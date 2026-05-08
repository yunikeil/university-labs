from __future__ import annotations

import hashlib
import hmac
import time


VERSION = "v1"


def build_knock(secret: str, client_ip: str, domain: str, ttl: int) -> bytes:
    """Build a signed UDP knock packet for redirect proxy access."""
    expires_at = int(time.time()) + ttl
    domain = domain.lower().rstrip(".")
    payload = f"{VERSION}|{client_ip}|{domain}|{expires_at}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}|{signature}".encode("utf-8")


def parse_knock(secret: str, data: bytes) -> tuple[str, str, int, tuple[int, ...]] | None:
    """Return client_ip, domain, expires_at if packet signature is valid."""
    try:
        text = data.decode("utf-8")
        parts = text.split("|")
        if len(parts) == 5:
            version, client_ip, domain, expires_text, signature = parts
            ports_text = ""
        elif len(parts) == 6:
            version, client_ip, domain, expires_text, ports_text, signature = parts
        else:
            return None
        expires_at = int(expires_text)
        ports = parse_ports(ports_text)
    except (UnicodeDecodeError, ValueError):
        return None

    if version != VERSION or expires_at < int(time.time()):
        return None

    payload = f"{version}|{client_ip}|{domain}|{expires_at}|{ports_text}" if len(parts) == 6 else f"{version}|{client_ip}|{domain}|{expires_at}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    return client_ip, domain, expires_at, ports


def parse_ports(value: str) -> tuple[int, ...]:
    ports: list[int] = []

    for item in value.split(","):
        item = item.strip()
        if not item:
            continue

        port = int(item)
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid port: {port}")
        ports.append(port)

    return tuple(ports)
