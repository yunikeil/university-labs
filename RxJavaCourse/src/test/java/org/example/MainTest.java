package org.example;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

public class MainTest {

    @AfterAll
    static void shutdownSchedulers() {
        Main.Schedulers.shutdownAll();
    }

    @Test
    void testObserverBasicFlow() {
        List<String> events = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
            emitter.onNext(1);
            emitter.onNext(2);
            emitter.onComplete();
        }).subscribe(new Main.Observer<Integer>() {
            @Override
            public void onNext(Integer item) {
                events.add("next:" + item);
            }

            @Override
            public void onError(Throwable t) {
                events.add("error:" + t.getMessage());
            }

            @Override
            public void onComplete() {
                events.add("complete");
            }
        });

        assertEquals(List.of("next:1", "next:2", "complete"), events);
    }

    @Test
    void testCreateAndSubscribe() {
        List<Integer> result = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
            emitter.onNext(10);
            emitter.onNext(20);
            emitter.onComplete();
        }).subscribe(new Main.Observer<Integer>() {
            @Override
            public void onNext(Integer item) {
                result.add(item);
            }

            @Override
            public void onError(Throwable t) {
                fail("No error expected");
            }

            @Override
            public void onComplete() {
            }
        });

        assertEquals(List.of(10, 20), result);
    }

    @Test
    void testJust() {
        List<String> result = new ArrayList<>();

        Main.Observable.just("A", "B", "C")
                .subscribe(new Main.Observer<String>() {
                    @Override
                    public void onNext(String item) {
                        result.add(item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                    }
                });

        assertEquals(List.of("A", "B", "C"), result);
    }

    @Test
    void testMap() {
        List<Integer> result = new ArrayList<>();

        Main.Observable.just(1, 2, 3)
                .map(x -> x * 2)
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        result.add(item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                    }
                });

        assertEquals(List.of(2, 4, 6), result);
    }

    @Test
    void testMapThrowsError() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1, 2, 3)
                .map(x -> {
                    if (x == 2) {
                        throw new RuntimeException("boom");
                    }
                    return x * 10;
                })
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        events.add("next:" + item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        events.add("error:" + t.getMessage());
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("next:10", "error:boom"), events);
    }

    @Test
    void testFilter() {
        List<Integer> result = new ArrayList<>();

        Main.Observable.just(1, 2, 3, 4, 5, 6)
                .filter(x -> x % 2 == 0)
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        result.add(item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                    }
                });

        assertEquals(List.of(2, 4, 6), result);
    }

    @Test
    void testFilterThrowsError() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1, 2, 3)
                .filter(x -> {
                    if (x == 2) {
                        throw new RuntimeException("predicate failed");
                    }
                    return true;
                })
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        events.add("next:" + item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        events.add("error:" + t.getMessage());
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("next:1", "error:predicate failed"), events);
    }

    @Test
    void testFlatMap() {
        List<String> result = new ArrayList<>();

        Main.Observable.just("A", "B")
                .flatMap(x -> Main.Observable.just(x + "1", x + "2"))
                .subscribe(new Main.Observer<String>() {
                    @Override
                    public void onNext(String item) {
                        result.add(item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                    }
                });

        assertEquals(List.of("A1", "A2", "B1", "B2"), result);
    }

    @Test
    void testFlatMapMapperThrowsError() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1, 2, 3)
                .flatMap(x -> {
                    if (x == 2) {
                        throw new RuntimeException("flatMap failed");
                    }
                    return Main.Observable.just(x * 10);
                })
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        events.add("next:" + item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        events.add("error:" + t.getMessage());
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("next:10", "error:flatMap failed"), events);
    }

    @Test
    void testFlatMapReturnsNull() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1)
                .flatMap(x -> null)
                .subscribe(new Main.Observer<Object>() {
                    @Override
                    public void onNext(Object item) {
                        events.add("next");
                    }

                    @Override
                    public void onError(Throwable t) {
                        events.add("error:" + t.getMessage());
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("error:flatMap mapper returned null"), events);
    }

    @Test
    void testFlatMapInnerError() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1, 2)
                .flatMap(x -> Main.Observable.<Integer>create(emitter -> {
                    if (x == 2) {
                        emitter.onError(new RuntimeException("inner boom"));
                        return;
                    }
                    emitter.onNext(x);
                    emitter.onComplete();
                }))
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        events.add("next:" + item);
                    }

                    @Override
                    public void onError(Throwable t) {
                        events.add("error:" + t.getMessage());
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("next:1", "error:inner boom"), events);
    }

    @Test
    void testOnComplete() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1)
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        events.add("next");
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("next", "complete"), events);
    }

    @Test
    void testSourceThrowsError() {
        List<String> events = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
            throw new RuntimeException("source failed");
        }).subscribe(new Main.Observer<Integer>() {
            @Override
            public void onNext(Integer item) {
                events.add("next");
            }

            @Override
            public void onError(Throwable t) {
                events.add("error:" + t.getMessage());
            }

            @Override
            public void onComplete() {
                events.add("complete");
            }
        });

        assertEquals(List.of("error:source failed"), events);
    }

    @Test
    void testSubscribeWithLambdaOnNextOnly() {
        List<Integer> result = new ArrayList<>();

        Main.Observable.just(1, 2, 3)
                .subscribe(result::add);

        assertEquals(List.of(1, 2, 3), result);
    }

    @Test
    void testSubscribeWithThreeCallbacks() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(5, 6)
                .subscribe(
                        item -> events.add("next:" + item),
                        error -> events.add("error:" + error.getMessage()),
                        () -> events.add("complete")
                );

        assertEquals(List.of("next:5", "next:6", "complete"), events);
    }

    @Test
    void testBooleanDisposable() {
        Main.BooleanDisposable disposable = new Main.BooleanDisposable();

        assertFalse(disposable.isDisposed());

        disposable.dispose();

        assertTrue(disposable.isDisposed());
    }

    @Test
    void testCompositeDisposable() {
        Main.BooleanDisposable d1 = new Main.BooleanDisposable();
        Main.BooleanDisposable d2 = new Main.BooleanDisposable();
        Main.CompositeDisposable composite = new Main.CompositeDisposable();

        composite.add(d1);
        composite.add(d2);

        assertFalse(composite.isDisposed());
        assertFalse(d1.isDisposed());
        assertFalse(d2.isDisposed());

        composite.dispose();

        assertTrue(composite.isDisposed());
        assertTrue(d1.isDisposed());
        assertTrue(d2.isDisposed());
    }

    @Test
    void testCompositeDisposableAddAfterDispose() {
        Main.CompositeDisposable composite = new Main.CompositeDisposable();
        composite.dispose();

        Main.BooleanDisposable d = new Main.BooleanDisposable();
        composite.add(d);

        assertTrue(d.isDisposed());
    }

    @Test
    void testDisposableStopsEmission() {
        List<Integer> result = new ArrayList<>();
        Main.Disposable[] ref = new Main.Disposable[1];

        ref[0] = Main.Observable.<Integer>create(emitter -> {
            for (int i = 1; i <= 10; i++) {
                if (emitter.isDisposed()) {
                    return;
                }
                emitter.onNext(i);
            }
            emitter.onComplete();
        }).subscribe(new Main.Observer<Integer>() {
            @Override
            public void onNext(Integer item) {
                result.add(item);
                if (item == 3) {
                    ref[0].dispose();
                }
            }

            @Override
            public void onError(Throwable t) {
                fail("No error expected");
            }

            @Override
            public void onComplete() {
            }
        });

        assertEquals(List.of(1, 2, 3), result);
    }

    @Test
    void testSchedulerExecuteIo() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(1);
        List<String> threadNames = new ArrayList<>();

        Main.Disposable disposable = Main.Schedulers.io().execute(() -> {
            threadNames.add(Thread.currentThread().getName());
            latch.countDown();
        });

        assertNotNull(disposable);
        assertTrue(latch.await(2, TimeUnit.SECONDS));
        assertFalse(threadNames.isEmpty());
    }

    @Test
    void testSchedulerExecuteComputation() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(1);
        List<String> threadNames = new ArrayList<>();

        Main.Disposable disposable = Main.Schedulers.computation().execute(() -> {
            threadNames.add(Thread.currentThread().getName());
            latch.countDown();
        });

        assertNotNull(disposable);
        assertTrue(latch.await(2, TimeUnit.SECONDS));
        assertFalse(threadNames.isEmpty());
    }

    @Test
    void testSchedulerExecuteSingle() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(1);
        List<String> threadNames = new ArrayList<>();

        Main.Disposable disposable = Main.Schedulers.single().execute(() -> {
            threadNames.add(Thread.currentThread().getName());
            latch.countDown();
        });

        assertNotNull(disposable);
        assertTrue(latch.await(2, TimeUnit.SECONDS));
        assertFalse(threadNames.isEmpty());
    }

    @Test
    void testSubscribeOn() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(1);
        List<String> threadNames = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
                    threadNames.add(Thread.currentThread().getName());
                    emitter.onNext(1);
                    emitter.onComplete();
                }).subscribeOn(Main.Schedulers.io())
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                        latch.countDown();
                    }
                });

        assertTrue(latch.await(2, TimeUnit.SECONDS));
        assertFalse(threadNames.isEmpty());
    }

    @Test
    void testObserveOn() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(1);
        List<String> threadNames = new ArrayList<>();

        Main.Observable.just(1, 2, 3)
                .observeOn(Main.Schedulers.single())
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        threadNames.add(Thread.currentThread().getName());
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                        latch.countDown();
                    }
                });

        assertTrue(latch.await(2, TimeUnit.SECONDS));
        assertFalse(threadNames.isEmpty());
    }

    @Test
    void testSubscribeOnAndObserveOnTogether() throws InterruptedException {
        CountDownLatch latch = new CountDownLatch(1);
        List<String> sourceThreads = new ArrayList<>();
        List<String> observerThreads = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
                    sourceThreads.add(Thread.currentThread().getName());
                    emitter.onNext(1);
                    emitter.onComplete();
                }).subscribeOn(Main.Schedulers.io())
                .observeOn(Main.Schedulers.single())
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        observerThreads.add(Thread.currentThread().getName());
                    }

                    @Override
                    public void onError(Throwable t) {
                        fail("No error expected");
                    }

                    @Override
                    public void onComplete() {
                        latch.countDown();
                    }
                });

        assertTrue(latch.await(2, TimeUnit.SECONDS));
        assertFalse(sourceThreads.isEmpty());
        assertFalse(observerThreads.isEmpty());
    }

    @Test
    void testObserverOnNextThrows() {
        List<String> events = new ArrayList<>();

        Main.Observable.just(1, 2)
                .subscribe(new Main.Observer<Integer>() {
                    @Override
                    public void onNext(Integer item) {
                        events.add("next:" + item);
                        if (item == 1) {
                            throw new RuntimeException("observer failed");
                        }
                    }

                    @Override
                    public void onError(Throwable t) {
                        events.add("error:" + t.getMessage());
                    }

                    @Override
                    public void onComplete() {
                        events.add("complete");
                    }
                });

        assertEquals(List.of("next:1", "error:observer failed"), events);
    }

    @Test
    void testEmitterIgnoresSignalsAfterComplete() {
        List<String> events = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
            emitter.onNext(1);
            emitter.onComplete();
            emitter.onNext(2);
            emitter.onError(new RuntimeException("late error"));
        }).subscribe(new Main.Observer<Integer>() {
            @Override
            public void onNext(Integer item) {
                events.add("next:" + item);
            }

            @Override
            public void onError(Throwable t) {
                events.add("error:" + t.getMessage());
            }

            @Override
            public void onComplete() {
                events.add("complete");
            }
        });

        assertEquals(List.of("next:1", "complete"), events);
    }

    @Test
    void testEmitterIgnoresSignalsAfterError() {
        List<String> events = new ArrayList<>();

        Main.Observable.<Integer>create(emitter -> {
            emitter.onNext(1);
            emitter.onError(new RuntimeException("boom"));
            emitter.onNext(2);
            emitter.onComplete();
        }).subscribe(new Main.Observer<Integer>() {
            @Override
            public void onNext(Integer item) {
                events.add("next:" + item);
            }

            @Override
            public void onError(Throwable t) {
                events.add("error:" + t.getMessage());
            }

            @Override
            public void onComplete() {
                events.add("complete");
            }
        });

        assertEquals(List.of("next:1", "error:boom"), events);
    }

    @Test
    void testNullCreateSource() {
        assertThrows(NullPointerException.class, () -> Main.Observable.create(null));
    }

    @Test
    void testNullSubscribeObserver() {
        Main.Observable<Integer> observable = Main.Observable.just(1, 2, 3);
        assertThrows(NullPointerException.class, () -> observable.subscribe((Main.Observer<Integer>) null));
    }

    @Test
    void testNullMapMapper() {
        Main.Observable<Integer> observable = Main.Observable.just(1, 2, 3);
        assertThrows(NullPointerException.class, () -> observable.map(null));
    }

    @Test
    void testNullFilterPredicate() {
        Main.Observable<Integer> observable = Main.Observable.just(1, 2, 3);
        assertThrows(NullPointerException.class, () -> observable.filter(null));
    }

    @Test
    void testNullFlatMapMapper() {
        Main.Observable<Integer> observable = Main.Observable.just(1, 2, 3);
        assertThrows(NullPointerException.class, () -> observable.flatMap(null));
    }

    @Test
    void testNullSubscribeOnScheduler() {
        Main.Observable<Integer> observable = Main.Observable.just(1, 2, 3);
        assertThrows(NullPointerException.class, () -> observable.subscribeOn(null));
    }

    @Test
    void testNullObserveOnScheduler() {
        Main.Observable<Integer> observable = Main.Observable.just(1, 2, 3);
        assertThrows(NullPointerException.class, () -> observable.observeOn(null));
    }
}