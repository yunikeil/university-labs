from __future__ import annotations

import hashlib
import hmac
import os
import socket
import struct
import threading


BUFFER_SIZE = 1024 * 1024
SALT_SIZE = 32
TAG_SIZE = 16
MAX_FRAME_SIZE = 2 * 1024 * 1024
PROTECTED_STREAM_BYTES = 64 * 1024

FRAME_OPEN = b"H"
FRAME_OK = b"O"
FRAME_ERROR = b"R"
FRAME_DATA = b"D"
FRAME_EOF = b"E"


class TunnelProtocolError(Exception):
    """The peer sent malformed or unauthenticated tunnel data."""


class FrameCipher:
    """Small framed stream cipher built from HMAC-SHA256.

    This is an obfuscation layer for our own proxy pair, not a replacement for
    audited transport security. It hides HTTP CONNECT targets and TLS SNI from
    simple DPI between the browser proxy and redirect proxy.
    """

    def __init__(self, secret: str, salt: bytes, role: str) -> None:
        secret_bytes = secret.encode("utf-8")
        c2s_key = hmac.new(secret_bytes, salt + b"c2s", hashlib.sha256).digest()
        s2c_key = hmac.new(secret_bytes, salt + b"s2c", hashlib.sha256).digest()

        if role == "client":
            self.tx_key = c2s_key
            self.rx_key = s2c_key
        elif role == "server":
            self.tx_key = s2c_key
            self.rx_key = c2s_key
        else:
            raise ValueError(f"Invalid tunnel role: {role}")

        self.tx_seq = 0
        self.rx_seq = 0
        self.tx_protected_remaining = PROTECTED_STREAM_BYTES
        self.rx_protected_remaining = PROTECTED_STREAM_BYTES
        self.tx_lock = threading.Lock()

    def send_frame(self, sock: socket.socket, payload: bytes) -> None:
        if len(payload) > MAX_FRAME_SIZE:
            raise ValueError(f"Tunnel frame is too large: {len(payload)}")

        with self.tx_lock:
            seq = self.tx_seq
            self.tx_seq += 1

        header = struct.pack("!I", len(payload))
        header_mask = self._mask(self.tx_key, b"header", seq, 4)
        encrypted_header = xor_bytes(header, header_mask)
        encrypted_payload = self._crypt_payload(self.tx_key, b"payload", seq, payload, tx=True)
        tag = hmac.new(
            self.tx_key,
            b"tag" + struct.pack("!Q", seq) + encrypted_header + encrypted_payload,
            hashlib.sha256,
        ).digest()[:TAG_SIZE]
        sock.sendall(encrypted_header + encrypted_payload + tag)

    def recv_frame(self, sock: socket.socket) -> bytes:
        seq = self.rx_seq
        self.rx_seq += 1

        encrypted_header = recv_exact(sock, 4)
        if len(encrypted_header) < 4:
            raise EOFError("Tunnel closed while reading frame header")

        header_mask = self._mask(self.rx_key, b"header", seq, 4)
        payload_size = struct.unpack("!I", xor_bytes(encrypted_header, header_mask))[0]
        if payload_size > MAX_FRAME_SIZE:
            raise TunnelProtocolError(f"Tunnel frame is too large: {payload_size}")

        encrypted_payload = recv_exact(sock, payload_size)
        tag = recv_exact(sock, TAG_SIZE)
        if len(encrypted_payload) < payload_size or len(tag) < TAG_SIZE:
            raise EOFError("Tunnel closed while reading frame body")

        expected = hmac.new(
            self.rx_key,
            b"tag" + struct.pack("!Q", seq) + encrypted_header + encrypted_payload,
            hashlib.sha256,
        ).digest()[:TAG_SIZE]
        if not hmac.compare_digest(tag, expected):
            raise TunnelProtocolError("Tunnel frame authentication failed")

        return self._crypt_payload(self.rx_key, b"payload", seq, encrypted_payload, tx=False)

    def _crypt_payload(self, key: bytes, label: bytes, seq: int, payload: bytes, *, tx: bool) -> bytes:
        if not tx:
            first_byte = xor_bytes(payload[:1], self._mask(key, label, seq, 1))
            encrypt_all = first_byte != FRAME_DATA
        else:
            encrypt_all = not payload.startswith(FRAME_DATA)

        if encrypt_all:
            return xor_bytes(payload, self._mask(key, label, seq, len(payload)))

        remaining = self.tx_protected_remaining if tx else self.rx_protected_remaining
        protected_data_size = min(max(remaining, 0), max(len(payload) - 1, 0))
        protected_size = 1 + protected_data_size

        if tx:
            self.tx_protected_remaining -= protected_data_size
        else:
            self.rx_protected_remaining -= protected_data_size

        if protected_size <= 0:
            return payload

        protected = xor_bytes(payload[:protected_size], self._mask(key, label, seq, protected_size))
        return protected + payload[protected_size:]

    @staticmethod
    def _mask(key: bytes, label: bytes, seq: int, size: int) -> bytes:
        if size <= 0:
            return b""
        seed = key + label + struct.pack("!Q", seq)
        return hashlib.shake_256(seed).digest(size)


def open_tunnel(host: str, port: int, secret: str, timeout: float) -> tuple[socket.socket, FrameCipher]:
    sock = socket.create_connection((host, port), timeout=timeout)
    salt = os.urandom(SALT_SIZE)
    sock.sendall(salt)
    return sock, FrameCipher(secret, salt, "client")


def accept_tunnel(sock: socket.socket, secret: str, timeout: float) -> FrameCipher:
    sock.settimeout(timeout)
    salt = recv_exact(sock, SALT_SIZE)
    if len(salt) < SALT_SIZE:
        raise EOFError("Tunnel closed while reading salt")
    return FrameCipher(secret, salt, "server")


def build_open_frame(host: str, port: int, initial_data: bytes) -> bytes:
    host_bytes = host.rstrip(".").encode("idna")
    if len(host_bytes) > 65535:
        raise ValueError(f"Tunnel target host is too long: {host}")
    if port < 1 or port > 65535:
        raise ValueError(f"Tunnel target port is invalid: {port}")

    return (
        FRAME_OPEN
        + struct.pack("!H", len(host_bytes))
        + host_bytes
        + struct.pack("!H", port)
        + struct.pack("!I", len(initial_data))
        + initial_data
    )


def parse_open_frame(payload: bytes) -> tuple[str, int, bytes]:
    if not payload.startswith(FRAME_OPEN):
        raise TunnelProtocolError("Expected tunnel open frame")

    offset = 1
    if offset + 2 > len(payload):
        raise TunnelProtocolError("Truncated tunnel host length")
    host_length = struct.unpack("!H", payload[offset : offset + 2])[0]
    offset += 2

    if offset + host_length + 2 + 4 > len(payload):
        raise TunnelProtocolError("Truncated tunnel open frame")

    host = payload[offset : offset + host_length].decode("idna")
    offset += host_length
    port = struct.unpack("!H", payload[offset : offset + 2])[0]
    offset += 2
    initial_size = struct.unpack("!I", payload[offset : offset + 4])[0]
    offset += 4

    if offset + initial_size != len(payload):
        raise TunnelProtocolError("Invalid tunnel initial payload length")

    return host, port, payload[offset:]


def build_error_frame(message: str) -> bytes:
    return FRAME_ERROR + message.encode("utf-8", errors="replace")[:4096]


def parse_response_frame(payload: bytes) -> None:
    if payload == FRAME_OK:
        return
    if payload.startswith(FRAME_ERROR):
        raise OSError(payload[1:].decode("utf-8", errors="replace"))
    raise TunnelProtocolError("Unexpected tunnel response frame")


def relay_pair(plain: socket.socket, tunnel: socket.socket, cipher: FrameCipher) -> None:
    upstream_thread = threading.Thread(target=relay_plain_to_tunnel, args=(plain, tunnel, cipher), daemon=True)
    upstream_thread.start()

    try:
        relay_tunnel_to_plain(tunnel, plain, cipher)
    finally:
        close_socket(plain)
        close_socket(tunnel)
        upstream_thread.join(timeout=1.0)


def relay_plain_to_tunnel(plain: socket.socket, tunnel: socket.socket, cipher: FrameCipher) -> None:
    buffer = bytearray(BUFFER_SIZE)
    try:
        while True:
            size = plain.recv_into(buffer)
            if not size:
                cipher.send_frame(tunnel, FRAME_EOF)
                return
            cipher.send_frame(tunnel, FRAME_DATA + bytes(memoryview(buffer)[:size]))
    except OSError:
        close_socket(tunnel)


def relay_tunnel_to_plain(tunnel: socket.socket, plain: socket.socket, cipher: FrameCipher) -> None:
    while True:
        payload = cipher.recv_frame(tunnel)
        if payload == FRAME_EOF:
            shutdown_write(plain)
            return
        if not payload.startswith(FRAME_DATA):
            raise TunnelProtocolError("Unexpected tunnel data frame")
        plain.sendall(payload[1:])


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def close_socket(sock: socket.socket) -> None:
    try:
        sock.close()
    except OSError:
        pass


def shutdown_write(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_WR)
    except OSError:
        pass
