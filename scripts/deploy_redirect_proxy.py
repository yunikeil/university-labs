from __future__ import annotations

import argparse
import getpass
import os
import posixpath
import signal
import time
from pathlib import Path


DEFAULT_HOST = "193.200.74.60"
DEFAULT_USER = "root"
REMOTE_DIR = "/opt/dns-filter-redirect"
REMOTE_SCRIPT = posixpath.join(REMOTE_DIR, "redirect_proxy.py")
REMOTE_PAIR_TUNNEL = posixpath.join(REMOTE_DIR, "pair_tunnel.py")
SERVICE_NAME = "dns-filter-redirect-proxy.service"
SERVICE_PATH = f"/etc/systemd/system/{SERVICE_NAME}"
WATCHED_SUFFIXES = {".py", ".txt"}
IGNORED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def build_service_file(
    python_bin: str,
    upstream_dns_host: str,
    http_port: int,
    https_port: int,
    transparent_port: int,
    pair_port: int,
    ssh_port: int,
    auth_secret: str | None,
    knock_port: int,
    pair_secret: str | None,
    log_connections: bool,
    log_knocks: bool,
) -> str:
    auth_args = ""
    if auth_secret:
        auth_args = f" --auth-secret {auth_secret} --knock-port {knock_port}"

    log_args = ""
    if log_connections:
        log_args += " --log-connections"
    if log_knocks:
        log_args += " --log-knocks"

    pair_args = ""
    if pair_secret:
        pair_args = f" --pair-port {pair_port} --pair-secret {pair_secret}"

    iptables_rule = (
        "iptables -t nat {action} PREROUTING -p tcp "
        "-m addrtype --dst-type LOCAL "
        f"-m multiport ! --dports {ssh_port},{transparent_port},{pair_port} "
        f"-j REDIRECT --to-ports {transparent_port}"
    )
    delete_rule = iptables_rule.format(action="-D")
    add_rule = iptables_rule.format(action="-A")

    return f"""[Unit]
Description=DNS Filter Redirect Proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={REMOTE_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/sh -c '{delete_rule} 2>/dev/null || true'
ExecStartPre=/bin/sh -c '{add_rule}'
ExecStart={python_bin} -u {REMOTE_SCRIPT} --host 0.0.0.0 --http-port {http_port} --https-port {https_port} --transparent-port {transparent_port} --upstream-dns-host {upstream_dns_host}{auth_args}{pair_args}{log_args}
ExecStopPost=/bin/sh -c '{delete_rule} 2>/dev/null || true'
StandardOutput=journal
StandardError=journal
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
"""


def load_paramiko():
    try:
        import paramiko
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Paramiko is not installed. Run: python -m pip install -r requirements.txt"
        ) from exc

    return paramiko


def connect(args: argparse.Namespace):
    paramiko = load_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    password = None
    if args.password_env:
        password = os.environ.get(args.password_env)
        if not password:
            raise SystemExit(f"Environment variable {args.password_env} is empty or not set.")
    if args.password:
        password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")

    client.connect(
        hostname=args.host,
        port=args.port,
        username=args.user,
        key_filename=args.key,
        password=password,
        timeout=args.timeout,
        banner_timeout=args.timeout,
        auth_timeout=args.timeout,
    )
    return client


def run(client, command: str) -> str:
    print(f"remote$ {command}")
    stdin, stdout, stderr = client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")

    if output.strip():
        print(output.rstrip())
    if error.strip():
        print(error.rstrip())

    if exit_code != 0:
        raise RuntimeError(f"Remote command failed with exit code {exit_code}: {command}")

    return output


def upload_text(client, content: str, remote_path: str) -> None:
    sftp = client.open_sftp()
    try:
        with sftp.file(remote_path, "w") as remote_file:
            remote_file.write(content)
    finally:
        sftp.close()


def stop_remote_service(args: argparse.Namespace) -> None:
    client = connect(args)
    try:
        run(client, f"systemctl stop {SERVICE_NAME}")
    finally:
        client.close()


def deploy(args: argparse.Namespace) -> None:
    local_script = Path(__file__).resolve().parents[1] / "src" / "dns_filter" / "redirect_proxy.py"
    local_pair_tunnel = Path(__file__).resolve().parents[1] / "src" / "dns_filter" / "pair_tunnel.py"
    script_content = local_script.read_text(encoding="utf-8")
    pair_tunnel_content = local_pair_tunnel.read_text(encoding="utf-8")
    service_content = build_service_file(
        python_bin=args.python_bin,
        upstream_dns_host=args.upstream_dns_host,
        http_port=args.http_port,
        https_port=args.https_port,
        transparent_port=args.transparent_port,
        pair_port=args.pair_port,
        ssh_port=args.port,
        auth_secret=args.auth_secret,
        knock_port=args.knock_port,
        pair_secret=args.pair_secret or args.auth_secret,
        log_connections=args.log_connections,
        log_knocks=args.log_knocks,
    )

    client = connect(args)
    try:
        run(client, f"mkdir -p {REMOTE_DIR}")
        upload_text(client, script_content, REMOTE_SCRIPT)
        upload_text(client, pair_tunnel_content, REMOTE_PAIR_TUNNEL)
        run(client, f"chmod 0644 {REMOTE_SCRIPT}")
        run(client, f"chmod 0644 {REMOTE_PAIR_TUNNEL}")

        upload_text(client, service_content, SERVICE_PATH)
        run(client, "systemctl daemon-reload")
        run(client, f"systemctl enable {SERVICE_NAME}")
        run(client, f"systemctl restart {SERVICE_NAME}")
        run(client, f"systemctl --no-pager --full status {SERVICE_NAME}")
    finally:
        client.close()


def snapshot(root: Path) -> dict[Path, float]:
    files: dict[Path, float] = {}

    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in WATCHED_SUFFIXES:
            files[path] = path.stat().st_mtime

    return files


def watch_and_deploy(args: argparse.Namespace) -> None:
    root = Path(args.watch_root).resolve()
    stopped = False

    def stop(signum: int, frame: object) -> None:
        nonlocal stopped
        if stopped:
            raise SystemExit(128 + signum)

        stopped = True
        print(f"Stopping remote {SERVICE_NAME}...", flush=True)
        try:
            stop_remote_service(args)
        finally:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    last_snapshot = snapshot(root)
    deploy(args)
    print(f"Watching {root} for remote deploy changes.", flush=True)

    while True:
        time.sleep(args.watch_interval)
        current_snapshot = snapshot(root)

        if current_snapshot != last_snapshot:
            print("Change detected, redeploying remote redirect proxy...", flush=True)
            last_snapshot = current_snapshot
            deploy(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy redirect_proxy.py to a remote Linux server via SSH.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Remote server IP or hostname.")
    parser.add_argument("--user", default=DEFAULT_USER, help="SSH user.")
    parser.add_argument("--port", default=22, type=int, help="SSH port.")
    parser.add_argument("--key", default=None, help="Path to SSH private key.")
    parser.add_argument("--password", action="store_true", help="Ask for SSH password instead of key auth.")
    parser.add_argument("--password-env", default=None, help="Read SSH password from this environment variable.")
    parser.add_argument("--timeout", default=20.0, type=float, help="SSH connection timeout.")
    parser.add_argument("--python-bin", default="/usr/bin/python3", help="Remote Python executable.")
    parser.add_argument("--http-port", default=80, type=int, help="Remote HTTP listen port.")
    parser.add_argument("--https-port", default=443, type=int, help="Remote HTTPS listen port.")
    parser.add_argument("--transparent-port", default=10080, type=int, help="Remote internal transparent listen port.")
    parser.add_argument("--pair-port", default=9443, type=int, help="Remote custom proxy-pair tunnel listen port.")
    parser.add_argument("--upstream-dns-host", default="8.8.8.8", help="DNS used by redirect proxy to open real sites.")
    parser.add_argument("--auth-secret", default=None, help="Shared HMAC secret for DNS UDP knocks.")
    parser.add_argument("--knock-port", default=9091, type=int, help="Remote UDP knock listen port.")
    parser.add_argument("--pair-secret", default=None, help="Shared secret for custom proxy-pair tunnel.")
    parser.add_argument("--log-connections", action="store_true", help="Enable detailed redirect connection logs.")
    parser.add_argument("--log-knocks", action="store_true", help="Enable detailed DNS knock logs.")
    parser.add_argument("--watch", action="store_true", help="Watch local files, redeploy on changes, stop remote service on exit.")
    parser.add_argument("--watch-root", default=".", help="Directory to watch in --watch mode.")
    parser.add_argument("--watch-interval", default=1.0, type=float, help="Watch polling interval in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.watch:
        watch_and_deploy(args)
    else:
        deploy(args)


if __name__ == "__main__":
    main()
