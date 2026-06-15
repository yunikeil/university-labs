import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.Executor;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;


public class Main {

    public static void main(String[] args) throws Exception {
        CustomThreadPoolExecutor executor = new CustomThreadPoolExecutor(
                "pepePool", 2, 4, 5,
                TimeUnit.SECONDS, 2, 1,
                new CallerRunsPolicy()
        );

        CustomLogger.log("[Main] Submitting runnable tasks.");
        for (int i = 1; i <= 10; i++) {
            try {
                executor.execute(new DemoTask(i, 2500));
            } catch (Exception e) {
                CustomLogger.log("[Main] Failed to submit task #%d: %s", i, e.getMessage());
            }
        }

        CustomLogger.log("[Main] Submitting callable tasks.");
        List<Future<String>> futures = new ArrayList<>();
        for (int i = 11; i <= 13; i++) {
            final int taskId = i;
            try {
                futures.add(executor.submit(() -> {
                    CustomLogger.log("[Callable] #%d started on %s", taskId, Thread.currentThread().getName());
                    Thread.sleep(1500);
                    CustomLogger.log("[Callable] #%d finished on %s", taskId, Thread.currentThread().getName());
                    return "result-" + taskId;
                }));
            } catch (Exception e) {
                CustomLogger.log("[Main] Failed to submit callable #%d: %s", i, e.getMessage());
            }
        }

        for (Future<String> future : futures) {
            CustomLogger.log("[Main] Callable result received: %s", future.get());
        }

        Thread.sleep(7000);
        CustomLogger.log("[Main] Current state: workers=%d busy=%d idle=%d queued=%d",
                executor.getWorkerCount(),
                executor.getBusyWorkers(),
                executor.getIdleWorkers(),
                executor.getTotalQueuedTasks());

        executor.shutdown();

        Thread.sleep(6000);
        CustomLogger.log("[Main] Final state after shutdown: workers=%d busy=%d idle=%d queued=%d",
                executor.getWorkerCount(),
                executor.getBusyWorkers(),
                executor.getIdleWorkers(),
                executor.getTotalQueuedTasks());
    }

    interface CustomExecutor extends Executor {
        @Override
        void execute(Runnable command);

        <T> Future<T> submit(Callable<T> callable);

        void shutdown();

        void shutdownNow();
    }

    @FunctionalInterface
    interface RejectedTaskPolicy {
        void reject(Task task, CustomThreadPoolExecutor executor);
    }

    static class AbortPolicy implements RejectedTaskPolicy {
        @Override
        public void reject(Task task, CustomThreadPoolExecutor executor) {
            CustomLogger.log("[Rejected] Task %s was rejected due to overload!", task);
            throw new RejectedExecutionException("Task rejected: " + task);
        }
    }

    static class CallerRunsPolicy implements RejectedTaskPolicy {
        @Override
        public void reject(Task task, CustomThreadPoolExecutor executor) {
            if (executor.isShutdown()) {
                CustomLogger.log("[Rejected] Task %s was rejected because executor is shutting down.", task);
                return;
            }
            CustomLogger.log("[Rejected] Overload detected, running task %s in caller thread %s.",
                    task,
                    Thread.currentThread().getName());
            task.run();
        }
    }

    static final class CustomLogger {
        private static final DateTimeFormatter FORMATTER = DateTimeFormatter.ofPattern("HH:mm:ss.SSS");

        private CustomLogger() {
        }

        public static synchronized void log(String template, Object... args) {
            String prefix = LocalTime.now().format(FORMATTER);
            String message = String.format(template, args);
            System.out.printf("%s %s%n", prefix, message);
        }
    }

    static class LoggingThreadFactory implements java.util.concurrent.ThreadFactory {
        private final String poolName;
        private final AtomicInteger counter = new AtomicInteger(1);

        public LoggingThreadFactory(String poolName) {
            this.poolName = poolName;
        }

        @Override
        public Thread newThread(Runnable runnable) {
            String threadName = poolName + "-worker-" + counter.getAndIncrement();
            CustomLogger.log("[ThreadFactory] Creating new thread: %s", threadName);

            Thread thread = new Thread(() -> {
                try {
                    runnable.run();
                } finally {
                    CustomLogger.log("[Worker] %s terminated.", Thread.currentThread().getName());
                }
            }, threadName);
            thread.setDaemon(false);
            return thread;
        }
    }

    static class Task extends FutureTask<Object> {
        private static final AtomicLong IDS = new AtomicLong(1);

        private final long id;
        private final String description;

        public Task(Runnable runnable, String description) {
            super(runnable, null);
            this.id = IDS.getAndIncrement();
            this.description = normalizeDescription(description, runnable);
        }

        @SuppressWarnings("unchecked")
        public <T> Task(Callable<T> callable, String description) {
            super((Callable<Object>) callable);
            this.id = IDS.getAndIncrement();
            this.description = normalizeDescription(description, callable);
        }

        private String normalizeDescription(String description, Object fallback) {
            if (description != null && !description.isBlank()) {
                return description;
            }
            return fallback.getClass().getSimpleName() + "@" + Integer.toHexString(System.identityHashCode(fallback));
        }

        @Override
        public String toString() {
            return "Task{id=" + id + ", description='" + description + "'}";
        }
    }

    static class WorkerQueue {
        private final int id;
        private final BlockingQueue<Task> queue;
        private final AtomicBoolean workerAssigned = new AtomicBoolean(false);

        public WorkerQueue(int id, int capacity) {
            this.id = id;
            this.queue = new ArrayBlockingQueue<>(capacity);
        }

        public int getId() {
            return id;
        }

        public int size() {
            return queue.size();
        }

        public int remainingCapacity() {
            return queue.remainingCapacity();
        }

        public boolean offer(Task task) {
            return queue.offer(task);
        }

        public Task poll(long timeout, TimeUnit unit) throws InterruptedException {
            return queue.poll(timeout, unit);
        }

        public void drainAndCancel() {
            Task task;
            while ((task = queue.poll()) != null) {
                task.cancel(true);
            }
        }

        public boolean tryAcquireWorkerSlot() {
            return workerAssigned.compareAndSet(false, true);
        }

        public void releaseWorkerSlot() {
            workerAssigned.set(false);
        }

        public boolean hasWorker() {
            return workerAssigned.get();
        }
    }

    static class CustomThreadPoolExecutor implements CustomExecutor {
        private final String poolName;
        private final int corePoolSize;
        private final int maxPoolSize;
        private final long keepAliveTime;
        private final TimeUnit timeUnit;
        private final int minSpareThreads;
        private final LoggingThreadFactory threadFactory;
        private final RejectedTaskPolicy rejectedTaskPolicy;
        private final List<WorkerQueue> queues;
        private final AtomicInteger workerCount = new AtomicInteger();
        private final AtomicInteger busyWorkers = new AtomicInteger();
        private final AtomicLong roundRobinCursor = new AtomicLong();
        private final Object lifecycleLock = new Object();

        private volatile boolean shutdown;

        public CustomThreadPoolExecutor(
                String poolName,
                int corePoolSize,
                int maxPoolSize,
                long keepAliveTime,
                TimeUnit timeUnit,
                int queueSize,
                int minSpareThreads,
                RejectedTaskPolicy rejectedTaskPolicy
        ) {
            if (corePoolSize <= 0 || maxPoolSize <= 0 || queueSize <= 0) {
                throw new IllegalArgumentException("Pool sizes and queue size must be positive.");
            }
            if (corePoolSize > maxPoolSize) {
                throw new IllegalArgumentException("corePoolSize cannot exceed maxPoolSize.");
            }
            if (minSpareThreads < 0 || minSpareThreads > maxPoolSize) {
                throw new IllegalArgumentException("minSpareThreads must be between 0 and maxPoolSize.");
            }

            this.poolName = Objects.requireNonNull(poolName, "poolName");
            this.corePoolSize = corePoolSize;
            this.maxPoolSize = maxPoolSize;
            this.keepAliveTime = keepAliveTime;
            this.timeUnit = Objects.requireNonNull(timeUnit, "timeUnit");
            this.minSpareThreads = minSpareThreads;
            this.threadFactory = new LoggingThreadFactory(poolName);
            this.rejectedTaskPolicy = Objects.requireNonNull(rejectedTaskPolicy, "rejectedTaskPolicy");
            this.queues = new ArrayList<>(maxPoolSize);

            for (int i = 0; i < maxPoolSize; i++) {
                this.queues.add(new WorkerQueue(i, queueSize));
            }

            CustomLogger.log("[Pool] %s initialized: core=%d, max=%d, keepAlive=%d %s, queueSize=%d, minSpare=%d",
                    poolName, corePoolSize, maxPoolSize, keepAliveTime, timeUnit, queueSize, minSpareThreads);

            prestartCoreWorkers();
        }

        private void prestartCoreWorkers() {
            synchronized (lifecycleLock) {
                for (int i = 0; i < corePoolSize; i++) {
                    WorkerQueue queue = queues.get(i);
                    if (!queue.hasWorker() && queue.tryAcquireWorkerSlot()) {
                        startWorker(queue);
                    }
                }
            }
        }

        @Override
        public void execute(Runnable command) {
            Objects.requireNonNull(command, "command");
            submitTask(new Task(command, command.toString()));
        }

        @Override
        public <T> Future<T> submit(Callable<T> callable) {
            Objects.requireNonNull(callable, "callable");
            Task task = new Task(callable, callable.toString());
            submitTask(task);
            @SuppressWarnings("unchecked")
            Future<T> future = (Future<T>) task;
            return future;
        }

        private void submitTask(Task task) {
            if (shutdown) {
                rejectedTaskPolicy.reject(task, this);
                return;
            }

            ensureMinSpareThreads();

            WorkerQueue queue = chooseQueue();
            if (queue != null && queue.offer(task)) {
                CustomLogger.log("[Pool] Task accepted into queue #%d: %s", queue.getId(), task);
                maybeScaleUp();
                return;
            }

            WorkerQueue fallbackQueue = chooseLeastLoadedQueueWithCapacity();
            if (fallbackQueue != null && fallbackQueue.offer(task)) {
                CustomLogger.log("[Pool] Task accepted into queue #%d after fallback: %s", fallbackQueue.getId(), task);
                maybeScaleUp();
                return;
            }

            maybeScaleUpToHandleBurst();

            WorkerQueue retryQueue = chooseLeastLoadedQueueWithCapacity();
            if (retryQueue != null && retryQueue.offer(task)) {
                CustomLogger.log("[Pool] Task accepted into queue #%d after scaling: %s", retryQueue.getId(), task);
                return;
            }

            rejectedTaskPolicy.reject(task, this);
        }

        private WorkerQueue chooseQueue() {
            long index = roundRobinCursor.getAndIncrement();
            return queues.get((int) Math.floorMod(index, queues.size()));
        }

        private WorkerQueue chooseLeastLoadedQueueWithCapacity() {
            WorkerQueue best = null;
            int bestLoad = Integer.MAX_VALUE;
            for (WorkerQueue queue : queues) {
                if (queue.remainingCapacity() <= 0) {
                    continue;
                }
                int size = queue.size();
                if (size < bestLoad) {
                    bestLoad = size;
                    best = queue;
                }
            }
            return best;
        }

        private void ensureMinSpareThreads() {
            synchronized (lifecycleLock) {
                int idleWorkers = workerCount.get() - busyWorkers.get();
                while (!shutdown && idleWorkers < minSpareThreads && workerCount.get() < maxPoolSize) {
                    WorkerQueue queue = findQueueWithoutWorker();
                    if (queue == null) {
                        break;
                    }
                    startWorker(queue);
                    idleWorkers = workerCount.get() - busyWorkers.get();
                }
            }
        }

        private void maybeScaleUp() {
            synchronized (lifecycleLock) {
                if (shutdown || workerCount.get() >= maxPoolSize) {
                    return;
                }

                int totalQueuedTasks = totalQueuedTasks();
                int idleWorkers = workerCount.get() - busyWorkers.get();
                if (totalQueuedTasks > idleWorkers) {
                    WorkerQueue queue = findQueueWithoutWorker();
                    if (queue != null) {
                        startWorker(queue);
                    }
                }
            }
        }

        private void maybeScaleUpToHandleBurst() {
            synchronized (lifecycleLock) {
                if (shutdown || workerCount.get() >= maxPoolSize) {
                    return;
                }
                WorkerQueue queue = findQueueWithoutWorker();
                if (queue != null) {
                    startWorker(queue);
                }
            }
        }

        private int totalQueuedTasks() {
            int total = 0;
            for (WorkerQueue queue : queues) {
                total += queue.size();
            }
            return total;
        }

        private WorkerQueue findQueueWithoutWorker() {
            for (WorkerQueue queue : queues) {
                if (queue.tryAcquireWorkerSlot()) {
                    return queue;
                }
            }
            return null;
        }

        private void startWorker(WorkerQueue queue) {
            int currentWorkers = workerCount.incrementAndGet();
            CustomLogger.log("[Pool] Starting worker for queue #%d. Active workers=%d", queue.getId(), currentWorkers);
            Thread workerThread = threadFactory.newThread(new Worker(queue));
            workerThread.start();
        }

        @Override
        public void shutdown() {
            shutdown = true;
            CustomLogger.log("[Pool] Shutdown requested for %s. New tasks will be rejected.", poolName);
        }

        @Override
        public void shutdownNow() {
            shutdown = true;
            CustomLogger.log("[Pool] ShutdownNow requested for %s. Queued tasks will be cancelled.", poolName);
            for (WorkerQueue queue : queues) {
                queue.drainAndCancel();
            }
        }

        public boolean isShutdown() {
            return shutdown;
        }

        public int getWorkerCount() {
            return workerCount.get();
        }

        public int getBusyWorkers() {
            return busyWorkers.get();
        }

        public int getIdleWorkers() {
            return getWorkerCount() - getBusyWorkers();
        }

        public int getTotalQueuedTasks() {
            return totalQueuedTasks();
        }

        private class Worker implements Runnable {
            private final WorkerQueue queue;

            private Worker(WorkerQueue queue) {
                this.queue = queue;
            }

            @Override
            public void run() {
                try {
                    workerLoop();
                } finally {
                    queue.releaseWorkerSlot();
                    int remaining = workerCount.decrementAndGet();
                    CustomLogger.log("[Pool] Worker for queue #%d stopped. Remaining workers=%d", queue.getId(), remaining);
                }
            }

            private void workerLoop() {
                while (true) {
                    if (shutdown && queue.size() == 0) {
                        CustomLogger.log("[Worker] %s noticed shutdown and empty queue, stopping.", Thread.currentThread().getName());
                        return;
                    }

                    try {
                        Task task = queue.poll(keepAliveTime, timeUnit);
                        if (task == null) {
                            if (shouldStopOnIdleTimeout()) {
                                CustomLogger.log("[Worker] %s idle timeout, stopping.", Thread.currentThread().getName());
                                return;
                            }
                            continue;
                        }

                        if (shutdown && task.isCancelled()) {
                            continue;
                        }

                        busyWorkers.incrementAndGet();
                        try {
                            if (shutdown && Thread.currentThread().isInterrupted()) {
                                CustomLogger.log("[Worker] %s is interrupted during shutdown, skipping %s",
                                        Thread.currentThread().getName(), task);
                                task.cancel(true);
                                continue;
                            }
                            CustomLogger.log("[Worker] %s executes %s", Thread.currentThread().getName(), task);
                            task.run();
                        } finally {
                            busyWorkers.decrementAndGet();
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        CustomLogger.log("[Worker] %s interrupted, stopping.", Thread.currentThread().getName());
                        return;
                    } catch (RuntimeException e) {
                        CustomLogger.log("[Worker] %s failed with runtime error: %s",
                                Thread.currentThread().getName(), e.getMessage());
                    }
                }
            }

            private boolean shouldStopOnIdleTimeout() {
                synchronized (lifecycleLock) {
                    if (workerCount.get() > corePoolSize) {
                        return true;
                    }
                    int idleWorkers = workerCount.get() - busyWorkers.get();
                    return idleWorkers > minSpareThreads && workerCount.get() > corePoolSize;
                }
            }
        }
    }

    static class DemoTask implements Runnable {
        private final int taskId;
        private final long durationMillis;

        public DemoTask(int taskId, long durationMillis) {
            this.taskId = taskId;
            this.durationMillis = durationMillis;
        }

        @Override
        public void run() {
            CustomLogger.log("[Task] #%d started on %s", taskId, Thread.currentThread().getName());
            try {
                Thread.sleep(durationMillis);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                CustomLogger.log("[Task] #%d interrupted on %s", taskId, Thread.currentThread().getName());
                return;
            }
            CustomLogger.log("[Task] #%d finished on %s", taskId, Thread.currentThread().getName());
        }

        @Override
        public String toString() {
            return "DemoTask{id=" + taskId + ", durationMs=" + durationMillis + "}";
        }
    }
}