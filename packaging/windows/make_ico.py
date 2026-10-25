"""Render src/appkata/qml/assets/appkata.svg into appkata.ico (16–256 px, PNG-compressed
entries). Run with the project's venv: .venv/bin/python packaging/windows/make_ico.py"""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "..", "..", "src", "appkata", "qml", "assets", "appkata.svg")
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main() -> None:
    QGuiApplication(sys.argv)
    r = QSvgRenderer(SVG)
    images = [png(r, s) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in zip(SIZES, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(os.path.join(HERE, "appkata.ico"), "wb") as f:
        f.write(out + b"".join(images))


if __name__ == "__main__":
    main()
