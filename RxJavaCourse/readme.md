# Mini RxJava

## Описание проекта

В рамках данной работы реализована упрощённая версия библиотеки RxJava на языке Java с использованием основных принципов реактивного программирования и паттерна Observer.

Проект позволяет:

* создавать реактивные потоки данных;
* подписываться на потоки через наблюдателей;
* преобразовывать данные с помощью операторов `map`, `filter`, `flatMap`;
* управлять потоками выполнения через `Scheduler`;
* использовать `subscribeOn()` и `observeOn()` для переключения потоков;
* отменять подписку через `Disposable`;
* обрабатывать ошибки через `onError()`.

Основная цель проекта — продемонстрировать, как можно реализовать базовые механизмы реактивной библиотеки без использования готовой RxJava.

---

## Реализованный функционал

### 1. Базовые компоненты

Реализованы следующие базовые сущности:

* `Observer<T>`

    * `onNext(T item)` — получение элемента потока;
    * `onError(Throwable t)` — обработка ошибки;
    * `onComplete()` — завершение потока.

* `Observable<T>`

    * поддерживает создание потока через `create(...)`;
    * поддерживает подписку через `subscribe(...)`.

* `Emitter<T>`

    * используется внутри источника для отправки событий подписчику.

* `Disposable`

    * позволяет отменять подписку.

---

## 2. Операторы преобразования

### `map(Function mapper)`

Преобразует каждый элемент потока по заданной функции.

Пример:

```java
Observable.just(1, 2, 3)
    .map(x -> x * 2);
```

### `filter(Predicate predicate)`

Оставляет только те элементы, которые удовлетворяют условию.

Пример:

```java
Observable.just(1, 2, 3, 4)
    .filter(x -> x % 2 == 0);
```

### `flatMap(Function<T, Observable<R>> mapper)`

Преобразует каждый элемент исходного потока в новый `Observable`, после чего объединяет результаты.

Пример:

```java
Observable.just("A", "B")
    .flatMap(x -> Observable.just(x + "-1", x + "-2"));
```

---

## 3. Управление потоками выполнения

Реализован интерфейс:

```java
Scheduler
```

с методом:

```java
Disposable execute(Runnable task)
```

### Реализованные Scheduler

#### `IOThreadScheduler`

Аналог `Schedulers.io()`.

Использует:

* `CachedThreadPool`

Подходит для:

* операций ввода-вывода;
* сетевых запросов;
* чтения и записи файлов;
* задач с ожиданием внешних ресурсов.

#### `ComputationScheduler`

Аналог `Schedulers.computation()`.

Использует:

* `FixedThreadPool`

Подходит для:

* вычислений;
* обработки данных;
* CPU-bound задач.

Размер пула потоков определяется числом доступных процессорных ядер.

#### `SingleThreadScheduler`

Аналог `Schedulers.single()`.

Использует:

* один поток (`SingleThreadExecutor`)

Подходит для:

* последовательной обработки событий;
* задач, где важен строгий порядок выполнения.

---

## 4. Методы `subscribeOn()` и `observeOn()`

### `subscribeOn(Scheduler scheduler)`

Определяет, в каком потоке будет выполняться подписка и исходный источник данных.

То есть код внутри `Observable.create(...)` будет выполняться в указанном scheduler.

### `observeOn(Scheduler scheduler)`

Определяет, в каком потоке будут вызываться методы подписчика:

* `onNext`
* `onError`
* `onComplete`

Это позволяет, например:

* производить вычисления в одном пуле потоков;
* обрабатывать результат в одном выделенном потоке.

---

## 5. Disposable и отмена подписки

Для отмены подписки реализован интерфейс:

```java
Disposable
```

с методами:

```java
void dispose();
boolean isDisposed();
```

Если подписка отменена, поток должен прекратить дальнейшую отправку элементов.

Также реализован `CompositeDisposable`, который позволяет хранить несколько подписок и завершать их одновременно.

---

## 6. Обработка ошибок

Во всех операторах предусмотрена обработка исключений.

Если внутри:

* `map`
* `filter`
* `flatMap`
* источника `Observable.create(...)`

возникает ошибка, она передаётся подписчику через:

```java
onError(Throwable t)
```

После этого поток считается завершённым.

---

## Архитектура проекта

В проекте реализованы следующие основные компоненты:

* `Observer<T>` — подписчик на поток;
* `Observable<T>` — источник данных;
* `Emitter<T>` — механизм отправки событий;
* `Disposable` — механизм отмены подписки;
* `Scheduler` — абстракция выполнения задач в потоке;
* `Schedulers` — фабрика и хранилище scheduler-ов;
* `BooleanDisposable` — простая реализация `Disposable`;
* `CompositeDisposable` — контейнер для нескольких подписок.

---

## Пример использования

В `Main.java` приведён пример использования библиотеки.

### Пример 1: map + filter + subscribeOn + observeOn

```java
Observable.<Integer>create(emitter -> {
    for (int i = 1; i <= 10; i++) {
        if (emitter.isDisposed()) {
            return;
        }
        emitter.onNext(i);
    }
    emitter.onComplete();
})
.subscribeOn(Schedulers.io())
.map(x -> x * 2)
.filter(x -> x % 4 == 0)
.observeOn(Schedulers.single())
.subscribe(
    item -> System.out.println("Received: " + item),
    error -> System.out.println("Error: " + error.getMessage()),
    () -> System.out.println("Completed")
);
```

### Пример 2: flatMap

```java
Observable.just("A", "B", "C")
    .flatMap(letter ->
        Observable.<String>create(emitter -> {
            emitter.onNext(letter + "-1");
            emitter.onNext(letter + "-2");
            emitter.onComplete();
        })
    )
    .subscribe(
        item -> System.out.println(item),
        error -> System.out.println(error.getMessage()),
        () -> System.out.println("Done")
    );
```

### Пример 3: обработка ошибок

```java
Observable.just(10, 5, 0, 2)
    .map(x -> 100 / x)
    .subscribe(
        item -> System.out.println(item),
        error -> System.out.println("Caught error: " + error),
        () -> System.out.println("Complete")
    );
```

### Пример 4: отмена подписки

```java
Disposable disposable = Observable.<Integer>create(emitter -> {
    int i = 1;
    while (!emitter.isDisposed()) {
        emitter.onNext(i++);
    }
})
.subscribe(
    item -> System.out.println(item),
    error -> System.out.println(error.getMessage()),
    () -> System.out.println("Complete")
);

disposable.dispose();
```
