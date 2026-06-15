from __future__ import annotations

import argparse
import os
import select
import sys
import time

from deploy_redirect_proxy import DEFAULT_HOST, DEFAULT_USER, SERVICE_NAME, connect


def stream_once(args: argparse.Namespace) -> None:
    client = connect(args)
    command = f"journalctl -u {args.service} -f -n {args.lines} --no-pager"

    try:
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(args.keepalive)

        print(f"remote$ {command}", flush=True)
        stdin, stdout, stderr = client.exec_command(command, get_pty=True)

        channel = stdout.channel
        while not channel.exit_status_ready():
            readable, _, _ = select.select([channel], [], [], args.idle_ping)

            if not readable:
                print("remote journal tail is still connected...", flush=True)
                continue

            while channel.recv_ready():
                data = channel.recv(4096).decode("utf-8", errors="replace")
                print(data, end="", flush=True)

            while channel.recv_stderr_ready():
                data = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                print(data, end="", file=sys.stderr, flush=True)

        exit_code = channel.recv_exit_status()
        raise RuntimeError(f"journalctl exited with code {exit_code}")
    finally:
        client.close()


def tail_logs(args: argparse.Namespace) -> None:
    while True:
        try:
            stream_once(args)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"remote journal tail disconnected: {exc}", flush=True)
            print(f"reconnecting in {args.reconnect_delay} seconds...", flush=True)
            time.sleep(args.reconnect_delay)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream remote systemd service logs over SSH.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Remote server IP or hostname.")
    parser.add_argument("--user", default=DEFAULT_USER, help="SSH user.")
    parser.add_argument("--port", default=22, type=int, help="SSH port.")
    parser.add_argument("--key", default=None, help="Path to SSH private key.")
    parser.add_argument("--password", action="store_true", help="Ask for SSH password instead of key auth.")
    parser.add_argument("--password-env", default=None, help="Read SSH password from this environment variable.")
    parser.add_argument("--timeout", default=20.0, type=float, help="SSH connection timeout.")
    parser.add_argument("--service", default=SERVICE_NAME, help="Remote systemd service name.")
    parser.add_argument("--lines", default=100, type=int, help="Initial journal lines to show.")
    parser.add_argument("--keepalive", default=15, type=int, help="SSH keepalive interval in seconds.")
    parser.add_argument("--idle-ping", default=60, type=float, help="Print heartbeat after this many quiet seconds.")
    parser.add_argument("--reconnect-delay", default=3.0, type=float, help="Delay before reconnecting after disconnect.")
    return parser.parse_args()


def main() -> None:
    # Keep env access explicit so linters do not mark the imported password-env path
    # as mysterious when this script is used inside Docker Compose.
    os.environ
    tail_logs(parse_args())


if __name__ == "__main__":
    main()
