from __future__ import annotations

import argparse
import signal
import subprocess
import time
from pathlib import Path


WATCHED_SUFFIXES = {".py", ".txt"}
IGNORED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def snapshot(root: Path) -> dict[Path, float]:
    """Возвращает времена изменения файлов, за которыми следим."""
    files: dict[Path, float] = {}

    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in WATCHED_SUFFIXES:
            files[path] = path.stat().st_mtime

    return files


def terminate(process: subprocess.Popen[bytes]) -> None:
    """Мягко останавливает дочерний процесс, затем добивает при необходимости."""
    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_with_reload(command: list[str], root: Path, interval: float) -> int:
    """Запускает команду и перезапускает её при изменении файлов."""
    last_snapshot = snapshot(root)
    process = subprocess.Popen(command)

    def stop(signum: int, frame: object) -> None:
        terminate(process)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    print(f"Watching {root} for changes: {', '.join(sorted(WATCHED_SUFFIXES))}")
    print(f"Started: {' '.join(command)}")

    while True:
        exit_code = process.poll()
        if exit_code is not None:
            return exit_code

        time.sleep(interval)
        current_snapshot = snapshot(root)

        if current_snapshot != last_snapshot:
            print()
            print("=" * 20, " Change detected, restarting process... ", "=" * 20)
            terminate(process)
            last_snapshot = current_snapshot
            process = subprocess.Popen(command)
            print(f"Restarted: {' '.join(command)}")


def run_oneshot_with_reload(command: list[str], root: Path, interval: float) -> int:
    """Выполняет короткую команду при старте и повторяет её при изменениях."""
    last_snapshot = snapshot(root)

    def run_once() -> int:
        print(f"Running: {' '.join(command)}")
        return subprocess.call(command)

    exit_code = run_once()
    if exit_code != 0:
        print(f"Command exited with code {exit_code}; waiting for changes anyway.")

    print(f"Watching {root} for changes: {', '.join(sorted(WATCHED_SUFFIXES))}")

    while True:
        time.sleep(interval)
        current_snapshot = snapshot(root)

        if current_snapshot != last_snapshot:
            print()
            print("=" * 20, " Change detected, running command... ", "=" * 20)
            last_snapshot = current_snapshot
            exit_code = run_once()
            if exit_code != 0:
                print(f"Command exited with code {exit_code}; waiting for changes anyway.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny polling reloader for Docker development.")
    parser.add_argument("--root", default=".", help="Directory to watch.")
    parser.add_argument("--interval", default=1.0, type=float, help="Polling interval in seconds.")
    parser.add_argument("--oneshot", action="store_true", help="Run command on start and after changes.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    command = args.command

    if command and command[0] == "--":
        command = command[1:]

    if not command:
        raise SystemExit("Command is required. Example: python scripts/dev_reload.py -- python -m app")

    if args.oneshot:
        exit_code = run_oneshot_with_reload(command, Path(args.root).resolve(), args.interval)
    else:
        exit_code = run_with_reload(command, Path(args.root).resolve(), args.interval)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
