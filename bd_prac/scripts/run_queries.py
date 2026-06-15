import os
import re
import sys
import textwrap

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("Установите зависимость: pip install psycopg2-binary")
    sys.exit(1)


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "bd_prac"),
    "user": os.getenv("DB_USER", "student"),
    "password": os.getenv("DB_PASSWORD", "student"),
}

MAX_COLUMN_WIDTH = int(os.getenv("MAX_COLUMN_WIDTH", "32"))


def format_value(value):
    return "NULL" if value is None else str(value)


def wrap_cell(value, width):
    text = format_value(value)
    if text == "":
        return [""]

    lines = []
    for part in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            part,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )
        lines.extend(wrapped or [""])
    return lines


def load_queries(path="sql/02_solutions.sql"):
    with open(path, "r", encoding="utf-8") as file:
        text = file.read()

    pattern = re.compile(
        r"-- Part (?P<part>\d+), Task (?P<task>\d+)\n(?P<sql>.*?)(?=\n-- Part \d+, Task \d+|\Z)",
        re.S,
    )
    return {
        f"{match.group('part')}.{match.group('task')}": match.group("sql").strip()
        for match in pattern.finditer(text)
    }


def print_rows(rows):
    if not rows:
        print("Запрос выполнен, строк нет.")
        return

    headers = list(rows[0].keys())
    widths = {
        header: min(
            MAX_COLUMN_WIDTH,
            max(len(str(header)), *(len(format_value(row[header])) for row in rows)),
        )
        for header in headers
    }
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))

    for row in rows:
        wrapped_cells = [wrap_cell(row[header], widths[header]) for header in headers]
        row_height = max(len(cell) for cell in wrapped_cells)

        for line_number in range(row_height):
            print(
                " | ".join(
                    (cell[line_number] if line_number < len(cell) else "").ljust(widths[header])
                    for cell, header in zip(wrapped_cells, headers)
                )
            )


def main():
    queries = load_queries()
    print("Доступные задачи:", ", ".join(sorted(queries.keys())))
    choice = input("Введите номер в формате часть.задача, например 2.4, или all: ").strip()

    selected = queries.items() if choice.lower() == "all" else [(choice, queries.get(choice))]
    if choice.lower() != "all" and selected[0][1] is None:
        print("Такой задачи нет.")
        sys.exit(1)

    with psycopg2.connect(**DB_CONFIG) as connection:
        for key, query in selected:
            print(f"\n=== Part {key.split('.')[0]}, Task {key.split('.')[1]} ===")
            print("\nSQL:")
            print(query)
            print("\nResult:")
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                print_rows(cursor.fetchall())


if __name__ == "__main__":
    main()
