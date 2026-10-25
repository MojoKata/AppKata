"""Properties that must hold for every grant set, not just the ones a finding named (requirement 17).

The point tests in test_sandbox.py pin one bug each; several findings were a *reader* of a grant
set disagreeing with another reader for some set no test had built (round two R9: the chips vs the
launcher on the install root; round three R3-2: the launcher, the chips and the marker at Strict;
round four R4-1: a name the resolver reports that the resolver would not take back). So: a corpus
of every built-in template under every kind of override, Off included, and for each set the
invariants between its readers -- normalize/to_json, the launcher text, the summary chips, the
identity marker, the resolver, the merge rule and the review lines -- checked in one place.
"""

import json
import os
import shlex

import sys

import pytest

from appkata_core import sandbox as sb
from appkata_core import trustfile

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox and its launchers are Linux-only (17.1)")


@pytest.fixture(autouse=True)
def _proxy_here(monkeypatch):
    """The launchers here are for a host with xdg-dbus-proxy, as every launcher tier is; one without
    it has its own tests (review 2, F12)."""
    monkeypatch.setattr(sb, "have_bus_filter", lambda: True)


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    for v in ("XDG_DATA_HOME", "APPKATA_APPS", "APPKATA_DATA"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(sb, "sandboxes_root", lambda: str(tmp_path / "sandboxes"))
    return tmp_path / "home"


# every kind of override a review line or the dialog can apply, alone and all at once
OVERRIDES = {
    "none": {},
    "network on": {"network": True},
    "network off": {"network": False},
    "a folder rw": {"folders": {"+~/Projects": "rw"}},
    "a folder ro": {"folders": {"+~/Media": "ro"}},
    "a refused folder": {"folders": {"+~/.ssh": "rw"}},
    "the home": {"folders": {"+~": "rw"}},
    "a folder under the install root": {"folders": {"+~/Apps/x": "rw"}},          # a custom root (round two, R9)
    "the default install root": {"folders": {"+~/bin/apps": "rw"}},                # unused when the root is custom
    "play": {"sound": ["play"]},
    "play and record": {"sound": ["play", "record"]},
    "camera": {"devices": ["camera", "x11"]},
    "no x11": {"devices": []},
    "every capability": {"caps": sorted(sb.CAP_LABELS)},
    "writable app folder": {"write_app": True},
    "exec allowed": {"exec_deny": False},
    "everything": {"network": True, "folders": {"+~/Projects": "rw", "+~/Media": "ro", "+~/.config": "rw"}, "sound": ["play", "record"],
                   "devices": ["camera", "x11"], "caps": sorted(sb.CAP_LABELS), "write_app": True, "exec_deny": False},
}
CORPUS = [(f"{t} + {o}", sb.apply_overrides(sb.resolve_template(t), ov)) for t in sb.TEMPLATE_ORDER for o, ov in OVERRIDES.items()]
CORPUS.append(("off", sb.resolve_template("off")))
IDS = [c[0] for c in CORPUS]


@pytest.mark.parametrize("gs", [c[1] for c in CORPUS], ids=IDS)
def test_a_grant_set_survives_storage_and_normalizing_is_idempotent(gs):
    n = sb.normalize(gs)
    assert sb.normalize(n) == n
    stored = json.loads(json.dumps(sb.to_json(gs)))                  # what the install record holds
    assert sb.normalize(stored) == n
    assert sb.normalize(sb.grants_from_config({"custom": stored})) == n     # and what the dialog sends back
    assert sb.config_error({"custom": stored}) == ""
    if n["level"] == "strict":                                         # 17.2's table, whatever was asked
        assert n["folders"] == {} and n["network"] is False and n["sound"] == set() and n["caps"] == set()
        assert n["devices"] <= {"x11"} and n["write_app"] is False


@pytest.mark.parametrize("gs", [c[1] for c in CORPUS if sb.level_of(c[1]) != "off"], ids=[i for i, c in zip(IDS, CORPUS) if sb.level_of(c[1]) != "off"])
def test_a_customization_saved_as_any_template_plus_changes_is_the_same_grant_set(gs):
    # Review 2, F10: the dialog saved a customized template as {"custom": ...}, losing its name. It is
    # saved as the template plus overrides now; from whichever template it started, it must resolve
    # to the very set the dialog showed, through storage, and say whether it differs from the template
    n = sb.normalize(gs)
    for t in sb.TEMPLATE_ORDER:
        cfg = json.loads(json.dumps({"template": t, "overrides": sb.as_overrides(t, gs)}))
        assert sb.config_error(cfg) == "" and sb.normalize(sb.grants_from_config(cfg)) == n, t
        assert sb.customized(t, gs) is (n != sb.resolve_template(t)) and (cfg["overrides"] == {}) is not sb.customized(t, gs), t


@pytest.mark.parametrize("gs", [c[1] for c in CORPUS], ids=IDS)
def test_the_launcher_the_chips_and_the_marker_agree_with_the_grant_set(fake_home, gs):
    n = sb.normalize(gs)
    root = str(fake_home / "Apps")                 # a custom install root (Settings → Portable apps), not the default
    chips = sb.summary(gs, root)
    assert len(chips) == len(set(chips))
    if n["level"] == "off":
        assert chips == ["No sandbox"] and not sb.uses_bus(gs)
        return
    text = sb.launcher_text("app", "App", root, f"{root}/app/1", "bin/app", gs)
    strict = n["level"] == "strict"
    # level
    assert ("Strict · private home" in chips) is strict and ("Standard" in chips) is not strict
    assert ("xdg-dbus-proxy" in text) is not strict and "/run/appkata" in text      # the shim at every level (R5-4)
    assert "exec bwrap" not in text and text.rstrip().endswith("exit $status")
    # network
    assert ("--share-net" in text) is n["network"] and ("resolv.conf" in text) is n["network"]
    assert ("Network" in chips) is n["network"] and ("No network" in chips) is not n["network"]
    marker = open(sb.write_flatpak_info("app", network=n["network"] and not strict)).read()
    assert ("shared=network" in marker) is (n["network"] and not strict)
    # folders: granted ones bound as asked, refused ones named and never bound, the chips the same
    for path, mode in n["folders"].items():
        if path == "$cwd":
            assert "share=1" in text and "The folder it's run in" in chips
            continue
        p = shlex.quote(os.path.expanduser(path))
        why = sb.protected_folder(path, root)
        bound = f"{'--bind-try' if mode == 'rw' else '--ro-bind-try'} {p} {p}" in text
        assert bound is not bool(why), path
        assert (f"# Refused folder grant {path}: {why}" in text) is bool(why)
        assert (f"{path} · refused: {why}" in chips) is bool(why)
        assert (path + ("" if mode == "rw" else " · read-only") in chips) is not bool(why)
    # ... and nothing under the real home is bound that was not granted (a literal home path only
    # ever appears in the launcher for a folder grant; the theme and font binds go through $HOME)
    bound = {l.split()[1] for l in text.splitlines() if ("--bind-try " in l or "--ro-bind-try " in l) and str(fake_home) in l}
    assert bound == {shlex.quote(os.path.expanduser(p)) for p in n["folders"] if p != "$cwd" and not sb.protected_folder(p, root)}
    # sound, devices, capabilities, the app folder
    assert ("pipewire-0" in text) is bool(n["sound"])
    assert ("Sound and microphone" in chips) is ("record" in n["sound"])
    assert ("Sound · can also record" in chips) is (bool(n["sound"]) and "record" not in n["sound"])
    assert ("/dev/video" in text) is ("camera" in n["devices"]) and ("Camera" in chips) is ("camera" in n["devices"])
    assert ('[ -n "${DISPLAY:-}" ] && x11=1' in text) is ("x11" in n["devices"])
    for cap, args in sb.CAP_PROXY_ARGS.items():
        assert all((shlex.quote(a) in text) is (cap in n["caps"]) for a in args), cap
        assert (sb._CAP_CHIP[cap][0] in chips) is (cap in n["caps"])
    assert ('--bind "$appdir" "$appdir"' in text) is n["write_app"] and ('--ro-bind "$appdir" "$appdir"' in text) is not n["write_app"]
    assert ("Can change its own files" in chips) is n["write_app"]


def _configs():
    """Every (source, grants, template) the resolver can report, from every way a choice arises."""
    one = [{"template": "online-app", "overrides": {}}]
    two = one + [{"template": "offline-editor", "overrides": {"folders": {"+~/Docs": "ro"}}}]
    default = {"template": "strict", "overrides": {}}
    out = []
    for t in list(sb.TEMPLATE_ORDER) + ["off"]:
        out.append(sb.choose({"template": t, "overrides": {}}, None, [], default))
        out.append(sb.choose({"template": t, "overrides": {"network": True}}, None, [], default))
    custom = sb.to_json(sb.apply_overrides(sb.resolve_template("standard"), {"caps": ["tray"]}))
    out.append(sb.choose({"custom": custom}, None, [], default))
    out.append(sb.choose(None, {"grants": custom, "template": "custom"}, one, default))
    out.append(sb.choose(None, {"grants": sb.to_json(sb.resolve_template("messenger")), "template": "messenger"}, two, default))
    out.append(sb.choose(None, None, one, default))
    out.append(sb.choose(None, None, two, default))
    out.append(sb.choose(None, None, [], default))
    out.append(sb.choose(None, None, [], {"template": "cli-tool", "overrides": {}}, is_cli=True))
    return out


@pytest.mark.parametrize("src,gs,template", _configs(), ids=lambda v: v if isinstance(v, str) else "")
def test_whatever_the_resolver_reports_can_be_sent_back_to_it(src, gs, template):
    # Round four, R4-1: the dialog echoed the reported template name; "custom" is not one.
    assert src in ("user", "pinned", "reviews", "default")
    assert template in sb.TEMPLATES or template in ("off", "custom")
    assert sb.config_error({"custom": sb.to_json(gs)}) == ""              # the set itself: always
    assert sb.normalize(sb.grants_from_config({"custom": sb.to_json(gs)})) == sb.normalize(gs)
    if template == "custom":
        assert sb.config_error({"template": template, "overrides": {}})   # the name alone: never
    else:
        assert sb.config_error({"template": template, "overrides": {}}) == ""
        assert sb.level_of(sb.grants_from_config({"template": template, "overrides": {}})) == sb.level_of(gs) or src == "user"


LEVEL = {"off": 0, "standard": 1, "strict": 2}


@pytest.mark.parametrize("a", [c[1] for c in CORPUS[::3]], ids=IDS[::3])
@pytest.mark.parametrize("b", [c[1] for c in CORPUS[1::5]], ids=IDS[1::5])
def test_merging_never_widens_and_is_symmetric(a, b):
    # 17.3.2: across Trusts the result is least-privilege -- nothing a single review withheld comes
    # back -- and the order of the reviews does not matter. Off adds no limit (c97ef39).
    a, b = sb.normalize(a), sb.normalize(b)
    m = sb.intersect(a, b)
    assert m == sb.intersect(b, a)
    assert sb.intersect(a, a) == a
    if a["level"] == "off":
        assert m == b
        return
    if b["level"] == "off":
        assert m == a
        return
    assert LEVEL[m["level"]] >= max(LEVEL[a["level"]], LEVEL[b["level"]])
    for key in ("sound", "devices", "caps"):
        assert m[key] <= a[key] and m[key] <= b[key]
    assert set(m["folders"]) <= set(a["folders"]) & set(b["folders"])
    for p, mode in m["folders"].items():
        assert mode == "ro" or (a["folders"][p] == "rw" and b["folders"][p] == "rw")
    assert m["network"] <= a["network"] and m["network"] <= b["network"]
    assert m["write_app"] <= a["write_app"] and m["write_app"] <= b["write_app"]
    assert m["exec_deny"] >= a["exec_deny"] and m["exec_deny"] >= b["exec_deny"]


@pytest.mark.parametrize("template", list(sb.TEMPLATE_ORDER) + ["off"])
@pytest.mark.parametrize("folders,network", [("", None), ("+~/Zettlr, ~/Media:ro, -~/Downloads", None), ("", True), ("+~/Docs", False)])
def test_a_review_line_round_trips_to_the_same_grant_set(template, folders, network):
    # 10.3.1 / 17.3: what a reviewer writes is what the reader resolves -- through the trustfile's
    # writer and parser, not just config_from_review on a hand-built dict.
    opts = {"sandbox": template}
    if folders:
        opts["sandboxFolders"] = folders
    if network is not None:
        opts["sandboxNetwork"] = network
    text = trustfile.format_settings("Demo", trustfile.options_to_write({}, "", opts, "linux"))
    parsed, warns = trustfile.parse_section("Demo", text)
    assert not warns, warns
    back = sb.config_from_review(trustfile.resolve_settings(parsed["opts"], "linux"))
    assert back == sb.config_from_review(opts)
    assert sb.normalize(sb.grants_from_config(back)) == sb.normalize(sb.grants_from_config(sb.config_from_review(opts)))
