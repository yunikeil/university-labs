# Домашнее задание по базам данных

Проект поднимает готовую PostgreSQL-среду через Docker Compose и содержит SQL-решения для четырех независимых наборов таблиц. Для удобной проверки есть интерактивный Python-скрипт: он показывает список задач, спрашивает номер, печатает SQL-запрос и выводит результат в консольной таблице.

## Что Внутри

```text
.
├── docker-compose.yml
├── requirements.txt
├── image.png
├── image-1.png
├── image-2.png
├── sql
│   ├── 01_init.sql
│   └── 02_solutions.sql
├── pgadmin
│   ├── servers.json
│   └── pgpass
└── scripts
    ├── Dockerfile
    └── run_queries.py
```

`docker-compose.yml` запускает PostgreSQL, pgAdmin и отдельный сервис `query-runner` для Python-скрипта. PostgreSQL автоматически создает базу `bd_prac`, а pgAdmin при первом старте уже содержит сервер `bd_prac_postgres`.

`sql/01_init.sql` создает схемы `part1`, `part2`, `part3`, `part4`, таблицы и тестовые данные. `sql/02_solutions.sql` хранит все готовые запросы, помеченные комментариями вида `-- Part 2, Task 4`.

`scripts/run_queries.py` читает запросы из `sql/02_solutions.sql`, дает выбрать задачу в формате `часть.задача`, выполняет ее в PostgreSQL и печатает SQL вместе с результатом. `scripts/Dockerfile` собирает контейнер для этого скрипта, поэтому локально не нужно устанавливать Python-зависимости.

## Запуск

Нужны только Docker и Docker Compose.

```bash
docker compose up -d
```

Доступы:

| Сервис | Адрес | Логин | Пароль |
|---|---|---|---|
| PostgreSQL | `localhost:5432` | `student` | `student` |
| pgAdmin | `http://localhost:5050` | `admin@example.com` | `admin` |

База данных PostgreSQL: `bd_prac`.

Если нужно полностью пересоздать контейнеры и данные:

```bash
docker compose down -v
docker compose up -d
```

## Python-Проверка

Основной способ проверки:

```bash
docker compose run --rm query-runner
```

Скрипт покажет доступные задачи и попросит ввод:

```text
Введите номер в формате часть.задача, например 2.4, или all:
```

Примеры:

- `1.1` — выполнить первую задачу первой части;
- `2.5` — выполнить пятую задачу второй части;
- `all` — выполнить все запросы.

Перед каждой таблицей скрипт печатает сам SQL-запрос. Длинные значения переносятся внутри колонок, а `NULL` отображается явно. По умолчанию ширина колонки ограничена `32` символами:

```bash
docker compose run --rm -e MAX_COLUMN_WIDTH=50 query-runner
```

## pgAdmin

Откройте `http://localhost:5050`, войдите под `admin@example.com` / `admin` и выберите сервер `bd_prac_postgres`. Он создается автоматически из `pgadmin/servers.json`; пароль подключения берется из `pgadmin/pgpass`.

В Query Tool можно выполнять запросы из `sql/02_solutions.sql`. Для выбора нужной схемы используется строка:

```sql
SET search_path TO part1;
```

Номер схемы соответствует номеру части: `part1`, `part2`, `part3`, `part4`.

## SQL-Решения

В `sql/02_solutions.sql` находятся все запросы:

```sql
-- Part 1, Task 1
-- Part 1, Task 2
-- Part 2, Task 1
...
-- Part 4, Task 3
```

Краткое содержание:

| Часть | Схема | Таблицы | Что проверяется |
|---|---|---|---|
| Part 1 | `part1` | `Vehicle`, `Car`, `Motorcycle`, `Bicycle` | фильтрация транспорта и объединение разных типов через `UNION ALL` |
| Part 2 | `part2` | `Classes`, `Cars`, `Races`, `Results` | агрегаты, средние позиции, оконные функции и сравнение внутри классов |
| Part 3 | `part3` | `Hotel`, `Room`, `Customer`, `Booking` | анализ бронирований, сумм, длительности проживания и категорий отелей |
| Part 4 | `part4` | `Departments`, `Roles`, `Employees`, `Projects`, `Tasks` | рекурсивные запросы по иерархии сотрудников и агрегация проектов/задач |

## Полезные Команды

Выполнить все SQL-решения через `psql`:

```bash
docker compose exec -T postgres psql -U student -d bd_prac -f /sql/02_solutions.sql
```

Проверить созданные таблицы:

```bash
docker compose exec -T postgres psql -U student -d bd_prac -c "SELECT schemaname, tablename FROM pg_tables WHERE schemaname LIKE 'part%' ORDER BY schemaname, tablename;"
```

Пересоздать схемы и тестовые данные без удаления контейнеров:

```bash
docker compose exec -T postgres psql -U student -d bd_prac -f /docker-entrypoint-initdb.d/01_init.sql
```

Остановить проект:

```bash
docker compose down
```
