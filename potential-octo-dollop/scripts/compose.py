from __future__ import annotations

import argparse
import os
import signal
import subprocess


COMPOSE_FILE = "docker-compose.yaml"


def parse_remote(value: str) -> tuple[str, str]:
    if "@" not in value:
        return "root", value

    user, host = value.split("@", 1)
    return user or "root", host


def run_compose(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    command = ["docker", "compose", "-f", COMPOSE_FILE]

    if args.local:
        command.extend(["--profile", "local"])
        env.setdefault("BLOCKED_IPV4", "127.0.0.1")
        env.setdefault("REDIRECT_AUTH_SECRET", "dev-secret-change-me")
        env.setdefault("REDIRECT_KNOCK_HOST", "redirect_proxy")
        env.setdefault("BROWSER_PROXY_TUNNEL_HOST", "redirect_proxy")
    else:
        user, host = parse_remote(args.remote)
        command.extend(["--profile", "remote"])
        env["REMOTE_REDIRECT_USER"] = user
        env["REMOTE_REDIRECT_HOST"] = host
        env["BLOCKED_IPV4"] = host
        env.setdefault("REDIRECT_AUTH_SECRET", "dev-secret-change-me")
        env["REDIRECT_KNOCK_HOST"] = host
        env["BROWSER_PROXY_REDIRECT_HOST"] = host
        env.setdefault("BROWSER_PROXY_TUNNEL_HOST", host)

        if args.ssh_key:
            env["REMOTE_REDIRECT_KEY"] = args.ssh_key

        if args.ssh_dir:
            env["REMOTE_REDIRECT_SSH_DIR"] = args.ssh_dir

    command.extend(args.compose_args)

    if not args.compose_args:
        command.extend(["up", "--build"])

    print(" ".join(command))
    process = subprocess.Popen(command, env=env)

    try:
        return process.wait()
    except KeyboardInterrupt:
        print()
        print("Stopping docker compose...")
        process.send_signal(signal.SIGINT)
        return process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run docker compose in local or remote redirect mode.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--local", action="store_true", help="Run redirect proxy locally in Docker.")
    mode.add_argument("--remote", help="Deploy redirect proxy to user@host and point DNS to host.")
    parser.add_argument("--ssh-key", help="SSH key path inside the deployer container.")
    parser.add_argument("--ssh-dir", help="Local .ssh directory to mount into the deployer container.")
    parser.add_argument("compose_args", nargs=argparse.REMAINDER, help="Arguments passed to docker compose.")
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run_compose(parse_args()))


if __name__ == "__main__":
    main()
