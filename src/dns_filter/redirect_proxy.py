from __future__ import annotations

import argparse
import errno
import hashlib
import hmac
import random
import select
import socket
import socketserver
import struct
import threading
import time
from dataclasses import dataclass

try:
    from dns_filter.pair_tunnel import (
        FRAME_OK,
        accept_tunnel,
        build_error_frame,
        parse_open_frame,
        relay_pair,
    )
except ImportError:
    from pair_tunnel import FRAME_OK, accept_tunnel, build_error_frame, parse_open_frame, relay_pair


TYPE_A = 1
CLASS_IN = 1
BUFFER_SIZE = 256 * 1024
SOCKET_BUFFER_SIZE = 1024 * 1024
KNOCK_VERSION = "v1"
SO_ORIGINAL_DST = 80


class ProviderBlockDetected(Exception):
    """Raised after a provider-block hint was already printed."""


@dataclass(frozen=True)
class RedirectProxyConfig:
    """Настройки proxy, на который DNS перенаправляет заблокированные домены."""

    upstream_dns_host: str
    upstream_dns_port: int
    dns_timeout: float
    connect_timeout: float
    auth_required: bool
    allowed_clients: "AllowedClients"
    dns_cache: "DnsCache"
    log_connections: bool
    detect_provider_blocks: bool


@dataclass(frozen=True)
class RedirectFlowContext:
    """Connection context printed with provider-block hints."""

    host: str
    port: int
    upstream_host: str
    upstream_port: int
    client_ip: str
    client_port: int
    proxy_mode: str
    detect_provider_blocks: bool


class AllowedClients:
    """In-memory allowlist filled by signed UDP knocks from DNS."""

    def __init__(self) -> None:
        self.items: dict[str, int] = {}
        self.lock = threading.Lock()

    def allow(self, client_ip: str, expires_at: int) -> None:
        with self.lock:
            self.items[client_ip] = max(expires_at, self.items.get(client_ip, 0))

    def is_allowed(self, client_ip: str) -> bool:
        now = int(time.time())
        with self.lock:
            expires_at = self.items.get(client_ip)
            if not expires_at:
                return False

            if expires_at < now:
                self.items.pop(client_ip, None)
                return False

            return True


class DnsCache:
    """Small in-memory DNS cache for redirect hot path."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.items: dict[str, tuple[str, float]] = {}
        self.lock = threading.Lock()

    def get(self, host: str) -> str | None:
        if self.ttl <= 0:
            return None

        now = time.monotonic()
        with self.lock:
            cached = self.items.get(host)
            if not cached:
                return None

            ip_address, expires_at = cached
            if expires_at <= now:
                self.items.pop(host, None)
                return None

            return ip_address

    def set(self, host: str, ip_address: str) -> None:
        if self.ttl <= 0:
            return

        with self.lock:
            self.items[host] = (ip_address, time.monotonic() + self.ttl)


def parse_knock(secret: str, data: bytes) -> tuple[str, str, int, tuple[int, ...]] | None:
    """Return client_ip, domain, expires_at if UDP knock signature is valid."""
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
        ports = parse_port_list(ports_text)
    except (UnicodeDecodeError, ValueError):
        return None

    if version != KNOCK_VERSION or expires_at < int(time.time()):
        return None

    payload = f"{version}|{client_ip}|{domain}|{expires_at}|{ports_text}" if len(parts) == 6 else f"{version}|{client_ip}|{domain}|{expires_at}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    return client_ip, domain, expires_at, ports


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class RedirectProxyHandler(socketserver.BaseRequestHandler):
    """Обрабатывает одно TCP-подключение, пришедшее после DNS-подмены."""

    server: ThreadingTCPServer

    @property
    def config(self) -> RedirectProxyConfig:
        return self.server.config  # type: ignore[attr-defined]

    def handle(self) -> None:
        client_ip = self.client_address[0]
        proxy_mode = self.server.proxy_mode  # type: ignore[attr-defined]

        try:
            tune_tcp_socket(self.request)
            if self.config.auth_required and not self.config.allowed_clients.is_allowed(client_ip):
                print(f"DENY {client_ip}: no DNS knock", flush=True)
                return

            self.request.settimeout(self.config.connect_timeout)
            if proxy_mode == "http":
                first_chunk = self.request.recv(BUFFER_SIZE)
            elif proxy_mode == "tls":
                first_chunk = read_tls_record(self.request)
            else:
                first_chunk = read_auto_first_chunk(self.request)

            if not first_chunk:
                return

            if proxy_mode == "http":
                host, port = parse_http_destination(first_chunk, default_port=80)
            elif proxy_mode == "auto" and not first_chunk.startswith(b"\x16"):
                host, port = parse_http_destination(first_chunk, default_port=self.default_port())
            else:
                host, port = parse_tls_destination(first_chunk, default_port=self.default_port())

            upstream, target_label = self.connect_origin(host, port)
            tune_tcp_socket(upstream)
            upstream.settimeout(None)
            self.request.settimeout(None)

            if self.config.log_connections:
                print(f"REDIRECT {host}:{port} -> {target_label} route=direct", flush=True)
            flow_context = self.flow_context(host, port, upstream, proxy_mode)
            try:
                upstream.sendall(first_chunk)
            except OSError as exc:
                if log_tunnel_block_hint(flow_context, "send-initial", "client", exc):
                    raise ProviderBlockDetected(str(exc)) from exc
                raise
            tunnel(self.request, upstream, flow_context)
        except ProviderBlockDetected:
            return
        except (socket.timeout, TimeoutError) as exc:
            log_provider_block_hint(
                self.config,
                host="-",
                port=0,
                phase="client-read",
                reason="Timed out while waiting for first client bytes",
                confidence="low",
                target=f"{self.server.server_address[0]}:{self.server.server_address[1]}",  # type: ignore[index]
                client=f"{self.client_address[0]}:{self.client_address[1]}",
                exc=exc,
            )
        except Exception as exc:
            print(f"Redirect proxy error: {exc}", flush=True)

    def connect_origin(self, host: str, port: int) -> tuple[socket.socket, str]:
        return connect_origin_direct(self.config, host, port, f"{self.client_address[0]}:{self.client_address[1]}")

    def flow_context(self, host: str, port: int, upstream: socket.socket, proxy_mode: str) -> RedirectFlowContext:
        upstream_host, upstream_port = upstream.getpeername()[:2]
        return RedirectFlowContext(
            host=host,
            port=port,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            client_ip=self.client_address[0],
            client_port=self.client_address[1],
            proxy_mode=proxy_mode,
            detect_provider_blocks=self.config.detect_provider_blocks,
        )

    def default_port(self) -> int:
        if self.server.transparent:  # type: ignore[attr-defined]
            original = get_original_destination(self.request)
            if original:
                return original[1]

        return self.server.server_address[1]


class PairTunnelHandler(socketserver.BaseRequestHandler):
    """Custom encrypted proxy-pair endpoint used by the browser proxy."""

    server: ThreadingTCPServer

    @property
    def config(self) -> RedirectProxyConfig:
        return self.server.config  # type: ignore[attr-defined]

    @property
    def pair_secret(self) -> str:
        return self.server.pair_secret  # type: ignore[attr-defined]

    def handle(self) -> None:
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        upstream: socket.socket | None = None

        try:
            tune_tcp_socket(self.request)
            cipher = accept_tunnel(self.request, self.pair_secret, self.config.connect_timeout)
            self._cipher = cipher
            host, port, initial_data = parse_open_frame(cipher.recv_frame(self.request))
            upstream, target_label = connect_origin_direct(self.config, host, port, client)
            tune_tcp_socket(upstream)
            upstream.settimeout(None)
            self.request.settimeout(None)

            if self.config.log_connections:
                print(f"PAIR REDIRECT {host}:{port} -> {target_label} client={client}", flush=True)

            cipher.send_frame(self.request, FRAME_OK)
            if initial_data:
                upstream.sendall(initial_data)

            relay_pair(upstream, self.request, cipher)
        except ProviderBlockDetected as exc:
            self.send_tunnel_error(str(exc))
        except Exception as exc:
            self.send_tunnel_error(str(exc))
            print(f"Pair tunnel error: {exc}", flush=True)
        finally:
            if upstream:
                upstream.close()

    def send_tunnel_error(self, message: str) -> None:
        try:
            cipher = getattr(self, "_cipher")
            cipher.send_frame(self.request, build_error_frame(message))
        except Exception:
            pass


def connect_origin_direct(
    config: RedirectProxyConfig,
    host: str,
    port: int,
    client: str,
) -> tuple[socket.socket, str]:
    try:
        ip_address = resolve_a_record_cached(host, config)
        upstream = socket.create_connection((ip_address, port), timeout=config.connect_timeout)
        return upstream, f"{ip_address}:{port}"
    except ProviderBlockDetected:
        raise
    except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError) as exc:
        if isinstance(exc, (socket.timeout, TimeoutError)):
            reason = "TCP connect to origin timed out"
            confidence = "medium"
        elif isinstance(exc, ConnectionRefusedError):
            reason = "TCP connection refused by origin"
            confidence = "low"
        else:
            reason = "Direct origin route failed"
            confidence = "low"

        log_provider_block_hint(
            config,
            host=host,
            port=port,
            phase="connect",
            reason=reason,
            confidence=confidence,
            target="direct",
            client=client,
            exc=exc,
        )
        raise ProviderBlockDetected(str(exc)) from exc


def read_tls_record(client: socket.socket) -> bytes:
    """Reads one complete TLS record so SNI parsing sees the full ClientHello."""
    header = recv_exact(client, 5)
    if len(header) < 5:
        return header

    record_length = int.from_bytes(header[3:5], "big")
    if record_length <= 0 or record_length > BUFFER_SIZE:
        return header

    return header + recv_exact(client, record_length)


def read_auto_first_chunk(client: socket.socket) -> bytes:
    first_byte = client.recv(1, socket.MSG_PEEK)
    if first_byte == b"\x16":
        return read_tls_record(client)
    return client.recv(BUFFER_SIZE)


def get_original_destination(client: socket.socket) -> tuple[str, int] | None:
    """Returns original dst ip:port after iptables REDIRECT on Linux."""
    try:
        data = client.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    except OSError:
        return None

    if len(data) < 8:
        return None

    port = struct.unpack_from("!H", data, 2)[0]
    ip_address = socket.inet_ntoa(data[4:8])
    return ip_address, port


def recv_exact(client: socket.socket, size: int) -> bytes:
    data = bytearray()

    while len(data) < size:
        chunk = client.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)

    return bytes(data)


def parse_http_destination(data: bytes, default_port: int) -> tuple[str, int]:
    """Достаёт целевой домен из HTTP Host header."""
    header_bytes = data.split(b"\r\n\r\n", 1)[0]
    header_text = header_bytes.decode("iso-8859-1", errors="replace")

    for line in header_text.split("\r\n")[1:]:
        name, separator, value = line.partition(":")
        if separator and name.lower() == "host":
            return split_host_port(value.strip(), default_port)

    raise ValueError("HTTP request has no Host header")


def parse_tls_destination(data: bytes, default_port: int) -> tuple[str, int]:
    """Достаёт целевой домен из TLS SNI.

    Мы не расшифровываем HTTPS. SNI лежит в первом TLS ClientHello открытым
    текстом, и этого достаточно, чтобы понять, на какой реальный сервер идти.
    """
    hostname = parse_sni_hostname(data)
    if not hostname:
        raise ValueError("TLS ClientHello has no SNI hostname")

    return hostname, default_port


def parse_sni_hostname(data: bytes) -> str | None:
    """Минимальный парсер SNI из TLS ClientHello."""
    if len(data) < 5 or data[0] != 0x16:
        return None

    record_length = int.from_bytes(data[3:5], "big")
    if len(data) < 5 + record_length:
        return None

    offset = 5
    if data[offset] != 0x01:  # HandshakeType client_hello.
        return None

    offset += 4  # handshake type + 3-byte length
    offset += 2  # client version
    offset += 32  # random

    if offset + 1 > len(data):
        return None
    session_id_length = data[offset]
    offset += 1 + session_id_length

    if offset + 2 > len(data):
        return None
    cipher_suites_length = int.from_bytes(data[offset : offset + 2], "big")
    offset += 2 + cipher_suites_length

    if offset + 1 > len(data):
        return None
    compression_methods_length = data[offset]
    offset += 1 + compression_methods_length

    if offset + 2 > len(data):
        return None
    extensions_length = int.from_bytes(data[offset : offset + 2], "big")
    offset += 2
    extensions_end = offset + extensions_length

    while offset + 4 <= extensions_end and offset + 4 <= len(data):
        extension_type = int.from_bytes(data[offset : offset + 2], "big")
        extension_length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        offset += 4
        extension_end = offset + extension_length

        if extension_type == 0x0000:
            return parse_server_name_extension(data[offset:extension_end])

        offset = extension_end

    return None


def parse_server_name_extension(data: bytes) -> str | None:
    if len(data) < 2:
        return None

    offset = 2  # server_name_list length
    while offset + 3 <= len(data):
        name_type = data[offset]
        name_length = int.from_bytes(data[offset + 1 : offset + 3], "big")
        offset += 3

        if offset + name_length > len(data):
            return None

        if name_type == 0:
            return data[offset : offset + name_length].decode("idna")

        offset += name_length

    return None


def split_host_port(value: str, default_port: int) -> tuple[str, int]:
    """Разбирает host[:port]. Для IPv6 в квадратных скобках оставлена простая ветка."""
    value = value.strip()

    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        if rest.startswith(":") and rest[1:].isdigit():
            return host, int(rest[1:])
        return host, default_port

    host, separator, port_text = value.rpartition(":")
    if separator and port_text.isdigit():
        return host, int(port_text)

    return value, default_port


def resolve_a_record_cached(host: str, config: RedirectProxyConfig) -> str:
    cached = config.dns_cache.get(host)
    if cached:
        return cached

    try:
        ip_address = resolve_a_record(
            host,
            (config.upstream_dns_host, config.upstream_dns_port),
            config.dns_timeout,
        )
    except (socket.timeout, TimeoutError) as exc:
        log_provider_block_hint(
            config,
            host=host,
            port=53,
            phase="dns",
            reason="Upstream DNS request timed out",
            confidence="medium",
            target=f"{config.upstream_dns_host}:{config.upstream_dns_port}",
            client="-",
            exc=exc,
        )
        raise ProviderBlockDetected(str(exc)) from exc
    config.dns_cache.set(host, ip_address)
    return ip_address


def resolve_a_record(host: str, dns_address: tuple[str, int], timeout: float) -> str:
    """Резолвит настоящий IP через upstream DNS, минуя фильтрующий DNS."""
    packet = build_dns_query(host)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns_socket:
        dns_socket.settimeout(timeout)
        dns_socket.sendto(packet, dns_address)
        response, _ = dns_socket.recvfrom(4096)

    ip_address = parse_first_a_record(response)
    if not ip_address:
        raise ValueError(f"Upstream DNS returned no A record for {host}")

    return ip_address


def build_dns_query(host: str) -> bytes:
    transaction_id = random.randint(0, 65535)
    flags = 0x0100
    header = struct.pack("!HHHHHH", transaction_id, flags, 1, 0, 0, 0)

    question = bytearray()
    for label in host.rstrip(".").split("."):
        label_bytes = label.encode("idna")
        if len(label_bytes) > 63:
            raise ValueError(f"DNS label is too long: {label}")
        question.append(len(label_bytes))
        question.extend(label_bytes)

    question.extend(b"\x00")
    question.extend(struct.pack("!HH", TYPE_A, CLASS_IN))
    return header + bytes(question)


def parse_first_a_record(packet: bytes) -> str | None:
    if len(packet) < 12:
        return None

    _, _, question_count, answer_count, _, _ = struct.unpack("!HHHHHH", packet[:12])
    offset = 12

    for _ in range(question_count):
        offset = skip_dns_name(packet, offset)
        offset += 4

    for _ in range(answer_count):
        offset = skip_dns_name(packet, offset)
        if offset + 10 > len(packet):
            return None

        record_type, record_class, _, data_length = struct.unpack("!HHIH", packet[offset : offset + 10])
        offset += 10

        if offset + data_length > len(packet):
            return None

        record_data = packet[offset : offset + data_length]
        offset += data_length

        if record_type == TYPE_A and record_class == CLASS_IN and data_length == 4:
            return socket.inet_ntoa(record_data)

    return None


def skip_dns_name(packet: bytes, offset: int) -> int:
    while True:
        if offset >= len(packet):
            raise ValueError("DNS name is truncated")

        length = packet[offset]
        offset += 1

        if length == 0:
            return offset

        if length & 0b1100_0000:
            return offset + 1

        offset += length


def tunnel(client: socket.socket, upstream: socket.socket, context: RedirectFlowContext) -> None:
    sockets = [client, upstream]
    buffers = {
        client: bytearray(BUFFER_SIZE),
        upstream: bytearray(BUFFER_SIZE),
    }
    inspected_upstream = False

    try:
        while sockets:
            readable, _, _ = select.select(sockets, [], [], 30)
            if not readable:
                break

            for source in readable:
                target = upstream if source is client else client
                buffer = buffers[source]
                try:
                    size = source.recv_into(buffer)
                except OSError as exc:
                    if log_tunnel_block_hint(context, "recv", "upstream" if source is upstream else "client", exc):
                        raise ProviderBlockDetected(str(exc)) from exc
                    raise
                if not size:
                    return
                chunk = memoryview(buffer)[:size]
                if source is upstream and not inspected_upstream:
                    inspected_upstream = True
                    log_http_block_page_hint(context, chunk)

                try:
                    target.sendall(chunk)
                except OSError as exc:
                    if log_tunnel_block_hint(context, "send", "upstream" if source is upstream else "client", exc):
                        raise ProviderBlockDetected(str(exc)) from exc
                    raise
    finally:
        upstream.close()


def tune_tcp_socket(sock: socket.socket) -> None:
    options = (
        (socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_SIZE),
        (socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_BUFFER_SIZE),
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
    )

    for level, option, value in options:
        try:
            sock.setsockopt(level, option, value)
        except OSError:
            pass


def log_provider_block_hint(
    config: RedirectProxyConfig,
    *,
    host: str,
    port: int,
    phase: str,
    reason: str,
    confidence: str,
    target: str,
    client: str,
    exc: BaseException,
) -> None:
    if not config.detect_provider_blocks:
        return

    print(
        "PROVIDER-BLOCK? "
        f"proxy=redirect phase={phase} host={host}:{port} target={target} client={client} "
        f"confidence={confidence} reason={reason} error={exc!r}",
        flush=True,
    )


def log_tunnel_block_hint(context: RedirectFlowContext, operation: str, side: str, exc: OSError) -> bool:
    if not context.detect_provider_blocks:
        return False

    err_no = getattr(exc, "errno", None)
    if err_no not in {
        errno.ECONNRESET,
        errno.EPIPE,
        errno.ETIMEDOUT,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        10053,
        10054,
        10060,
        10065,
    }:
        return False

    confidence = "medium" if err_no in {errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH, 10060, 10065} else "low"
    print(
        "PROVIDER-BLOCK? "
        f"proxy=redirect phase=tunnel mode={context.proxy_mode} operation={operation} side={side} "
        f"host={context.host}:{context.port} target={context.upstream_host}:{context.upstream_port} "
        f"client={context.client_ip}:{context.client_port} confidence={confidence} error={exc!r}",
        flush=True,
    )
    return True


def log_http_block_page_hint(context: RedirectFlowContext, chunk: memoryview) -> None:
    if not context.detect_provider_blocks:
        return

    sample = bytes(chunk[:4096]).lower()
    markers = (
        b"blocked",
        b"access denied",
        b"forbidden",
        "заблок".encode("utf-8"),
        "доступ ограничен".encode("utf-8"),
        "роскомнадзор".encode("utf-8"),
    )
    if not sample.startswith(b"http/") or not any(marker in sample for marker in markers):
        return

    print(
        "PROVIDER-BLOCK? "
        f"proxy=redirect phase=http-response mode={context.proxy_mode} "
        f"host={context.host}:{context.port} target={context.upstream_host}:{context.upstream_port} "
        "confidence=high reason=origin returned a block-page-looking HTTP response",
        flush=True,
    )


def serve_knock_listener(
    host: str,
    port: int,
    secret: str,
    allowed_clients: AllowedClients,
    log_knocks: bool,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as knock_socket:
        knock_socket.bind((host, port))
        print(f"Knock listener on {host}:{port}", flush=True)

        while True:
            data, sender = knock_socket.recvfrom(2048)
            parsed = parse_knock(secret, data)
            if not parsed:
                print(f"Invalid knock from {sender[0]}", flush=True)
                continue

            client_ip, domain, expires_at, ports = parsed
            allowed_clients.allow(client_ip, expires_at)
            allowed_clients.allow(sender[0], expires_at)
            if log_knocks:
                print(f"ALLOW {client_ip} for {domain} until {expires_at}", flush=True)
                if sender[0] != client_ip:
                    print(f"ALLOW {sender[0]} for {domain} via knock sender until {expires_at}", flush=True)


def serve_port(
    host: str,
    port: int,
    proxy_mode: str,
    config: RedirectProxyConfig,
    transparent: bool = False,
) -> None:
    with ThreadingTCPServer((host, port), RedirectProxyHandler) as server:
        server.config = config  # type: ignore[attr-defined]
        server.proxy_mode = proxy_mode  # type: ignore[attr-defined]
        server.transparent = transparent  # type: ignore[attr-defined]
        print(f"Redirect proxy listening on {host}:{port} ({proxy_mode})", flush=True)
        server.serve_forever()


def serve_pair_tunnel_port(
    host: str,
    port: int,
    pair_secret: str,
    config: RedirectProxyConfig,
) -> None:
    with ThreadingTCPServer((host, port), PairTunnelHandler) as server:
        server.config = config  # type: ignore[attr-defined]
        server.pair_secret = pair_secret  # type: ignore[attr-defined]
        print(f"Pair tunnel listening on {host}:{port}", flush=True)
        server.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DNS redirect proxy for HTTP and HTTPS.")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on.")
    parser.add_argument("--http-port", default=80, type=int, help="HTTP listen port.")
    parser.add_argument("--https-port", default=443, type=int, help="HTTPS listen port.")
    parser.add_argument("--transparent-port", default=10080, type=int, help="Internal TCP port used by iptables REDIRECT.")
    parser.add_argument("--upstream-dns-host", default="8.8.8.8", help="DNS used to open real sites.")
    parser.add_argument("--upstream-dns-port", default=53, type=int, help="Upstream DNS port.")
    parser.add_argument("--dns-timeout", default=2.0, type=float, help="DNS timeout in seconds.")
    parser.add_argument("--dns-cache-ttl", default=60.0, type=float, help="Redirect proxy DNS cache TTL in seconds.")
    parser.add_argument("--connect-timeout", default=5.0, type=float, help="Origin connect timeout.")
    parser.add_argument("--auth-secret", default=None, help="Require signed UDP knocks with this shared secret.")
    parser.add_argument("--knock-host", default="0.0.0.0", help="UDP knock listen address.")
    parser.add_argument("--knock-port", default=9091, type=int, help="UDP knock listen port.")
    parser.add_argument("--pair-port", default=9443, type=int, help="Custom proxy-pair tunnel listen port.")
    parser.add_argument("--pair-secret", default=None, help="Shared secret for custom proxy-pair tunnel.")
    parser.add_argument("--log-connections", action="store_true", help="Print every redirected TCP connection.")
    parser.add_argument("--log-knocks", action="store_true", help="Print every accepted DNS knock.")
    parser.add_argument(
        "--no-provider-block-detect",
        dest="detect_provider_blocks",
        action="store_false",
        help="Disable provider-block detection hints.",
    )
    parser.set_defaults(detect_provider_blocks=True)
    return parser.parse_args()


def parse_port_list(value: str) -> tuple[int, ...]:
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


def main() -> None:
    args = parse_args()
    allowed_clients = AllowedClients()
    config = RedirectProxyConfig(
        upstream_dns_host=args.upstream_dns_host,
        upstream_dns_port=args.upstream_dns_port,
        dns_timeout=args.dns_timeout,
        connect_timeout=args.connect_timeout,
        auth_required=bool(args.auth_secret),
        allowed_clients=allowed_clients,
        dns_cache=DnsCache(args.dns_cache_ttl),
        log_connections=args.log_connections,
        detect_provider_blocks=args.detect_provider_blocks,
    )
    threads = [
        threading.Thread(target=serve_port, args=(args.host, args.http_port, "http", config)),
        threading.Thread(target=serve_port, args=(args.host, args.https_port, "tls", config)),
        threading.Thread(target=serve_port, args=(args.host, args.transparent_port, "auto", config, True)),
    ]
    pair_secret = args.pair_secret or args.auth_secret
    if pair_secret:
        threads.append(threading.Thread(target=serve_pair_tunnel_port, args=(args.host, args.pair_port, pair_secret, config)))

    if args.auth_secret:
        threads.append(
            threading.Thread(
                target=serve_knock_listener,
                args=(args.knock_host, args.knock_port, args.auth_secret, allowed_clients, args.log_knocks),
            )
        )

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()


if __name__ == "__main__":
    print("Hello there!")
    main()
