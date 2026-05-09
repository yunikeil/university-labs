from __future__ import annotations

import argparse
import ipaddress
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from dns_filter.knock import build_knock


# DNS-типы записей, которые нам нужны:
# A    -> IPv4-адрес
# AAAA -> IPv6-адрес
TYPE_A = 1
TYPE_AAAA = 28

# IN означает обычный интернет-класс DNS-записи.
CLASS_IN = 1

# Коды ошибок DNS, которые возвращаем для некорректных или неподдержанных запросов.
RCODE_FORMAT_ERROR = 1
RCODE_NOT_IMPLEMENTED = 4


@dataclass(frozen=True)
class DnsQuestion:
    """Один вопрос из DNS-запроса."""

    name: str
    qtype: int
    qclass: int
    end_offset: int


class KnockSender:
    """Sends signed knocks with a tiny per-client rate limit."""

    def __init__(
        self,
        address: tuple[str, int] | None,
        secret: str | None,
        ttl: int,
        min_interval: float,
    ) -> None:
        self.address = address
        self.secret = secret
        self.ttl = ttl
        self.min_interval = min_interval
        self.next_send_at: dict[str, float] = {}

    def enabled(self) -> bool:
        return bool(self.address and self.secret)

    def send(self, client_ip: str, domain: str) -> None:
        if not self.address or not self.secret:
            return

        now = time.monotonic()
        if self.min_interval > 0 and self.next_send_at.get(client_ip, 0) > now:
            return

        packet = build_knock(self.secret, client_ip, domain, self.ttl)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as knock_socket:
            knock_socket.sendto(packet, self.address)

        if self.min_interval > 0:
            self.next_send_at[client_ip] = now + self.min_interval


def load_blocked_domains(path: Path) -> set[str]:
    """Загружает список запрещённых доменов из файла.

    Формат простой: один домен на строку. Пустые строки и строки с # пропускаются.
    """
    domains: set[str] = set()

    for line in path.read_text(encoding="utf-8").splitlines():
        domain = line.strip().lower().rstrip(".")
        if not domain or domain.startswith("#"):
            continue
        domains.add(domain)

    return domains


def is_blocked(domain: str, blocked_domains: set[str]) -> bool:
    """Проверяет домен и его поддомены по списку блокировки."""
    domain = domain.lower().rstrip(".")

    for blocked in blocked_domains:
        if domain == blocked or domain.endswith(f".{blocked}"):
            return True

    return False


def matches_suffix(domain: str, suffixes: tuple[str, ...]) -> bool:
    """Проверяет домен и его поддомены по списку suffix-фильтров."""
    domain = domain.lower().rstrip(".")

    for suffix in suffixes:
        suffix = suffix.lower().lstrip(".")
        if domain == suffix or domain.endswith(f".{suffix}"):
            return True

    return False


def is_allowed_direct(domain: str, direct_suffixes: tuple[str, ...]) -> bool:
    """Проверяет, должен ли домен открываться напрямую."""
    return matches_suffix(domain, direct_suffixes)


def parse_question(packet: bytes) -> DnsQuestion:
    """Достаёт домен, тип и класс из DNS-запроса."""
    if len(packet) < 12:
        raise ValueError("DNS packet is too short")

    labels: list[str] = []
    offset = 12  # Первые 12 байт занимает DNS-заголовок.

    while True:
        if offset >= len(packet):
            raise ValueError("DNS question is truncated")

        label_length = packet[offset]
        offset += 1

        # Нулевой байт означает конец имени домена.
        if label_length == 0:
            break

        # Сжатые имена через указатели в вопросе клиента для этой заготовки не нужны.
        if label_length & 0b1100_0000:
            raise ValueError("Compressed names are not supported in questions")

        label_end = offset + label_length
        if label_end > len(packet):
            raise ValueError("DNS label is truncated")

        labels.append(packet[offset:label_end].decode("ascii"))
        offset = label_end

    if offset + 4 > len(packet):
        raise ValueError("DNS question has no type/class")

    # После имени домена идут 2 байта типа записи и 2 байта класса.
    qtype, qclass = struct.unpack("!HH", packet[offset : offset + 4])
    return DnsQuestion(".".join(labels), qtype, qclass, offset + 4)


def build_error_response(packet: bytes, rcode: int) -> bytes:
    """Собирает минимальный DNS-ответ с ошибкой."""
    transaction_id = packet[:2] if len(packet) >= 2 else b"\x00\x00"
    flags = 0x8000 | rcode  # 0x8000 помечает пакет как ответ, а не запрос.
    empty_counts = b"\x00\x00\x00\x00\x00\x00\x00\x00"
    return transaction_id + struct.pack("!H", flags) + empty_counts


def build_answer(record_type: int, record_data: bytes, ttl: int = 60) -> bytes:
    """Собирает одну DNS-запись ответа."""
    name_pointer = b"\xc0\x0c"  # Ссылка на имя домена в вопросе: offset 12.
    return (
        name_pointer
        + struct.pack("!HHIH", record_type, CLASS_IN, ttl, len(record_data))
        + record_data
    )


def build_blocked_response(
    packet: bytes,
    question: DnsQuestion,
    blocked_ipv4: str,
    blocked_ipv6: str,
) -> bytes:
    """Возвращает подменный адрес вместо настоящего адреса заблокированного домена."""
    transaction_id = packet[:2]
    request_flags = struct.unpack("!H", packet[2:4])[0]

    # Сохраняем Recursion Desired и отвечаем Recursion Available.
    recursion_desired = request_flags & 0x0100
    flags = 0x8000 | recursion_desired | 0x0080

    question_bytes = packet[12 : question.end_offset]
    answers: list[bytes] = []

    if question.qclass == CLASS_IN and question.qtype in (TYPE_A, 255):
        answers.append(build_answer(TYPE_A, ipaddress.IPv4Address(blocked_ipv4).packed))

    if question.qclass == CLASS_IN and question.qtype in (TYPE_AAAA, 255):
        answers.append(build_answer(TYPE_AAAA, ipaddress.IPv6Address(blocked_ipv6).packed))

    if not answers:
        return build_error_response(packet, RCODE_NOT_IMPLEMENTED)

    # Header: flags, 1 вопрос, N ответов, 0 authority, 0 additional.
    header = transaction_id + struct.pack("!HHHHH", flags, 1, len(answers), 0, 0)
    return header + question_bytes + b"".join(answers)


def forward_to_upstream(packet: bytes, upstream_address: tuple[str, int], timeout: float) -> bytes:
    """Пересылает разрешённый DNS-запрос настоящему upstream DNS-серверу."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream_socket:
        upstream_socket.settimeout(timeout)

        try:
            upstream_socket.sendto(packet, upstream_address)
            response, _ = upstream_socket.recvfrom(4096)
            return response
        except TimeoutError:
            return build_error_response(packet, RCODE_FORMAT_ERROR)


def handle_packet(
    packet: bytes,
    client_address: tuple[str, int],
    blocked_domains: set[str],
    upstream_address: tuple[str, int],
    timeout: float,
    blocked_ipv4: str,
    blocked_ipv6: str,
    direct_suffixes: tuple[str, ...],
    redirect_suffixes: tuple[str, ...],
    knock_sender: KnockSender,
    log_queries: bool,
) -> bytes:
    """Обрабатывает один DNS-пакет: блокирует или проксирует дальше."""
    try:
        question = parse_question(packet)
    except (UnicodeDecodeError, ValueError):
        return build_error_response(packet, RCODE_FORMAT_ERROR)

    if is_blocked(question.name, blocked_domains):
        if log_queries:
            print(f"Blocked {question.name}; returning {blocked_ipv4}")
        knock_sender.send(client_address[0], question.name)
        return build_blocked_response(packet, question, blocked_ipv4, blocked_ipv6)

    if matches_suffix(question.name, redirect_suffixes):
        if log_queries:
            print(f"Redirect suffix match {question.name}; returning {blocked_ipv4}")
        knock_sender.send(client_address[0], question.name)
        return build_blocked_response(packet, question, blocked_ipv4, blocked_ipv6)

    if direct_suffixes and not is_allowed_direct(question.name, direct_suffixes):
        if log_queries:
            print(f"Non-direct domain {question.name}; returning {blocked_ipv4}")
        knock_sender.send(client_address[0], question.name)
        return build_blocked_response(packet, question, blocked_ipv4, blocked_ipv6)

    return forward_to_upstream(packet, upstream_address, timeout)


def serve_forever(
    blocked_domains: set[str],
    listen_address: tuple[str, int],
    upstream_address: tuple[str, int],
    timeout: float,
    blocked_ipv4: str,
    blocked_ipv6: str,
    direct_suffixes: tuple[str, ...],
    redirect_suffixes: tuple[str, ...],
    knock_sender: KnockSender,
    log_queries: bool,
) -> None:
    """Запускает UDP-сервер и отвечает на DNS-запросы бесконечно."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind(listen_address)

        print(f"DNS blocker listening on {listen_address[0]}:{listen_address[1]}")
        print(f"Loaded blocked domains: {len(blocked_domains)}")
        print(f"Blocked A records will point to {blocked_ipv4}")
        print(f"Direct suffixes: {', '.join(direct_suffixes) if direct_suffixes else '-'}")
        print(f"Redirect suffixes: {', '.join(redirect_suffixes) if redirect_suffixes else '-'}")
        print(f"Forwarding allowed requests to {upstream_address[0]}:{upstream_address[1]}")
        if knock_sender.enabled() and knock_sender.address:
            print(f"Sending UDP knocks to {knock_sender.address[0]}:{knock_sender.address[1]}")

        while True:
            packet, client_address = server_socket.recvfrom(512)
            response = handle_packet(
                packet,
                client_address,
                blocked_domains,
                upstream_address,
                timeout,
                blocked_ipv4,
                blocked_ipv6,
                direct_suffixes,
                redirect_suffixes,
                knock_sender,
                log_queries,
            )
            server_socket.sendto(response, client_address)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a simple local DNS blocker.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to listen on.")
    parser.add_argument("--port", default=5353, type=int, help="Port to listen on.")
    parser.add_argument("--blocked", default="blocked_domains.txt", help="Blocked domains file.")
    parser.add_argument("--upstream-host", default="8.8.8.8", help="Upstream DNS server.")
    parser.add_argument("--upstream-port", default=53, type=int, help="Upstream DNS port.")
    parser.add_argument("--timeout", default=2.0, type=float, help="Upstream timeout in seconds.")
    parser.add_argument("--blocked-ipv4", default="127.0.0.1", help="IPv4 returned for blocked A records.")
    parser.add_argument("--blocked-ipv6", default="::1", help="IPv6 returned for blocked AAAA records.")
    parser.add_argument(
        "--direct-suffixes",
        default="ru",
        help="Comma-separated domain suffixes opened directly. Empty value disables catch-all redirect mode.",
    )
    parser.add_argument(
        "--redirect-suffixes",
        default="",
        help="Comma-separated domain suffixes redirected to --blocked-ipv4.",
    )
    parser.add_argument("--knock-host", default=None, help="Redirect proxy UDP knock host.")
    parser.add_argument("--knock-port", default=9091, type=int, help="Redirect proxy UDP knock port.")
    parser.add_argument("--knock-secret", default=None, help="Shared HMAC secret for redirect proxy knocks.")
    parser.add_argument("--knock-ttl", default=60, type=int, help="Redirect proxy allowlist TTL in seconds.")
    parser.add_argument("--knock-min-interval", default=2.0, type=float, help="Minimum seconds between repeated knocks per client IP.")
    parser.add_argument("--log-queries", action="store_true", help="Print every blocked/non-direct DNS query.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    blocked_path = Path(args.blocked)
    blocked_domains = load_blocked_domains(blocked_path)
    listen_address = (args.host, args.port)
    upstream_address = (args.upstream_host, args.upstream_port)
    direct_suffixes = tuple(suffix.strip().lstrip(".") for suffix in args.direct_suffixes.split(",") if suffix.strip())
    redirect_suffixes = tuple(suffix.strip().lstrip(".") for suffix in args.redirect_suffixes.split(",") if suffix.strip())
    knock_address = (args.knock_host, args.knock_port) if args.knock_host else None
    knock_sender = KnockSender(knock_address, args.knock_secret, args.knock_ttl, args.knock_min_interval)

    serve_forever(
        blocked_domains=blocked_domains,
        listen_address=listen_address,
        upstream_address=upstream_address,
        timeout=args.timeout,
        blocked_ipv4=args.blocked_ipv4,
        blocked_ipv6=args.blocked_ipv6,
        direct_suffixes=direct_suffixes,
        redirect_suffixes=redirect_suffixes,
        knock_sender=knock_sender,
        log_queries=args.log_queries,
    )


if __name__ == "__main__":
    main()
