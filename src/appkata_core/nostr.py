"""Just enough Nostr for Explore (requirement 7.7): a minimal WebSocket client (RFC 6455) to ask
relays for ngit repository announcements (NIP-34, kind 30617), and NIP-19 encodings for links."""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
import time
from urllib.parse import urlsplit

DEFAULT_RELAYS = ["wss://relay.ngit.dev", "wss://gitnostr.com", "wss://nos.lol", "wss://relay.damus.io"]
REPO_ANNOUNCEMENT = 30617


class NostrError(Exception):
    pass


# ---------------------------------------------------------------- bech32 (NIP-19)
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (b >> i) & 1 else 0
    return chk


def _convert(data: bytes, frombits=8, tobits=5) -> list[int]:
    acc = bits = 0
    out = []
    for b in data:
        acc = (acc << frombits) | b
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & ((1 << tobits) - 1))
    if bits:
        out.append((acc << (tobits - bits)) & ((1 << tobits) - 1))
    return out


def bech32(hrp: str, data: bytes) -> str:
    d = _convert(data)
    values = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + d
    pm = _polymod(values + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CHARSET[x] for x in d + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


def npub(pubkey_hex: str) -> str:
    return bech32("npub", bytes.fromhex(pubkey_hex))


def naddr(kind: int, pubkey_hex: str, identifier: str, relays: list[str] = ()) -> str:
    tlv = bytes([0, len(identifier.encode())]) + identifier.encode()
    for r in relays[:2]:
        tlv += bytes([1, len(r.encode())]) + r.encode()
    tlv += bytes([2, 32]) + bytes.fromhex(pubkey_hex) + bytes([3, 4]) + struct.pack(">I", kind)
    return bech32("naddr", tlv)


# ---------------------------------------------------------------- websocket
class WebSocket:
    def __init__(self, url: str, timeout: float = 8.0):
        u = urlsplit(url)
        port = u.port or (443 if u.scheme == "wss" else 80)
        raw = socket.create_connection((u.hostname, port), timeout=timeout)
        self.s = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname) if u.scheme == "wss" else raw
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: AppKata\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(4096)
            if not chunk:
                raise NostrError("relay closed the connection")
            head += chunk
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise NostrError(f"relay refused the WebSocket: {status.decode(errors='replace')}")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise NostrError("relay closed the connection")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        msg = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7f
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else b""
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            op = b0 & 0x0f
            if op == 8:
                raise NostrError("relay closed the connection")
            if op == 9:            # ping → pong
                self.s.sendall(bytes([0x8a, 0x80]) + os.urandom(4))
                continue
            if op in (0, 1, 2):
                msg += payload
                if b0 & 0x80:
                    return msg.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


def query(relay: str, filt: dict, timeout: float = 8.0) -> list[dict]:
    """Events matching a filter from one relay (until EOSE or timeout)."""
    ws = WebSocket(relay, timeout)
    try:
        sub = "appkata-" + os.urandom(4).hex()
        ws.send(json.dumps(["REQ", sub, filt]))
        out, end = [], time.time() + timeout
        while time.time() < end:
            msg = json.loads(ws.recv())
            if msg[0] == "EVENT" and msg[1] == sub:
                out.append(msg[2])
            elif msg[0] in ("EOSE", "CLOSED") and msg[1] == sub:
                break
        return out
    finally:
        ws.close()


def repo_announcements(relays: list[str], limit: int = 500) -> tuple[list[dict], list[str]]:
    """(events, errors) for kind 30617 from each relay, newest per (pubkey, d-tag)."""
    seen: dict[tuple, dict] = {}
    errors = []
    for r in relays:
        try:
            for e in query(r, {"kinds": [REPO_ANNOUNCEMENT], "limit": limit}):
                d = next((t[1] for t in e.get("tags", []) if t and t[0] == "d" and len(t) > 1), "")
                k = (e.get("pubkey"), d)
                if d and (k not in seen or e.get("created_at", 0) > seen[k].get("created_at", 0)):
                    seen[k] = e
        except (OSError, NostrError, ValueError) as ex:
            errors.append(f"{r}: {ex}")
    return list(seen.values()), errors
