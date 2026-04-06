package org.example;

import java.util.List;
import java.util.Objects;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;
import java.util.function.Predicate;

public class Main {

    public static void main(String[] args) throws InterruptedException {
        System.out.println("=== Example 1: map + filter + subscribeOn + observeOn ===");

        Disposable d1 = Observable.<Integer>create(emitter -> {
                    for (int i = 1; i <= 10; i++) {
                        if (emitter.isDisposed()) {
                            System.out.println("Source stopped because disposed");
                            return;
                        }
                        Thread.sleep(100);
                        emitter.onNext(i);
                    }
                    emitter.onComplete();
                })
                .subscribeOn(Schedulers.io())
                .map(x -> x * 2)
                .filter(x -> x % 4 == 0)
                .observeOn(Schedulers.single())
                .subscribe(
                        item -> System.out.println("Received: " + item + " | thread=" + Thread.currentThread().getName()),
                        error -> System.out.println("Error: " + error.getMessage()),
                        () -> System.out.println("Completed | thread=" + Thread.currentThread().getName())
                );

        Thread.sleep(1500);

        System.out.println();
        System.out.println("=== Example 2: flatMap ===");

        Observable.just("A", "B", "C")
                .flatMap(letter ->
                        Observable.<String>create(emitter -> {
                            emitter.onNext(letter + "-1");
                            emitter.onNext(letter + "-2");
                            emitter.onComplete();
                        }).subscribeOn(Schedulers.computation())
                )
                .observeOn(Schedulers.single())
                .subscribe(
                        item -> System.out.println("flatMap item: " + item + " | thread=" + Thread.currentThread().getName()),
                        error -> System.out.println("flatMap error: " + error.getMessage()),
                        () -> System.out.println("flatMap complete")
                );

        Thread.sleep(1000);

        System.out.println();
        System.out.println("=== Example 3: error handling ===");

        Observable.just(10, 5, 0, 2)
                .map(x -> 100 / x)
                .subscribe(
                        item -> System.out.println("division result: " + item),
                        error -> System.out.println("Caught error in onError(): " + error),
                        () -> System.out.println("division complete")
                );

        System.out.println();
        System.out.println("=== Example 4: dispose ===");

        Disposable d2 = Observable.<Integer>create(emitter -> {
                    int i = 1;
                    while (!emitter.isDisposed()) {
                        emitter.onNext(i++);
                        Thread.sleep(200);
                    }
                    System.out.println("Emitter noticed disposal and stopped");
                })
                .subscribeOn(Schedulers.io())
                .observeOn(Schedulers.single())
                .subscribe(
                        item -> System.out.println("stream item: " + item),
                        error -> System.out.println("stream error: " + error),
                        () -> System.out.println("stream complete")
                );

        Thread.sleep(900);
        d2.dispose();
        System.out.println("Subscription disposed from main");

        Thread.sleep(1000);

        Schedulers.shutdownAll();
    }

    public interface Observer<T> {
        void onNext(T item);
        void onError(Throwable t);
        void onComplete();
    }

    public interface Disposable {
        void dispose();
        boolean isDisposed();
    }

    public static class BooleanDisposable implements Disposable {
        private final AtomicBoolean disposed = new AtomicBoolean(false);

        @Override
        public void dispose() {
            disposed.set(true);
        }

        @Override
        public boolean isDisposed() {
            return disposed.get();
        }
    }

    public static class CompositeDisposable implements Disposable {
        private final List<Disposable> disposables = new CopyOnWriteArrayList<>();
        private final AtomicBoolean disposed = new AtomicBoolean(false);

        public void add(Disposable disposable) {
            if (disposable == null) {
                return;
            }
            if (disposed.get()) {
                disposable.dispose();
            } else {
                disposables.add(disposable);
            }
        }

        @Override
        public void dispose() {
            if (disposed.compareAndSet(false, true)) {
                for (Disposable disposable : disposables) {
                    disposable.dispose();
                }
                disposables.clear();
            }
        }

        @Override
        public boolean isDisposed() {
            return disposed.get();
        }
    }

    @FunctionalInterface
    public interface Consumer<T> {
        void accept(T t) throws Exception;
    }

    @FunctionalInterface
    public interface Action {
        void run() throws Exception;
    }

    @FunctionalInterface
    public interface OnSubscribe<T> {
        void subscribe(Emitter<T> emitter) throws Exception;
    }

    public interface Emitter<T> {
        void onNext(T item);
        void onError(Throwable t);
        void onComplete();
        boolean isDisposed();
    }

    public interface Scheduler {
        Disposable execute(Runnable task);
    }

    public static class ExecutorScheduler implements Scheduler {
        private final ExecutorService executor;

        public ExecutorScheduler(ExecutorService executor) {
            this.executor = executor;
        }

        @Override
        public Disposable execute(Runnable task) {
            Future<?> future = executor.submit(task);
            return new Disposable() {
                @Override
                public void dispose() {
                    future.cancel(true);
                }

                @Override
                public boolean isDisposed() {
                    return future.isCancelled() || future.isDone();
                }
            };
        }

        public void shutdown() {
            executor.shutdownNow();
        }
    }

    public static class Schedulers {
        private static final ExecutorScheduler IO =
                new ExecutorScheduler(Executors.newCachedThreadPool());

        private static final ExecutorScheduler COMPUTATION =
                new ExecutorScheduler(
                        Executors.newFixedThreadPool(
                                Math.max(2, Runtime.getRuntime().availableProcessors())
                        )
                );

        private static final ExecutorScheduler SINGLE =
                new ExecutorScheduler(Executors.newSingleThreadExecutor());

        private Schedulers() {
        }

        public static Scheduler io() {
            return IO;
        }

        public static Scheduler computation() {
            return COMPUTATION;
        }

        public static Scheduler single() {
            return SINGLE;
        }

        public static void shutdownAll() {
            IO.shutdown();
            COMPUTATION.shutdown();
            SINGLE.shutdown();
        }
    }

    public static class Observable<T> {
        private final OnSubscribe<T> source;

        private Observable(OnSubscribe<T> source) {
            this.source = source;
        }

        public static <T> Observable<T> create(OnSubscribe<T> source) {
            Objects.requireNonNull(source, "source == null");
            return new Observable<T>(source);
        }

        @SafeVarargs
        public static <T> Observable<T> just(T... items) {
            return create(emitter -> {
                for (T item : items) {
                    if (emitter.isDisposed()) {
                        return;
                    }
                    emitter.onNext(item);
                }
                emitter.onComplete();
            });
        }

        public Disposable subscribe(Observer<T> observer) {
            Objects.requireNonNull(observer, "observer == null");

            BooleanDisposable upstream = new BooleanDisposable();

            Emitter<T> emitter = new Emitter<T>() {
                private final AtomicBoolean terminated = new AtomicBoolean(false);

                @Override
                public void onNext(T item) {
                    if (upstream.isDisposed() || terminated.get()) {
                        return;
                    }
                    try {
                        observer.onNext(item);
                    } catch (Throwable ex) {
                        onError(ex);
                    }
                }

                @Override
                public void onError(Throwable t) {
                    if (upstream.isDisposed() || !terminated.compareAndSet(false, true)) {
                        return;
                    }
                    observer.onError(t);
                    upstream.dispose();
                }

                @Override
                public void onComplete() {
                    if (upstream.isDisposed() || !terminated.compareAndSet(false, true)) {
                        return;
                    }
                    observer.onComplete();
                    upstream.dispose();
                }

                @Override
                public boolean isDisposed() {
                    return upstream.isDisposed();
                }
            };

            try {
                source.subscribe(emitter);
            } catch (Throwable t) {
                emitter.onError(t);
            }

            return upstream;
        }

        public Disposable subscribe(
                Consumer<T> onNext,
                Consumer<Throwable> onError,
                Action onComplete
        ) {
            return subscribe(new Observer<T>() {
                @Override
                public void onNext(T item) {
                    try {
                        onNext.accept(item);
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }
                }

                @Override
                public void onError(Throwable t) {
                    try {
                        onError.accept(t);
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }
                }

                @Override
                public void onComplete() {
                    try {
                        onComplete.run();
                    } catch (Exception e) {
                        throw new RuntimeException(e);
                    }
                }
            });
        }

        public Disposable subscribe(Consumer<T> onNext) {
            return subscribe(
                    onNext,
                    error -> {
                        throw new RuntimeException(error);
                    },
                    () -> {
                    }
            );
        }

        public <R> Observable<R> map(Function<? super T, ? extends R> mapper) {
            Objects.requireNonNull(mapper, "mapper == null");

            return create(emitter ->
                    Observable.this.subscribe(new Observer<T>() {
                        @Override
                        public void onNext(T item) {
                            if (emitter.isDisposed()) {
                                return;
                            }
                            try {
                                R mapped = mapper.apply(item);
                                emitter.onNext(mapped);
                            } catch (Throwable t) {
                                emitter.onError(t);
                            }
                        }

                        @Override
                        public void onError(Throwable t) {
                            emitter.onError(t);
                        }

                        @Override
                        public void onComplete() {
                            emitter.onComplete();
                        }
                    })
            );
        }

        public Observable<T> filter(Predicate<? super T> predicate) {
            Objects.requireNonNull(predicate, "predicate == null");

            return create(emitter ->
                    Observable.this.subscribe(new Observer<T>() {
                        @Override
                        public void onNext(T item) {
                            if (emitter.isDisposed()) {
                                return;
                            }
                            try {
                                if (predicate.test(item)) {
                                    emitter.onNext(item);
                                }
                            } catch (Throwable t) {
                                emitter.onError(t);
                            }
                        }

                        @Override
                        public void onError(Throwable t) {
                            emitter.onError(t);
                        }

                        @Override
                        public void onComplete() {
                            emitter.onComplete();
                        }
                    })
            );
        }

        public <R> Observable<R> flatMap(Function<? super T, Observable<R>> mapper) {
            Objects.requireNonNull(mapper, "mapper == null");

            return create(emitter -> {
                CompositeDisposable composite = new CompositeDisposable();
                AtomicBoolean sourceCompleted = new AtomicBoolean(false);
                AtomicBoolean once = new AtomicBoolean(false);
                Object lock = new Object();
                int[] activeInner = {0};

                Disposable outer = Observable.this.subscribe(new Observer<T>() {
                    @Override
                    public void onNext(T item) {
                        if (emitter.isDisposed()) {
                            return;
                        }

                        Observable<R> inner;
                        try {
                            inner = mapper.apply(item);
                            if (inner == null) {
                                emitter.onError(new NullPointerException("flatMap mapper returned null"));
                                return;
                            }
                        } catch (Throwable t) {
                            emitter.onError(t);
                            return;
                        }

                        synchronized (lock) {
                            activeInner[0]++;
                        }

                        Disposable innerDisposable = inner.subscribe(new Observer<R>() {
                            @Override
                            public void onNext(R innerItem) {
                                if (!emitter.isDisposed()) {
                                    emitter.onNext(innerItem);
                                }
                            }

                            @Override
                            public void onError(Throwable t) {
                                if (once.compareAndSet(false, true)) {
                                    composite.dispose();
                                    emitter.onError(t);
                                }
                            }

                            @Override
                            public void onComplete() {
                                boolean shouldComplete = false;
                                synchronized (lock) {
                                    activeInner[0]--;
                                    if (sourceCompleted.get() && activeInner[0] == 0) {
                                        shouldComplete = true;
                                    }
                                }
                                if (shouldComplete && once.compareAndSet(false, true)) {
                                    emitter.onComplete();
                                }
                            }
                        });

                        composite.add(innerDisposable);
                    }

                    @Override
                    public void onError(Throwable t) {
                        if (once.compareAndSet(false, true)) {
                            composite.dispose();
                            emitter.onError(t);
                        }
                    }

                    @Override
                    public void onComplete() {
                        boolean shouldComplete = false;
                        synchronized (lock) {
                            sourceCompleted.set(true);
                            if (activeInner[0] == 0) {
                                shouldComplete = true;
                            }
                        }
                        if (shouldComplete && once.compareAndSet(false, true)) {
                            emitter.onComplete();
                        }
                    }
                });

                composite.add(outer);
            });
        }

        public Observable<T> subscribeOn(Scheduler scheduler) {
            Objects.requireNonNull(scheduler, "scheduler == null");

            return create(emitter -> scheduler.execute(() -> {
                if (emitter.isDisposed()) {
                    return;
                }

                Observable.this.subscribe(new Observer<T>() {
                    @Override
                    public void onNext(T item) {
                        if (!emitter.isDisposed()) {
                            emitter.onNext(item);
                        }
                    }

                    @Override
                    public void onError(Throwable t) {
                        if (!emitter.isDisposed()) {
                            emitter.onError(t);
                        }
                    }

                    @Override
                    public void onComplete() {
                        if (!emitter.isDisposed()) {
                            emitter.onComplete();
                        }
                    }
                });
            }));
        }

        public Observable<T> observeOn(Scheduler scheduler) {
            Objects.requireNonNull(scheduler, "scheduler == null");

            return create(emitter ->
                    Observable.this.subscribe(new Observer<T>() {
                        @Override
                        public void onNext(T item) {
                            scheduler.execute(() -> {
                                if (!emitter.isDisposed()) {
                                    emitter.onNext(item);
                                }
                            });
                        }

                        @Override
                        public void onError(Throwable t) {
                            scheduler.execute(() -> {
                                if (!emitter.isDisposed()) {
                                    emitter.onError(t);
                                }
                            });
                        }

                        @Override
                        public void onComplete() {
                            scheduler.execute(() -> {
                                if (!emitter.isDisposed()) {
                                    emitter.onComplete();
                                }
                            });
                        }
                    })
            );
        }
    }
}