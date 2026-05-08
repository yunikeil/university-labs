from __future__ import annotations

import argparse
import errno
import random
import select
import socket
import socketserver
import struct
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from dns_filter.pair_tunnel import build_open_frame, open_tunnel, parse_response_frame, relay_pair


TYPE_A = 1
CLASS_IN = 1
BUFFER_SIZE = 256 * 1024
SOCKET_BUFFER_SIZE = 1024 * 1024
FATAL_STOP_LOCK = threading.Lock()
FATAL_STOP_REQUESTED = False


class ProviderBlockDetected(Exception):
    """Raised after a provider-block hint was already printed."""


@dataclass(frozen=True)
class ProxyConfig:
    """Настройки proxy, общие для всех клиентских подключений."""

    dns_host: str
    dns_port: int
    dns_timeout: float
    connect_timeout: float
    redirect_ip: str | None
    redirect_host: str | None
    dns_cache: "DnsCache"
    provider_block_cache: "ProviderBlockCache"
    log_connections: bool
    detect_provider_blocks: bool
    tunnel_host: str | None
    tunnel_port: int
    tunnel_secret: str | None


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """TCP-сервер, который обрабатывает каждое подключение в отдельном потоке."""

    allow_reuse_address = True
    daemon_threads = True


class DnsCache:
    """Tiny TTL cache for the debug browser proxy DNS lookups."""

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


class ProviderBlockCache:
    """TTL cache for redirect destinations that already failed on the plain route."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.items: dict[tuple[str, int], float] = {}
        self.lock = threading.Lock()

    def is_blocked(self, host: str, port: int) -> bool:
        if self.ttl <= 0:
            return False

        key = (host.lower().rstrip("."), port)
        now = time.monotonic()
        with self.lock:
            expires_at = self.items.get(key)
            if not expires_at:
                return False
            if expires_at <= now:
                self.items.pop(key, None)
                return False
            return True

    def mark_blocked(self, host: str, port: int) -> None:
        if self.ttl <= 0:
            return

        key = (host.lower().rstrip("."), port)
        with self.lock:
            self.items[key] = time.monotonic() + self.ttl


class ProxyConnectRefused(ConnectionRefusedError):
    """Connection refused with enough context to debug DNS redirect routing."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        dns_host: str,
        dns_port: int,
        dns_answer: str,
        connect_host: str,
        connect_port: int,
        redirect_ip: str | None,
        redirect_host: str | None,
        timeout: float,
        original: ConnectionRefusedError,
    ) -> None:
        super().__init__(str(original))
        self.host = host
        self.port = port
        self.dns_host = dns_host
        self.dns_port = dns_port
        self.dns_answer = dns_answer
        self.connect_host = connect_host
        self.connect_port = connect_port
        self.redirect_ip = redirect_ip
        self.redirect_host = redirect_host
        self.timeout = timeout
        self.original = original


@dataclass(frozen=True)
class ProxyFlowContext:
    """Human-readable connection context for block-detection logs."""

    host: str
    port: int
    upstream_host: str
    upstream_port: int
    client_ip: str
    client_port: int
    detect_provider_blocks: bool


@dataclass(frozen=True)
class ProxyRoute:
    """DNS decision used by browser proxy before direct or tunnel routing."""

    dns_answer: str
    connect_host: str
    connect_port: int
    is_redirect: bool


class ProxyHandler(socketserver.BaseRequestHandler):
    """Один клиент браузера, подключившийся к proxy."""

    server: ThreadingTCPServer

    @property
    def config(self) -> ProxyConfig:
        return self.server.config  # type: ignore[attr-defined]

    def handle(self) -> None:
        try:
            tune_tcp_socket(self.request)
            first_chunk = read_until_headers_end(self.request)
            if not first_chunk:
                return

            request_line, headers = parse_http_headers(first_chunk)
            method, target, version = request_line.split(" ", 2)

            if method.upper() == "CONNECT":
                self.handle_connect(target, version)
            else:
                self.handle_http(method, target, version, headers, first_chunk)
        except ProxyConnectRefused as exc:
            if request_fatal_stop():
                log_connection_refused(exc, self.client_address)
                send_http_error(self.request, 502, "Bad Gateway")
                stop_server(self.server)
        except ProviderBlockDetected:
            send_http_error(self.request, 502, "Bad Gateway")
        except (socket.timeout, TimeoutError) as exc:
            log_provider_block_hint(
                self.config,
                host="-",
                port=0,
                phase="client-read",
                reason="Timed out while waiting for browser request headers",
                confidence="low",
                target=f"{self.server.server_address[0]}:{self.server.server_address[1]}",  # type: ignore[index]
                exc=exc,
            )
            send_http_error(self.request, 502, "Bad Gateway")
        except Exception as exc:
            print(f"Proxy error: {exc}")
            send_http_error(self.request, 502, "Bad Gateway")

    def handle_connect(self, target: str, version: str) -> None:
        """Обрабатывает HTTPS через CONNECT без расшифровки трафика."""
        host, port = split_host_port(target, default_port=443)
        route = resolve_proxy_route(host, port, self.config)
        if should_start_with_pair_tunnel(host, port, route, self.config):
            tunnel_sock, cipher = connect_via_pair_tunnel(host, port, b"", self.config)
            if self.config.log_connections:
                print(
                    f"PAIR CONNECT provider-block-cache {host}:{port} dns={route.dns_answer} -> {self.config.tunnel_host}:{self.config.tunnel_port}",
                    flush=True,
                )
            self.request.sendall(f"{version} 200 Connection Established\r\n\r\n".encode("ascii"))
            relay_pair(self.request, tunnel_sock, cipher)
            return

        try:
            upstream = connect_to_route(host, port, route, self.config)
        except (ProviderBlockDetected, ProxyConnectRefused) as exc:
            if can_fallback_to_pair_tunnel(route, self.config):
                mark_provider_block(host, port, self.config, f"plain connect failed: {exc}")
                tunnel_sock, cipher = connect_via_pair_tunnel(host, port, b"", self.config)
                if self.config.log_connections:
                    print(f"PAIR CONNECT fallback {host}:{port} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
                self.request.sendall(f"{version} 200 Connection Established\r\n\r\n".encode("ascii"))
                relay_pair(self.request, tunnel_sock, cipher)
                return
            raise

        upstream_host, upstream_port = upstream.getpeername()[:2]
        if self.config.log_connections:
            route_label = "plain-redirect" if route.is_redirect else "direct"
            print(f"CONNECT {route_label} {host}:{port} -> {upstream_host}:{upstream_port}")
        self.request.sendall(f"{version} 200 Connection Established\r\n\r\n".encode("ascii"))
        if can_fallback_to_pair_tunnel(route, self.config):
            self.relay_connect_plain_with_fallback(host, port, upstream)
            return

        tunnel(self.request, upstream, self.flow_context(host, port, upstream))

    def relay_connect_plain_with_fallback(self, host: str, port: int, upstream: socket.socket) -> None:
        """Relay CONNECT through plain redirect; fallback if initial ClientHello is blocked."""
        self.request.settimeout(self.config.connect_timeout)
        try:
            initial_data = self.request.recv(BUFFER_SIZE)
        except (socket.timeout, TimeoutError):
            initial_data = b""
        finally:
            self.request.settimeout(None)

        if not initial_data:
            tunnel(self.request, upstream, self.flow_context(host, port, upstream))
            return

        try:
            upstream.sendall(initial_data)
        except OSError as exc:
            upstream.close()
            mark_provider_block(host, port, self.config, f"plain initial send failed: {exc}")
            tunnel_sock, cipher = connect_via_pair_tunnel(host, port, initial_data, self.config)
            if self.config.log_connections:
                print(f"PAIR CONNECT fallback-after-send {host}:{port} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
            relay_pair(self.request, tunnel_sock, cipher)
            return

        try:
            upstream.settimeout(self.config.connect_timeout)
            first_response = upstream.recv(BUFFER_SIZE)
        except (socket.timeout, TimeoutError) as exc:
            upstream.close()
            mark_provider_block(host, port, self.config, f"plain route had no first response: {exc}")
            tunnel_sock, cipher = connect_via_pair_tunnel(host, port, initial_data, self.config)
            if self.config.log_connections:
                print(f"PAIR CONNECT fallback-after-timeout {host}:{port} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
            relay_pair(self.request, tunnel_sock, cipher)
            return
        except OSError as exc:
            upstream.close()
            mark_provider_block(host, port, self.config, f"plain first response failed: {exc}")
            tunnel_sock, cipher = connect_via_pair_tunnel(host, port, initial_data, self.config)
            if self.config.log_connections:
                print(f"PAIR CONNECT fallback-after-reset {host}:{port} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
            relay_pair(self.request, tunnel_sock, cipher)
            return
        finally:
            try:
                upstream.settimeout(None)
            except OSError:
                pass

        if not first_response:
            upstream.close()
            mark_provider_block(host, port, self.config, "plain route closed before first response")
            tunnel_sock, cipher = connect_via_pair_tunnel(host, port, initial_data, self.config)
            if self.config.log_connections:
                print(f"PAIR CONNECT fallback-after-close {host}:{port} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
            relay_pair(self.request, tunnel_sock, cipher)
            return

        self.request.sendall(first_response)
        try:
            tunnel(self.request, upstream, self.flow_context(host, port, upstream))
        except ProviderBlockDetected:
            mark_provider_block(host, port, self.config, "plain tunnel later failed")
            raise

    def handle_http(
        self,
        method: str,
        target: str,
        version: str,
        headers: list[str],
        first_chunk: bytes,
    ) -> None:
        """Обрабатывает обычный HTTP-запрос из браузера."""
        parsed = urlsplit(target)
        if parsed.scheme and parsed.netloc:
            host, port = split_host_port(parsed.netloc, default_port=80)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
        else:
            host_header = get_header(headers, "host")
            if not host_header:
                raise ValueError("HTTP request has no Host header")
            host, port = split_host_port(host_header, default_port=80)
            path = target

        rewritten = rewrite_http_request(first_chunk, f"{method} {path} {version}")

        route = resolve_proxy_route(host, port, self.config)
        if should_start_with_pair_tunnel(host, port, route, self.config):
            tunnel_sock, cipher = connect_via_pair_tunnel(host, port, rewritten, self.config)
            if self.config.log_connections:
                print(
                    f"PAIR {method.upper()} provider-block-cache {host}:{port}{path} dns={route.dns_answer} -> {self.config.tunnel_host}:{self.config.tunnel_port}",
                    flush=True,
                )
            relay_pair(self.request, tunnel_sock, cipher)
            return

        try:
            upstream = connect_to_route(host, port, route, self.config)
        except (ProviderBlockDetected, ProxyConnectRefused) as exc:
            if can_fallback_to_pair_tunnel(route, self.config):
                mark_provider_block(host, port, self.config, f"plain connect failed: {exc}")
                tunnel_sock, cipher = connect_via_pair_tunnel(host, port, rewritten, self.config)
                if self.config.log_connections:
                    print(f"PAIR {method.upper()} fallback {host}:{port}{path} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
                relay_pair(self.request, tunnel_sock, cipher)
                return
            raise

        upstream_host, upstream_port = upstream.getpeername()[:2]
        if self.config.log_connections:
            route_label = "plain-redirect" if route.is_redirect else "direct"
            print(f"{method.upper()} {route_label} {host}:{port}{path} -> {upstream_host}:{upstream_port}")
        try:
            upstream.sendall(rewritten)
        except OSError as exc:
            upstream.close()
            if can_fallback_to_pair_tunnel(route, self.config):
                mark_provider_block(host, port, self.config, f"plain initial send failed: {exc}")
                tunnel_sock, cipher = connect_via_pair_tunnel(host, port, rewritten, self.config)
                if self.config.log_connections:
                    print(f"PAIR {method.upper()} fallback-after-send {host}:{port}{path} -> {self.config.tunnel_host}:{self.config.tunnel_port}", flush=True)
                relay_pair(self.request, tunnel_sock, cipher)
                return
            raise

        try:
            tunnel(self.request, upstream, self.flow_context(host, port, upstream))
        except ProviderBlockDetected:
            if can_fallback_to_pair_tunnel(route, self.config):
                mark_provider_block(host, port, self.config, "plain tunnel later failed")
            raise

    def flow_context(self, host: str, port: int, upstream: socket.socket) -> ProxyFlowContext:
        upstream_host, upstream_port = upstream.getpeername()[:2]
        return ProxyFlowContext(
            host=host,
            port=port,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            client_ip=self.client_address[0],
            client_port=self.client_address[1],
            detect_provider_blocks=self.config.detect_provider_blocks,
        )


def read_until_headers_end(client: socket.socket) -> bytes:
    """Читает первый HTTP-запрос до конца заголовков."""
    data = bytearray()

    while b"\r\n\r\n" not in data and len(data) <= BUFFER_SIZE:
        chunk = client.recv(4096)
        if not chunk:
            break
        data.extend(chunk)

    return bytes(data)


def parse_http_headers(data: bytes) -> tuple[str, list[str]]:
    """Возвращает request line и список заголовков."""
    header_bytes = data.split(b"\r\n\r\n", 1)[0]
    header_text = header_bytes.decode("iso-8859-1")
    lines = header_text.split("\r\n")

    if not lines or len(lines[0].split(" ", 2)) != 3:
        raise ValueError("Invalid HTTP request line")

    return lines[0], lines[1:]


def rewrite_http_request(data: bytes, request_line: str) -> bytes:
    """Меняет только первую строку HTTP-запроса, оставляя заголовки и тело как есть."""
    _, rest = data.split(b"\r\n", 1)
    return request_line.encode("iso-8859-1") + b"\r\n" + rest


def get_header(headers: list[str], name: str) -> str | None:
    prefix = f"{name.lower()}:"
    for header in headers:
        if header.lower().startswith(prefix):
            return header.split(":", 1)[1].strip()
    return None


def split_host_port(value: str, default_port: int) -> tuple[str, int]:
    """Разбирает host[:port]. Для простоты IPv6 в квадратных скобках не поддержан."""
    host, separator, port_text = value.rpartition(":")
    if separator and port_text.isdigit():
        return host, int(port_text)
    return value, default_port


def connect_via_pair_tunnel(host: str, port: int, initial_data: bytes, config: ProxyConfig):
    """Opens target through our custom encrypted proxy-pair tunnel."""
    if not config.tunnel_host or not config.tunnel_secret:
        raise ValueError("Pair tunnel is not configured")

    try:
        tunnel_sock, cipher = open_tunnel(
            config.tunnel_host,
            config.tunnel_port,
            config.tunnel_secret,
            config.connect_timeout,
        )
        tune_tcp_socket(tunnel_sock)
        cipher.send_frame(tunnel_sock, build_open_frame(host, port, initial_data))
        parse_response_frame(cipher.recv_frame(tunnel_sock))
        tunnel_sock.settimeout(None)
        return tunnel_sock, cipher
    except (socket.timeout, TimeoutError, OSError) as exc:
        log_provider_block_hint(
            config,
            host=host,
            port=port,
            phase="pair-tunnel",
            reason="Custom proxy-pair tunnel failed",
            confidence="medium",
            target=f"{config.tunnel_host}:{config.tunnel_port}",
            exc=exc,
        )
        raise ProviderBlockDetected(str(exc)) from exc


def resolve_proxy_route(host: str, port: int, config: ProxyConfig) -> ProxyRoute:
    """Ask filtering DNS first; redirect answer means plain redirect proxy route."""
    ip_address = resolve_a_record_cached(host, config)
    is_redirect = bool(config.redirect_ip and ip_address == config.redirect_ip)
    connect_host = config.redirect_host if is_redirect and config.redirect_host else ip_address
    return ProxyRoute(
        dns_answer=ip_address,
        connect_host=connect_host,
        connect_port=port,
        is_redirect=is_redirect,
    )


def can_fallback_to_pair_tunnel(route: ProxyRoute, config: ProxyConfig) -> bool:
    return bool(route.is_redirect and config.tunnel_host and config.tunnel_secret)


def should_start_with_pair_tunnel(host: str, port: int, route: ProxyRoute, config: ProxyConfig) -> bool:
    return can_fallback_to_pair_tunnel(route, config) and config.provider_block_cache.is_blocked(host, port)


def mark_provider_block(host: str, port: int, config: ProxyConfig, reason: str) -> None:
    config.provider_block_cache.mark_blocked(host, port)
    if config.log_connections:
        print(f"PAIR CACHE {host}:{port} reason={reason}", flush=True)


def connect_to_route(host: str, port: int, route: ProxyRoute, config: ProxyConfig) -> socket.socket:
    try:
        upstream = socket.create_connection((route.connect_host, route.connect_port), timeout=config.connect_timeout)
        tune_tcp_socket(upstream)
    except (socket.timeout, TimeoutError) as exc:
        log_provider_block_hint(
            config,
            host=host,
            port=port,
            phase="connect",
            reason="TCP connect timed out",
            confidence="medium",
            target=f"{route.connect_host}:{route.connect_port}",
            exc=exc,
        )
        raise ProviderBlockDetected(str(exc)) from exc
    except ConnectionRefusedError as exc:
        log_provider_block_hint(
            config,
            host=host,
            port=port,
            phase="connect",
            reason="TCP connection refused; usually no listener, but useful for provider/firewall debugging",
            confidence="low",
            target=f"{route.connect_host}:{route.connect_port}",
            exc=exc,
        )
        raise ProxyConnectRefused(
            host=host,
            port=port,
            dns_host=config.dns_host,
            dns_port=config.dns_port,
            dns_answer=route.dns_answer,
            connect_host=route.connect_host,
            connect_port=route.connect_port,
            redirect_ip=config.redirect_ip,
            redirect_host=config.redirect_host,
            timeout=config.connect_timeout,
            original=exc,
        ) from exc

    upstream.settimeout(None)
    return upstream


def connect_via_dns(host: str, port: int, config: ProxyConfig) -> socket.socket:
    """Резолвит домен через указанный DNS и подключается к полученному IP."""
    route = resolve_proxy_route(host, port, config)
    return connect_to_route(host, port, route, config)


def resolve_a_record_cached(host: str, config: ProxyConfig) -> str:
    cached = config.dns_cache.get(host)
    if cached:
        return cached

    try:
        ip_address = resolve_a_record(host, (config.dns_host, config.dns_port), config.dns_timeout)
    except (socket.timeout, TimeoutError) as exc:
        log_provider_block_hint(
            config,
            host=host,
            port=53,
            phase="dns",
            reason="DNS request timed out",
            confidence="medium",
            target=f"{config.dns_host}:{config.dns_port}",
            exc=exc,
        )
        raise ProviderBlockDetected(str(exc)) from exc
    config.dns_cache.set(host, ip_address)
    return ip_address


def resolve_a_record(host: str, dns_address: tuple[str, int], timeout: float) -> str:
    """Отправляет DNS A-запрос на локальный DNS-сервер."""
    packet = build_dns_query(host)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns_socket:
        dns_socket.settimeout(timeout)
        dns_socket.sendto(packet, dns_address)
        response, _ = dns_socket.recvfrom(4096)

    ip_address = parse_first_a_record(response)
    if not ip_address:
        raise ValueError(f"DNS returned no A record for {host}")

    return ip_address


def build_dns_query(host: str) -> bytes:
    """Собирает минимальный DNS-запрос типа A."""
    transaction_id = random.randint(0, 65535)
    flags = 0x0100  # Recursion Desired.
    header = struct.pack("!HHHHHH", transaction_id, flags, 1, 0, 0, 0)

    question = bytearray()
    for label in host.rstrip(".").split("."):
        label_bytes = label.encode("ascii")
        if len(label_bytes) > 63:
            raise ValueError(f"DNS label is too long: {label}")
        question.append(len(label_bytes))
        question.extend(label_bytes)

    question.extend(b"\x00")
    question.extend(struct.pack("!HH", TYPE_A, CLASS_IN))
    return header + bytes(question)


def parse_first_a_record(packet: bytes) -> str | None:
    """Достаёт первый IPv4-адрес из DNS-ответа."""
    if len(packet) < 12:
        return None

    _, _, question_count, answer_count, _, _ = struct.unpack("!HHHHHH", packet[:12])
    offset = 12

    for _ in range(question_count):
        offset = skip_dns_name(packet, offset)
        offset += 4  # type + class

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
    """Пропускает DNS-имя, включая сжатые указатели вида c0 0c."""
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


def tunnel(client: socket.socket, upstream: socket.socket, context: ProxyFlowContext) -> None:
    """Прокидывает байты между браузером и удалённым сервером в обе стороны."""
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


def send_http_error(client: socket.socket, status: int, reason: str) -> None:
    body = f"{status} {reason}\n".encode("utf-8")
    response = (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii") + body

    try:
        client.sendall(response)
    except OSError:
        pass


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
    config: ProxyConfig,
    *,
    host: str,
    port: int,
    phase: str,
    reason: str,
    confidence: str,
    target: str,
    exc: BaseException,
) -> None:
    if not config.detect_provider_blocks:
        return

    print(
        "PROVIDER-BLOCK? "
        f"proxy=browser phase={phase} host={host}:{port} target={target} "
        f"confidence={confidence} reason={reason} error={exc!r}",
        flush=True,
    )


def log_tunnel_block_hint(context: ProxyFlowContext, operation: str, side: str, exc: OSError) -> bool:
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
        f"proxy=browser phase=tunnel operation={operation} side={side} "
        f"host={context.host}:{context.port} target={context.upstream_host}:{context.upstream_port} "
        f"client={context.client_ip}:{context.client_port} confidence={confidence} error={exc!r}",
        flush=True,
    )
    return True


def log_http_block_page_hint(context: ProxyFlowContext, chunk: memoryview) -> None:
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
        f"proxy=browser phase=http-response host={context.host}:{context.port} "
        f"target={context.upstream_host}:{context.upstream_port} confidence=high "
        "reason=upstream returned a block-page-looking HTTP response",
        flush=True,
    )


def log_connection_refused(exc: ProxyConnectRefused, client_address: tuple[str, int]) -> None:
    print("", flush=True)
    print("FATAL: browser proxy got ConnectionRefusedError and will stop now.", flush=True)
    print(f"  browser client: {client_address[0]}:{client_address[1]}", flush=True)
    print(f"  requested host: {exc.host}:{exc.port}", flush=True)
    print(f"  DNS server: {exc.dns_host}:{exc.dns_port}", flush=True)
    print(f"  DNS A answer: {exc.dns_answer}", flush=True)
    print(f"  actual TCP target: {exc.connect_host}:{exc.connect_port}", flush=True)
    print(f"  redirect_ip match value: {exc.redirect_ip}", flush=True)
    print(f"  redirect_host replacement: {exc.redirect_host}", flush=True)
    print(f"  connect timeout: {exc.timeout}s", flush=True)
    print(f"  original error: {exc.original}", flush=True)
    print(
        "  hint: target host is reachable by DNS, but no TCP listener accepted this port.",
        flush=True,
    )


def request_fatal_stop() -> bool:
    global FATAL_STOP_REQUESTED

    with FATAL_STOP_LOCK:
        if FATAL_STOP_REQUESTED:
            return False

        FATAL_STOP_REQUESTED = True
        return True


def stop_server(server: ThreadingTCPServer) -> None:
    print("Stopping browser proxy after fatal connection refusal.", flush=True)
    threading.Thread(target=server.shutdown, daemon=True).start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a browser proxy that resolves hosts via local DNS.")
    parser.add_argument("--host", default="127.0.0.1", help="Proxy listen address.")
    parser.add_argument("--port", default=8080, type=int, help="Proxy listen port.")
    parser.add_argument("--dns-host", default="127.0.0.1", help="DNS server address.")
    parser.add_argument("--dns-port", default=5353, type=int, help="DNS server port.")
    parser.add_argument("--dns-timeout", default=2.0, type=float, help="DNS timeout in seconds.")
    parser.add_argument("--dns-cache-ttl", default=30.0, type=float, help="Browser proxy DNS cache TTL in seconds.")
    parser.add_argument(
        "--provider-block-cache-ttl",
        default=300.0,
        type=float,
        help="Seconds to remember redirect domains that need pair tunnel after plain route failures.",
    )
    parser.add_argument("--connect-timeout", default=5.0, type=float, help="Upstream connect timeout.")
    parser.add_argument("--redirect-ip", default=None, help="DNS answer that should be routed to redirect host.")
    parser.add_argument("--redirect-host", default=None, help="Host used instead of redirect-ip from inside proxy.")
    parser.add_argument("--tunnel-host", default=None, help="Custom proxy-pair tunnel host. When set, DNS resolving is skipped.")
    parser.add_argument("--tunnel-port", default=9443, type=int, help="Custom proxy-pair tunnel port.")
    parser.add_argument("--tunnel-secret", default=None, help="Shared secret for custom proxy-pair tunnel.")
    parser.add_argument("--log-connections", action="store_true", help="Print every proxied browser connection.")
    parser.add_argument(
        "--no-provider-block-detect",
        dest="detect_provider_blocks",
        action="store_false",
        help="Disable provider-block detection hints.",
    )
    parser.set_defaults(detect_provider_blocks=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    address = (args.host, args.port)
    config = ProxyConfig(
        dns_host=args.dns_host,
        dns_port=args.dns_port,
        dns_timeout=args.dns_timeout,
        connect_timeout=args.connect_timeout,
        redirect_ip=args.redirect_ip,
        redirect_host=args.redirect_host,
        dns_cache=DnsCache(args.dns_cache_ttl),
        provider_block_cache=ProviderBlockCache(args.provider_block_cache_ttl),
        log_connections=args.log_connections,
        detect_provider_blocks=args.detect_provider_blocks,
        tunnel_host=args.tunnel_host or None,
        tunnel_port=args.tunnel_port,
        tunnel_secret=args.tunnel_secret,
    )

    with ThreadingTCPServer(address, ProxyHandler) as server:
        server.config = config  # type: ignore[attr-defined]
        print(f"Browser proxy listening on {args.host}:{args.port}")
        if config.tunnel_host and config.tunnel_secret:
            print(f"Using custom proxy-pair tunnel only after provider-block detection: {config.tunnel_host}:{config.tunnel_port}")
        else:
            print(f"Resolving hosts through DNS {args.dns_host}:{args.dns_port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
