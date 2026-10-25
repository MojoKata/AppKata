"""What a screen draws outside its box: each visible text checked against the card, chip or dialog
it sits in (review 3, R3-22).

The tour runs it on every screen it saves, and tests run it on dialogs given long values. A text's
box is the nearest filled Rectangle it is drawn in, or the background of the nearest control or
popup that has one, else the window. A clipping ancestor between a text and its box hides what it
clips (a field's text, a list's rows inside the list), and that isn't judged; one above the box
doesn't, so a card scrolled out of view is still judged against its own text.
"""

from __future__ import annotations

SLACK = 2.0          # px: antialiasing and fonts' line heights


def _filled(item) -> bool:
    if item is None or not item.isVisible() or item.width() <= 0 or item.height() <= 0:
        return False
    if not item.inherits("QQuickRectangle"):
        return False
    color = item.property("color")
    return color is not None and color.alpha() > 0


def _box(item):
    """The scene rect of what `item` is drawn in, what that is, and the ancestor it belongs to."""
    p = item.parentItem()
    while p is not None:
        if _filled(p):
            return p.mapRectToScene(p.boundingRect()), p, p
        bg = p.property("background") if p.inherits("QQuickControl") else None
        if _filled(bg):
            return bg.mapRectToScene(bg.boundingRect()), bg, p
        p = p.parentItem()
    return None, None, None


def _drawn(item):
    """The scene rect an item paints: for a Text its laid-out text (QQuickText::boundingRect), wherever
    its alignment and padding put it; fields and editors draw inside themselves."""
    if item.inherits("QQuickText"):
        return item.mapRectToScene(item.boundingRect())
    from PySide6.QtCore import QRectF
    return item.mapRectToScene(QRectF(0, 0, item.width(), item.height()))


def _shown(item, rect, owner=None):
    """`rect` less what the clipping ancestors up to `owner` (the box's, itself included) hide."""
    p = item.parentItem()
    while p is not None and not rect.isEmpty():
        if p.clip():
            rect = rect.intersected(p.mapRectToScene(p.boundingRect()))
        if p is owner:
            break
        p = p.parentItem()
    return rect


def _texts(item):
    if not item.isVisible() or item.opacity() <= 0:
        return
    if item.inherits("QQuickText") or item.inherits("QQuickTextEdit") or item.inherits("QQuickTextInput"):
        if str(item.property("text") or "").strip():
            yield item
    for child in item.childItems():
        yield from _texts(child)


def faults(window) -> list[dict]:
    """Each visible text drawn outside its box: {"text": the text, "line": what is wrong, said}."""
    from PySide6.QtCore import QRectF
    root = window.contentItem()
    screen = QRectF(0, 0, window.width(), window.height())
    out = []
    for t in _texts(root):
        box, what, owner = _box(t)
        drawn = _shown(t, _drawn(t), owner)
        if drawn.isEmpty():
            continue
        name = "the window" if box is None else (what.objectName() or what.metaObject().className())
        box = screen if box is None else box
        past = {"left": box.left() - drawn.left(), "right": drawn.right() - box.right(),
                "top": box.top() - drawn.top(), "bottom": drawn.bottom() - box.bottom()}
        sides = [f"{n} by {v:.0f} px" for n, v in past.items() if v > SLACK]
        if sides:
            text = " ".join(str(t.property("text")).split())
            out.append({"text": text, "line": f"{text[:70]!r} runs past {name}: {', '.join(sides)}"})
    return out
