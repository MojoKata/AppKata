"""A minimal D-Bus client for the system bus, enough to drive PackageKit (requirement 16.8.1):
method calls with typed arguments and the signals of one object. Pure Python, so no new
dependency; PySide6's QtDBus can't send the unsigned 64-bit flags PackageKit's methods take."""

from __future__ import annotations

import os
import select
import socket
import struct
import time

SYSTEM_BUS = "/var/run/dbus/system_bus_socket"
CALL, RETURN, ERROR, SIGNAL = 1, 2, 3, 4
NO_REPLY, ALLOW_INTERACTIVE = 0x1, 0x4

_ALIGN = {"y": 1, "b": 4, "n": 2, "q": 2, "i": 4, "u": 4, "x": 8, "t": 8, "d": 8, "h": 4,
          "s": 4, "o": 4, "g": 1, "a": 4, "(": 8, "{": 8, "v": 1}
_FIXED = {"y": "B", "b": "I", "n": "h", "q": "H", "i": "i", "u": "I", "x": "q", "t": "Q", "d": "d", "h": "I"}


class DBusError(Exception):
    def __init__(self, name: str, message: str = ""):
        super().__init__(f"{name}: {message}" if message else name)
        self.name = name


class Variant:
    """A value with its own signature, for `v` arguments."""
    def __init__(self, sig: str, value):
        self.sig, self.value = sig, value

    def __repr__(self):
        return f"Variant({self.sig!r}, {self.value!r})"


class ObjectPath(str):
    pass


class Signature(str):
    pass


def split_types(sig: str) -> list[str]:
    """'a{sv}as' → ['a{sv}', 'as']."""
    out, i = [], 0
    while i < len(sig):
        j = _end(sig, i)
        out.append(sig[i:j])
        i = j
    return out


def _end(sig: str, i: int) -> int:
    c = sig[i]
    if c == "a":
        return _end(sig, i + 1)
    if c in "({":
        depth, j = 0, i
        while True:
            if sig[j] in "({":
                depth += 1
            elif sig[j] in ")}":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
    return i + 1


# ---------------------------------------------------------------- marshalling (little-endian)
class _W:
    def __init__(self):
        self.b = bytearray()

    def pad(self, n: int):
        self.b += b"\0" * ((-len(self.b)) % n)

    def put(self, t: str, v):
        c = t[0]
        self.pad(_ALIGN[c])
        if c in _FIXED:
            self.b += struct.pack("<" + _FIXED[c], int(v) if c != "d" else float(v))
        elif c in "so":
            e = str(v).encode()
            self.b += struct.pack("<I", len(e)) + e + b"\0"
        elif c == "g":
            e = str(v).encode()
            self.b += bytes([len(e)]) + e + b"\0"
        elif c == "v":
            sig = v.sig if isinstance(v, Variant) else _guess(v)
            val = v.value if isinstance(v, Variant) else v
            self.put("g", sig)
            self.put(sig, val)
        elif c == "a":
            inner = t[1:]
            self.b += b"\0\0\0\0"
            at = len(self.b) - 4
            self.pad(_ALIGN[inner[0]])
            start = len(self.b)
            items = v.items() if inner[0] == "{" else v
            for item in items:
                self.put(inner, item)
            struct.pack_into("<I", self.b, at, len(self.b) - start)
        elif c in "({":
            for sub, x in zip(split_types(t[1:-1]), v):
                self.put(sub, x)
        else:
            raise ValueError(f"unsupported type {t}")


def _guess(v) -> str:
    if isinstance(v, bool):
        return "b"
    if isinstance(v, int):
        return "i"
    if isinstance(v, str):
        return "s"
    if isinstance(v, list):
        return "as"
    raise ValueError(f"can't guess a D-Bus type for {v!r}")


class _R:
    def __init__(self, b: bytes, pos: int = 0):
        self.b, self.pos = b, pos

    def pad(self, n: int):
        self.pos += (-self.pos) % n

    def get(self, t: str):
        c = t[0]
        self.pad(_ALIGN[c])
        if c in _FIXED:
            fmt = "<" + _FIXED[c]
            v = struct.unpack_from(fmt, self.b, self.pos)[0]
            self.pos += struct.calcsize(fmt)
            return bool(v) if c == "b" else v
        if c in "so":
            n = struct.unpack_from("<I", self.b, self.pos)[0]
            s = self.b[self.pos + 4:self.pos + 4 + n].decode("utf-8", "replace")
            self.pos += 4 + n + 1
            return ObjectPath(s) if c == "o" else s
        if c == "g":
            n = self.b[self.pos]
            s = self.b[self.pos + 1:self.pos + 1 + n].decode()
            self.pos += n + 2
            return Signature(s)
        if c == "v":
            sig = self.get("g")
            return Variant(sig, self.get(sig))
        if c == "a":
            n = struct.unpack_from("<I", self.b, self.pos)[0]
            self.pos += 4
            inner = t[1:]
            self.pad(_ALIGN[inner[0]])
            end = self.pos + n
            if inner[0] == "{":
                out = {}
                while self.pos < end:
                    k, v = self.get(inner)
                    out[k] = v
                return out
            out_l = []
            while self.pos < end:
                out_l.append(self.get(inner))
            return out_l
        if c in "({":
            return tuple(self.get(sub) for sub in split_types(t[1:-1]))
        raise ValueError(f"unsupported type {t}")


def marshal_message(mtype: int, serial: int, fields: dict, sig: str = "", args=(), flags: int = 0) -> bytes:
    body = _W()
    for t, a in zip(split_types(sig), args):
        body.put(t, a)
    hdr = _W()
    hdr.b += b"l" + bytes([mtype, flags, 1])
    hdr.b += struct.pack("<II", len(body.b), serial)
    f = []
    codes = {"path": (1, "o"), "interface": (2, "s"), "member": (3, "s"), "error": (4, "s"),
             "reply_serial": (5, "u"), "destination": (6, "s"), "sender": (7, "s")}
    for k, v in fields.items():
        code, t = codes[k]
        f.append((code, Variant(t, v)))
    if sig:
        f.append((8, Variant("g", sig)))
    hdr.put("a(yv)", f)
    hdr.pad(8)
    return bytes(hdr.b) + bytes(body.b)


def unmarshal_message(data: bytes) -> tuple[dict, int]:
    """(message, bytes used), or ({}, 0) when `data` doesn't hold a whole message yet."""
    if len(data) < 16:
        return {}, 0
    if data[0:1] != b"l":
        raise DBusError("org.freedesktop.DBus.Error.Protocol", "big-endian messages aren't supported")
    mtype, flags = data[1], data[2]
    blen, serial, flen = struct.unpack_from("<III", data, 4)
    hlen = 16 + flen
    hlen += (-hlen) % 8
    if len(data) < hlen + blen:
        return {}, 0
    r = _R(data, 12)
    fields = r.get("a(yv)")
    names = {1: "path", 2: "interface", 3: "member", 4: "error", 5: "reply_serial", 6: "destination",
             7: "sender", 8: "signature"}
    msg = {"type": mtype, "flags": flags, "serial": serial}
    for code, v in fields:
        if code in names:
            msg[names[code]] = v.value
    sig = msg.get("signature", "")
    br = _R(data[hlen:hlen + blen])
    msg["args"] = [br.get(t) for t in split_types(sig)] if sig else []
    return msg, hlen + blen


# ---------------------------------------------------------------- the connection
class Connection:
    def __init__(self, path: str | None = None, timeout: float = 30):
        addr = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS", "")
        if not path and addr.startswith("unix:path="):
            path = addr.split("=", 1)[1].split(",", 1)[0]
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path or SYSTEM_BUS)
        self.serial = 0
        self.buf = b""
        self.pending: list[dict] = []
        self._auth()
        self.name = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "Hello")[0]

    def _auth(self):
        self.sock.sendall(b"\0AUTH EXTERNAL " + str(os.getuid()).encode().hex().encode() + b"\r\n")
        line = b""
        while not line.endswith(b"\r\n"):
            chunk = self.sock.recv(256)
            if not chunk:
                raise DBusError("org.freedesktop.DBus.Error.AuthFailed", "the bus closed the connection")
            line += chunk
        if not line.startswith(b"OK"):
            raise DBusError("org.freedesktop.DBus.Error.AuthFailed", line.decode(errors="replace").strip())
        self.sock.sendall(b"BEGIN\r\n")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def send(self, mtype: int, fields: dict, sig: str = "", args=(), flags: int = 0) -> int:
        self.serial += 1
        self.sock.sendall(marshal_message(mtype, self.serial, fields, sig, args, flags))
        return self.serial

    def read(self, timeout: float | None = None) -> dict | None:
        """The next message, or None after `timeout` seconds."""
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            msg, used = unmarshal_message(self.buf)
            if used:
                self.buf = self.buf[used:]
                return msg
            wait = None if end is None else max(0.0, end - time.monotonic())
            if end is not None and wait == 0:
                return None
            r, _, _ = select.select([self.sock], [], [], wait)
            if not r:
                return None
            chunk = self.sock.recv(65536)
            if not chunk:
                raise DBusError("org.freedesktop.DBus.Error.Disconnected", "the bus closed the connection")
            self.buf += chunk

    def call(self, dest: str, path: str, iface: str, member: str, sig: str = "", args=(),
             interactive: bool = False, timeout: float = 120) -> list:
        s = self.send(CALL, {"path": path, "interface": iface, "member": member, "destination": dest}, sig, args,
                      ALLOW_INTERACTIVE if interactive else 0)
        end = time.monotonic() + timeout
        while True:
            m = self.read(max(0.0, end - time.monotonic()))
            if m is None:
                raise DBusError("org.freedesktop.DBus.Error.Timeout", f"{member} didn't answer")
            if m.get("reply_serial") == s:
                if m["type"] == ERROR:
                    raise DBusError(m.get("error", "?"), m["args"][0] if m["args"] else "")
                return m["args"]
            if m["type"] == SIGNAL:
                self.pending.append(m)

    def add_match(self, rule: str) -> None:
        self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "AddMatch", "s", [rule])

    def next_signal(self, timeout: float | None = None) -> dict | None:
        if self.pending:
            return self.pending.pop(0)
        while True:
            m = self.read(timeout)
            if m is None or m["type"] == SIGNAL:
                return m

    def has_name(self, name: str) -> bool:
        """Running, or startable on demand (PackageKit is activated by the bus)."""
        try:
            for member in ("ListNames", "ListActivatableNames"):
                if name in self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", member)[0]:
                    return True
        except DBusError:
            pass
        return False
