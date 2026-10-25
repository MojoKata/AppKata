"""SSH signatures (git's gpg.format=ssh) verified in pure Python, so trust checks don't
depend on the installed OpenSSH (ssh-keygen -Y needs 8.2+; Windows 10 and RHEL 8 ship older).

Supports ssh-ed25519, rsa-sha2-256/512 and ecdsa-sha2-nistp256 (PROTOCOL.sshsig).
Ed25519 signing is included for tests and demo data only.
"""

from __future__ import annotations

import base64
import hashlib
import struct

ARMOR_BEGIN = "-----BEGIN SSH SIGNATURE-----"
ARMOR_END = "-----END SSH SIGNATURE-----"
MAGIC = b"SSHSIG"


class SshSigError(ValueError):
    pass


# ---------------------------------------------------------------- wire format
def _string(b: bytes) -> bytes:
    return struct.pack(">I", len(b)) + b


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.i = data, 0

    def take(self, n: int) -> bytes:
        if self.i + n > len(self.d):
            raise SshSigError("truncated SSH signature")
        out = self.d[self.i:self.i + n]
        self.i += n
        return out

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def string(self) -> bytes:
        return self.take(self.u32())

    def mpint(self) -> int:
        return int.from_bytes(self.string(), "big", signed=False)


def fingerprint(pubkey_blob: bytes) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(pubkey_blob).digest()).decode().rstrip("=")


def key_line(pubkey_blob: bytes) -> str:
    kind = _Reader(pubkey_blob).string().decode()
    return f"{kind} {base64.b64encode(pubkey_blob).decode()}"


def blob_from_line(line: str) -> bytes:
    parts = line.split()
    return base64.b64decode(parts[1] if len(parts) > 1 else parts[0])


# ---------------------------------------------------------------- ed25519 (RFC 8032)
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if x % 2:
        x = _P - x
    return x


_BY = 4 * pow(5, _P - 2, _P) % _P
_B = (_xrecover(_BY), _BY, 1, _xrecover(_BY) * _BY % _P)


def _add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    dd = z1 * 2 * z2 % _P
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _enc(p) -> bytes:
    x, y, z, _ = p
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _dec(s: bytes):
    if len(s) != 32:
        raise SshSigError("bad ed25519 point")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    if y >= _P:
        raise SshSigError("bad ed25519 point")
    x = _xrecover(y)
    if (x & 1) != (s[31] >> 7):
        x = _P - x
    p = (x, y, 1, x * y % _P)
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _P:
        raise SshSigError("point not on curve")
    return p


def _eq(p, q) -> bool:
    x1, y1, z1, _ = p
    x2, y2, z2, _ = q
    return (x1 * z2 - x2 * z1) % _P == 0 and (y1 * z2 - y2 * z1) % _P == 0


def ed25519_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(sig) != 64:
        return False
    try:
        a, r = _dec(pub), _dec(sig[:32])
    except SshSigError:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    return _eq(_mul(s, _B), _add(r, _mul(h, a)))


def ed25519_keypair(seed: bytes) -> tuple[bytes, bytes]:
    """(seed, public key) — for tests and demo data."""
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    return seed, _enc(_mul(a, _B))


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little") & ((1 << 254) - 8) | (1 << 254)
    pub = _enc(_mul(a, _B))
    r = int.from_bytes(hashlib.sha512(h[32:] + msg).digest(), "little") % _L
    rp = _enc(_mul(r, _B))
    k = int.from_bytes(hashlib.sha512(rp + pub + msg).digest(), "little") % _L
    return rp + ((r + k * a) % _L).to_bytes(32, "little")


# ---------------------------------------------------------------- rsa, ecdsa p-256
_DIGEST_INFO = {"sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
                "sha512": bytes.fromhex("3051300d060960864801650304020305000440")}


def _rsa_verify(e: int, n: int, msg: bytes, sig: bytes, hname: str) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(sig) != k or n.bit_length() < 2048:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = _DIGEST_INFO[hname] + hashlib.new(hname, msg).digest()
    return em == b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


_P256 = (0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff,
         0xffffffff00000001000000000000000000000000fffffffffffffffffffffffc,
         0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b,
         0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
         0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5,
         0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551)


def _ec_add(p1, p2, pm):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % pm == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 - 3) * pow(2 * y1, pm - 2, pm) % pm
    else:
        lam = (y2 - y1) * pow(x2 - x1, pm - 2, pm) % pm
    x3 = (lam * lam - x1 - x2) % pm
    return (x3, (lam * (x1 - x3) - y1) % pm)


def _ec_mul(k, pt, pm):
    acc = None
    while k:
        if k & 1:
            acc = _ec_add(acc, pt, pm)
        pt = _ec_add(pt, pt, pm)
        k >>= 1
    return acc


def _p256_verify(q: bytes, msg: bytes, r: int, s: int) -> bool:
    pm, _, b, gx, gy, n = _P256
    if len(q) != 65 or q[0] != 4 or not (0 < r < n and 0 < s < n):
        return False
    qx, qy = int.from_bytes(q[1:33], "big"), int.from_bytes(q[33:], "big")
    if (qy * qy - (qx ** 3 - 3 * qx + b)) % pm:
        return False
    z = int.from_bytes(hashlib.sha256(msg).digest(), "big")
    w = pow(s, n - 2, n)
    pt = _ec_add(_ec_mul(z * w % n, (gx, gy), pm), _ec_mul(r * w % n, (qx, qy), pm), pm)
    return pt is not None and pt[0] % n == r


# ---------------------------------------------------------------- SSHSIG
def parse_armor(armored: str) -> bytes:
    body = armored.strip()
    if ARMOR_BEGIN not in body or ARMOR_END not in body:
        raise SshSigError("not an SSH signature")
    inner = body.split(ARMOR_BEGIN, 1)[1].split(ARMOR_END, 1)[0]
    return base64.b64decode("".join(inner.split()))


def signer_blob(armored: str) -> bytes:
    """The public key blob embedded in a signature (who claims to have signed)."""
    r = _Reader(parse_armor(armored))
    if r.take(6) != MAGIC or r.u32() != 1:
        raise SshSigError("unsupported SSH signature version")
    return r.string()


def verify(armored: str, message: bytes, namespace: str = "git") -> bytes:
    """Verify an SSHSIG over `message`; return the signer's public key blob. Raises SshSigError."""
    r = _Reader(parse_armor(armored))
    if r.take(6) != MAGIC or r.u32() != 1:
        raise SshSigError("unsupported SSH signature version")
    pub = r.string()
    ns = r.string().decode()
    reserved = r.string()
    halg = r.string().decode()
    sigwrap = _Reader(r.string())
    if ns != namespace:
        raise SshSigError(f"signature namespace is {ns!r}, expected {namespace!r}")
    if halg not in ("sha256", "sha512"):
        raise SshSigError(f"unsupported hash {halg}")
    signed = MAGIC + _string(ns.encode()) + _string(reserved) + _string(halg.encode()) + \
        _string(hashlib.new(halg, message).digest())
    sig_alg = sigwrap.string().decode()
    sig = sigwrap.string()
    k = _Reader(pub)
    key_alg = k.string().decode()
    ok = False
    if key_alg == "ssh-ed25519" and sig_alg == "ssh-ed25519":
        ok = ed25519_verify(k.string(), signed, sig)
    elif key_alg == "ssh-rsa" and sig_alg in ("rsa-sha2-256", "rsa-sha2-512"):
        e, n = k.mpint(), k.mpint()
        ok = _rsa_verify(e, n, signed, sig, "sha256" if sig_alg.endswith("256") else "sha512")
    elif key_alg == "ecdsa-sha2-nistp256" and sig_alg == key_alg:
        k.string()                                   # curve name
        q = k.string()
        sr = _Reader(sig)
        ok = _p256_verify(q, signed, sr.mpint(), sr.mpint())
    else:
        raise SshSigError(f"unsupported key type {key_alg}")
    if not ok:
        raise SshSigError("the signature doesn't match")
    return pub


def sign_ed25519(seed: bytes, message: bytes, namespace: str = "git") -> str:
    """An armored SSHSIG (tests and demo data)."""
    _, pub = ed25519_keypair(seed)
    pub_blob = _string(b"ssh-ed25519") + _string(pub)
    signed = MAGIC + _string(namespace.encode()) + _string(b"") + _string(b"sha512") + \
        _string(hashlib.sha512(message).digest())
    sig = _string(b"ssh-ed25519") + _string(ed25519_sign(seed, signed))
    blob = MAGIC + struct.pack(">I", 1) + _string(pub_blob) + _string(namespace.encode()) + _string(b"") + \
        _string(b"sha512") + _string(sig)
    b64 = base64.b64encode(blob).decode()
    return "\n".join([ARMOR_BEGIN] + [b64[i:i + 70] for i in range(0, len(b64), 70)] + [ARMOR_END])


def ed25519_pub_blob(seed: bytes) -> bytes:
    return _string(b"ssh-ed25519") + _string(ed25519_keypair(seed)[1])
