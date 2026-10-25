"""One AppKata at a time (requirement 1.9): a second start hands its arguments to the running
AppKata over a per-user local socket, then exits."""

from __future__ import annotations

import getpass
import hashlib
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from appkata_core.platform import data_dir


def server_name() -> str:
    """Per user and per data folder, so test and demo copies run side by side."""
    key = f"{getpass.getuser()}|{data_dir()}".encode()
    return "appkata-" + hashlib.sha1(key).hexdigest()[:12]


def hand_over(msg: dict, timeout_ms: int = 800) -> bool:
    """True when a running AppKata took the message (this start should exit)."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(json.dumps(msg).encode() + b"\n")
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class Server(QObject):
    received = Signal(dict)

    def __init__(self):
        super().__init__()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(server_name())        # a stale socket from a crash
        self.server.listen(server_name())
        self.server.newConnection.connect(self._accept)

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()

            def read(sock=sock, buf=buf):
                buf.extend(bytes(sock.readAll()))
                if buf.endswith(b"\n"):
                    try:
                        self.received.emit(json.loads(buf.decode()))
                    except ValueError:
                        pass
                    sock.disconnectFromServer()
            sock.readyRead.connect(read)
            if sock.bytesAvailable():
                read()


def listen() -> Server:
    return Server()
