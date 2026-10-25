"""A text the UI works out from the time of day goes on following it (review 3, R3-29).

How it slipped past: Theme.ago() worked "Synced 50 min ago" out from Date.now(), which a QML
binding doesn't depend on, so the header worked it out once, when the last sync changed, and kept
it: an AppKata left open said "Synced just now" until the next sync. The ⋮ menu works it out each
time it opens, so the regenerated X01 showed "Synced 50 min ago" beside "Last synced 52 min ago".
The tour checks that texts fit their boxes (R3-22) and that two parts of a screen tell the backend's
facts alike (E5); no test let time pass under a screen. The class: a text worked out from the
current time with nothing that makes it be worked out again as time passes. Theme's clock is the
one place QML reads the time; everything else reads Theme.now.
"""

import glob
import os
import re

from test_dialog_contract import qapp  # noqa: F401

QML = os.path.join(os.path.dirname(__file__), "..", "src", "appkata", "qml")
# a read of the current time: Date.now(), or a Date made with no arguments
READ = re.compile(r"\bDate\.now\(\)|\bnew Date\(\s*\)")
# Theme's clock, which keeps Theme.now (the one place the time may be read)
CLOCK = re.compile(r"\bnow\s*[:=]\s*Date\.now\(\)")

# Reads of the time outside the clock still open, by file, and the finding that keeps each
STILL_READS: dict = {}


def _reads() -> set[str]:
    out = set()
    for path in glob.glob(os.path.join(QML, "*.qml")):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = re.sub(r"(^|\s)//.*", "", line)          # a comment reads nothing
                if READ.search(line) and not (name == "Theme.qml" and CLOCK.search(line)):
                    out.add(name)
    return out


def test_only_themes_clock_reads_the_time():
    assert _reads() == set(STILL_READS)


def test_an_ago_text_moves_on_with_the_clock(qapp):
    """The header's binding, "Synced " + Theme.ago(lastSync), is worked out again as the clock
    ticks, with no new sync (on the old Theme it kept its first answer)."""
    from datetime import datetime, timedelta, timezone

    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    engine = QQmlEngine()
    comp = QQmlComponent(engine)
    comp.setData(b'import QtQuick\nimport "../../src/appkata/qml"\n'
                 b'Item { property string iso: ""; readonly property string shown: "Synced " + Theme.ago(iso)\n'
                 b'       function tick(ms) { Theme.now += ms } }',
                 QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "qml", "TimeProbe.qml")))
    item = comp.create()
    assert item is not None, comp.errorString()
    item.setProperty("iso", (datetime.now(timezone.utc) - timedelta(minutes=50, seconds=10)).isoformat())
    assert item.property("shown") == "Synced 50 min ago"
    item.tick(2 * 60_000)
    assert item.property("shown") == "Synced 52 min ago"
    item.tick(3 * 3_600_000)
    assert item.property("shown") == "Synced 4 h ago"
