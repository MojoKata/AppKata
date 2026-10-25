"""Every surface that shows, records or carries a grant set tells apart the sets that run differently,
and shows no difference that doesn't run (review 3, harness 5).

How review 2's F9, F10 and F11 slipped past: each surface was tested on what it does show. The
chips were tested label by label, the Audit for writing an entry, the review lines for parsing, the
Sandbox dialog for the switches it has. None was asked whether it can say everything the grant set
can. A grant set has more dimensions (level, folders and their modes, network, two sounds, two
devices, six services, a writable app folder) than the Audit records (a template name and a
level), than a review can write (a template, folders, network), or than the dialog can make (it
adds a folder read-write only). The class: a surface narrower than the thing it shows.

The harness takes the launcher as the truth (what runs) and makes every one-step change of a
grant set from a bespoke Standard set and from a Strict one. Wherever the launcher changes, each
surface must tell the change apart:

- **the chips**: install card, App Detail and the dialog;
- **the Audit**: what one change records;
- **one review's lines**, parsed by the product;
- **the Sandbox dialog**, driven through its own controls: every enabled switch, the folder picker,
  the remove buttons and the template list.

Wherever the launcher stays the same, the chips must too (round three's R3-2: a Strict set's
folder shown though never bound). A miss still open is listed with the finding that keeps it. Two
faults are re-introduced to show the harness sees them.
"""

import json
import os

import pytest

pytest.importorskip("PySide6")

from appkata_core import sandbox as sb, trustfile                        # noqa: E402
from test_dialog_contract import _call, _dialog, _pick, _prop, qapp, ui   # noqa: E402,F401
from test_sandbox_backend import URL, be                                  # noqa: E402,F401
from test_sandbox_ui_surfaces import _items                              # noqa: E402

APPS = "/home/u/apps"
BASE_FOLDER = "~/Base"

# What each surface can't yet tell apart, and the finding that keeps it so
STILL_MISSING = {
    "the Audit": {},
    # the secrets class: a review can never grant it (the owner's decision on R2-F8), so not a gap
    "a review": {f: "R2-F8" for f in ("saved passwords", "the password service")},
    "your review": {f: "R2-F8" for f in ("saved passwords", "the password service")},
    "the dialog": {},
    "the chips": {},
}


def _with(g: dict, **kw) -> dict:
    return {**g, **kw}


# one-step changes of a grant set; applied raw, as a review or the dialog would hand them over
FLIPS = {
    "Strict instead of Standard": lambda g: _with(g, level="strict"),
    "Standard instead of Strict": lambda g: _with(g, level="standard"),
    "a read-only folder": lambda g: _with(g, folders={**g["folders"], "~/Shared": "ro"}),
    "a read-write folder": lambda g: _with(g, folders={**g["folders"], "~/Shared": "rw"}),
    "the folder read-only instead": lambda g: _with(g, folders={**g["folders"], BASE_FOLDER: "ro"}),
    "no folder": lambda g: _with(g, folders={}),
    "no network": lambda g: _with(g, network=False),
    "the network": lambda g: _with(g, network=True),
    "play sound": lambda g: _with(g, sound=set(g["sound"]) | {"play"}),
    "record sound": lambda g: _with(g, sound=set(g["sound"]) | {"record"}),
    "the camera": lambda g: _with(g, devices=set(g["devices"]) | {"camera"}),
    "no X11 apps": lambda g: _with(g, devices=set(g["devices"]) - {"x11"}),
    "no notifications": lambda g: _with(g, caps=set(g["caps"]) - {"notifications"}),
    "a tray icon": lambda g: _with(g, caps=set(g["caps"]) | {"tray"}),
    "media keys": lambda g: _with(g, caps=set(g["caps"]) | {"mpris"}),
    "keep the screen awake": lambda g: _with(g, caps=set(g["caps"]) | {"inhibit"}),
    "saved passwords": lambda g: _with(g, caps=set(g["caps"]) | {"secrets"}),
    "the password service": lambda g: _with(g, caps=set(g["caps"]) | {"secrets-provide"}),
    "can change its own files": lambda g: _with(g, write_app=True),
    "no execute-deny": lambda g: _with(g, exec_deny=False),          # Landlock: deferred (17.18)
    "limited to ports": lambda g: _with(g, ports=[443]),               # Landlock: deferred (17.18)
}


def _bases() -> dict:
    std = sb.normalize(_with(sb.resolve_template("standard"), folders={BASE_FOLDER: "rw"}))   # bespoke: "custom"
    return {"Standard": std, "Strict": sb.resolve_template("strict")}


def _runs(gs: dict) -> str:
    return sb.build_launcher("demo", "Demo", f"{APPS}/demo/1.0", "bin/app", gs, apps_root=APPS)


def _changes():
    """(base, flip, before, after) for every one-step change that is a change of the grant set."""
    for bname, base in _bases().items():
        for fname, f in FLIPS.items():
            after = f(dict(base))
            if after != base:
                yield bname, fname, base, after


# ------------------------------------------------------------------- the chips, against the launcher

def _chip_misses() -> set[str]:
    out = set()
    for bname, fname, before, after in _changes():
        differs = _runs(before) != _runs(after)
        shown = sb.summary(before, APPS) != sb.summary(after, APPS)
        if differs and not shown:
            out.add(f"{fname}")
        elif shown and not differs:
            out.add(f"{fname} at {bname}: shown, but nothing runs differently")
    return out


def test_the_chips_tell_apart_every_change_that_runs_differently_and_no_other_but_the_listed():
    assert _chip_misses() == set(STILL_MISSING["the chips"])


def test_the_harness_catches_round_threes_strict_folder_shown_but_never_bound(monkeypatch):
    # R3-2 (round three): a Strict set with a folder showed the folder; the launcher never bound it
    chips = sb.summary_chips
    monkeypatch.setattr(sb, "summary_chips", lambda gs, apps_root=None, template=None: chips(
        _with(gs, level="standard", network=False, caps=set(), sound=set()) if gs.get("level") == "strict" and gs.get("folders") else gs, apps_root))
    assert "a read-write folder at Strict: shown, but nothing runs differently" in _chip_misses()


def test_the_harness_catches_a_chip_dropped(monkeypatch):
    chips = sb.summary_chips
    monkeypatch.setattr(sb, "summary_chips", lambda gs, apps_root=None, template=None: [c for c in chips(gs, apps_root)
                                                                          if c[0] != "Can change its own files"])
    assert "can change its own files" in _chip_misses()


# ------------------------------------------------------------------- one review's lines (10.3.1, 17.3)

def _read_back(opts: dict) -> dict | None:
    """Sandbox options written as a review's lines (this platform's), and read back as the reader's
    AppKata reads them: the grant set it applies, or None."""
    text = trustfile.format_settings("Demo", {"platforms": {"LINUX": {k: v for k, v in opts.items() if v is not None}}}, ["- Trust: 4"])
    parsed, _ = trustfile.parse_section("Demo", text + "\n")
    cfg = sb.config_from_review(trustfile.resolve_settings(parsed["opts"], "linux"))
    return sb.strip_secrets(sb.grants_from_config(cfg))[0] if cfg else None     # what the resolver lets a review grant


def _one_review_can_say(after: dict) -> bool:
    """Whether a review's lines can make the app run as `after`: AppKata's own writer puts it into lines
    (as_review, review 2 F9: it was three hand-built lines), and AppKata reads them back."""
    back = _read_back(sb.as_review("custom", after)[0])
    return back is not None and _runs(back) == _runs(after)


def test_one_review_can_say_every_change_that_runs_differently_but_the_listed():
    missing = {fname for bname, fname, before, after in _changes()
               if bname == "Standard" and _runs(before) != _runs(after) and not _one_review_can_say(after)}
    assert missing == set(STILL_MISSING["a review"])


def test_a_review_the_user_writes_carries_their_sandbox_but_the_listed(be, monkeypatch):
    # F9's other half: AppKata read the sandbox lines but never wrote them. Each choice of the user's is
    # put into their review by reviewData, and the reader's AppKata must run what the user runs.
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    missing = set()
    for bname, fname, before, after in _changes():
        if bname != "Standard" or _runs(before) == _runs(after):
            continue
        be.setSandbox(URL, {"custom": sb.to_json(after)})
        written = be.reviewData(URL)["sandboxSettings"]
        back = _read_back(written) if written else None
        if back is None or _runs(back) != _runs(be._resolved_sandbox(URL)["grants"]):
            missing.add(fname)
    assert missing == set(STILL_MISSING["your review"]), sorted(missing)


# ------------------------------------------------------------------- the Audit (17.16)

def test_the_audit_tells_apart_every_change_that_runs_differently_but_the_listed(be, monkeypatch):
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    entries = {}
    for bname, fname, before, after in [c for c in _changes() if c[0] == "Standard"] + [("Standard", "nothing", _bases()["Standard"], _bases()["Standard"])]:
        be.setSandbox(URL, {"custom": sb.to_json(before)})
        be.setSandbox(URL, {"custom": sb.to_json(after)})
        row = be.db.one("SELECT action, detail FROM audit ORDER BY id DESC LIMIT 1")
        if fname == "nothing" or _runs(before) != _runs(after):
            entries[fname] = (row["action"], row["detail"])
    same = {f for f, e in entries.items() if f != "nothing" and list(entries.values()).count(e) > 1}
    assert same == set(STILL_MISSING["the Audit"]), sorted(same)


# ------------------------------------------------------------------- the Sandbox dialog, through its own controls

def _dialog_can_make(ui, be, start: dict) -> list[tuple[str, dict]]:
    """Every grant set one control of the real dialog makes from `start`."""
    from PySide6.QtCore import QMetaObject, QObject, Qt, QUrl
    be.setSandbox(URL, {"custom": sb.to_json(start)})
    dlg = _dialog(ui, "sandbox")
    out = []

    def fresh():
        _call(dlg, "openFor", URL)
        return dlg

    fresh()
    toggles = [o for o in dlg.findChildren(QObject) if o.metaObject().className().startswith("SbxToggle")]
    assert len(toggles) >= 10, "the dialog's switches weren't found"
    for t in toggles:
        if t.property("disabled"):
            continue
        fresh()
        t.toggled.emit(not t.property("on"))
        out.append((f"switch {t.property('label')}", sb.normalize(_prop(dlg, "gs"))))
    fresh()
    picker = dlg.findChild(QObject, "folderPicker")
    for d in ("Shared", "Documents", "Music"):
        os.makedirs(os.path.join(be.locations["home"], d), exist_ok=True)
    QMetaObject.invokeMethod(picker, "open", Qt.ConnectionType.DirectConnection)        # a choice sticks only while open
    picker.setProperty("selectedFolder", QUrl.fromLocalFile(os.path.join(be.locations["home"], "Shared")))
    QMetaObject.invokeMethod(picker, "accept", Qt.ConnectionType.DirectConnection)
    out.append(("Add a folder…", sb.normalize(_prop(dlg, "gs"))))
    # ...and that folder's row then made read-only: how the dialog makes a read-only folder (review 2, F10)
    row = [o for o in _items(dlg) if o.metaObject().className().startswith("TipButton") and o.property("tip") == "Make read-only"]
    for b in row:
        before = sb.normalize(_prop(dlg, "gs"))
        b.clicked.emit()
        if sb.normalize(_prop(dlg, "gs"))["folders"].get("~/Shared") == "ro":
            out.append(("Add a folder…, then Make read-only", sb.normalize(_prop(dlg, "gs"))))
            break
        _call(dlg, "setField", "folders", before["folders"])          # another row's: put it back
    fresh()
    # each folder row's buttons: Remove, and Make read-only / read-write (review 2, F10)
    tips = [o.property("tip") for o in _items(dlg) if o.metaObject().className().startswith("TipButton")
            and o.property("tip") in ("Remove", "Make read-only", "Make read-write")]
    for i, tip in enumerate(tips):
        fresh()
        b = [o for o in _items(dlg) if o.metaObject().className().startswith("TipButton")
             and o.property("tip") in ("Remove", "Make read-only", "Make read-write")][i]
        b.clicked.emit()
        out.append((tip, sb.normalize(_prop(dlg, "gs"))))
    # the user folders in one click (decision 4), as this system names them
    for i, label in enumerate(f["label"] for f in be.sandboxInfo(URL)["userFolders"]):
        fresh()
        b = next(o for o in _items(dlg) if o.metaObject().className().startswith("FButton") and o.property("text") == label)
        b.clicked.emit()
        out.append((label, sb.normalize(_prop(dlg, "gs"))))
    for key in sb.TEMPLATE_ORDER:
        fresh()
        _pick(dlg, "templateSelect", key)
        out.append((f"template {key}", sb.normalize(_prop(dlg, "gs"))))
    return out


def test_the_dialog_can_make_every_change_that_runs_differently_but_the_listed(ui, be, monkeypatch):
    monkeypatch.setattr(be, "_app", lambda url: {"url": URL, "name": "Demo", "installed": ""})
    missing = set()
    for bname in ("Standard",):
        start = _bases()[bname]
        made = {_runs(gs) for _, gs in _dialog_can_make(ui, be, start)}
        missing |= {fname for b, fname, before, after in _changes() if b == bname
                    and _runs(before) != _runs(after) and _runs(after) not in made}
    assert missing == set(STILL_MISSING["the dialog"]), sorted(missing)
