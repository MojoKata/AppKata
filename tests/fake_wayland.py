"""A stand-in Wayland compositor that answers the registry and nothing else (review 3, harness 4).

The session warning lists the globals a compositor offers (17.9; review 2, F7). This answers a
client's wl_display.get_registry and sync with a chosen list of globals, so tier 1 can run the
product's own reader against each compositor of harness 4's table. The real ones are checked in the
`wayland`, `kwin` and `kwin6` harnesses.
"""

import os
import socket
import struct
import threading

BASE = ["wl_compositor", "wl_subcompositor", "wl_shm", "wl_seat", "wl_output", "xdg_wm_base", "zwp_linux_dmabuf_v1",
        "wp_viewporter", "wl_data_device_manager"]
WLROOTS = ["zwlr_screencopy_manager_v1", "zwlr_data_control_manager_v1", "zwp_virtual_keyboard_manager_v1",
           "zwlr_virtual_pointer_manager_v1", "zwlr_layer_shell_v1"]
KWIN = ["zwlr_data_control_manager_v1", "org_kde_plasma_shell", "org_kde_kwin_server_decoration_manager"]
OFFERS = {"mutter": BASE, "sway": BASE + WLROOTS, "labwc": BASE + WLROOTS, "phoc": BASE + WLROOTS,
          "kwin5": BASE + KWIN, "kwin6": BASE + KWIN, "unknown": BASE + ["ext_foreign_toplevel_list_v1"]}


def _msg(obj: int, op: int, payload: bytes) -> bytes:
    return struct.pack("=II", obj, ((8 + len(payload)) << 16) | op) + payload


def _string(s: str) -> bytes:
    b = s.encode() + b"\0"
    return struct.pack("=I", len(b)) + b + b"\0" * (-len(b) % 4)


class FakeCompositor:
    """Listens at `path` and answers each client's registry round trip with `globals_`."""

    def __init__(self, path: str, globals_: list[str]):
        self.path, self.globals = path, globals_
        if os.path.lexists(path):
            os.unlink(path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(4)
        self.sock.settimeout(0.2)
        self.stop = False
        self.t = threading.Thread(target=self._serve, daemon=True)
        self.t.start()

    def _serve(self):
        while not self.stop:
            try:
                c, _ = self.sock.accept()
            except OSError:
                continue
            with c:
                c.settimeout(2)
                buf, registry, callback = b"", None, None
                try:
                    while callback is None:
                        chunk = c.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        while len(buf) >= 8:
                            obj, word = struct.unpack_from("=II", buf)
                            size, op = word >> 16, word & 0xFFFF
                            if len(buf) < size:
                                break
                            new_id = struct.unpack_from("=I", buf, 8)[0]
                            buf = buf[size:]
                            if obj == 1 and op == 1:
                                registry = new_id
                            elif obj == 1 and op == 0:
                                callback = new_id
                    if registry is None or callback is None:
                        continue
                    out = b"".join(_msg(registry, 0, struct.pack("=I", i + 1) + _string(g) + struct.pack("=I", 1))
                                   for i, g in enumerate(self.globals))
                    out += _msg(callback, 0, struct.pack("=I", 1)) + _msg(1, 1, struct.pack("=I", callback))
                    c.sendall(out)
                except OSError:
                    pass

    def close(self):
        self.stop = True
        self.t.join(timeout=2)
        self.sock.close()
        if os.path.lexists(self.path):
            os.unlink(self.path)
