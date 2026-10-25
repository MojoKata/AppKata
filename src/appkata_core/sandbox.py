"""App sandboxing on Linux (requirement 17).

Limits the harm a portable app or AppImage can do once installed, using **bubblewrap** (`bwrap`) and
**xdg-dbus-proxy** — no root, no daemon, no setuid helper of AppKata's own. This module holds:

- the **grant-set** model and the seven built-in **templates** (17.2, 17.3);
- resolving several Trusts' reviews and the user's choice into one grant set, least-privilege
  (17.3.2, validated as `scripts/sandbox/merge.py`);
- **AppArmor** detection and the one-time pkexec setup where the kernel restricts unprivileged user
  namespaces (17.10);
- generating the per-app **launcher** `~/bin/apps/<app>/run` with the resolved grants baked in, the
  filtered **D-Bus proxy**, the `.flatpak-info` **identity** marker, and sandboxed AppImage
  extraction (17.4–17.9).

The launcher/proxy shape matches `docs/local-proxy-test-plan.md` and the commands validated by
`scripts/sandbox/field-test.sh`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import time

from .platform import OS, data_dir

log = logging.getLogger("appkata.sandbox")

# -------------------------------------------------------------------------- grant-set model (17.2)

LEVELS = ["off", "standard", "strict"]          # strictness order; "off" is least restrictive
LEVEL_LABELS = {"off": "Off", "standard": "Standard", "strict": "Strict"}

# desktop-services capabilities (17.5.1) and devices (17.2.1), for the UI and the proxy mapping
CAP_LABELS = {"notifications": "Notifications", "inhibit": "Screensaver inhibit", "tray": "Tray icon",
              "mpris": "Media keys", "secrets": "Secrets (use)", "secrets-provide": "Secrets (provide)"}
DEVICE_LABELS = {"camera": "Camera", "x11": "X11 apps (XWayland)"}
SOUND_LABELS = {"play": "Play sound", "record": "Record sound"}


def stricter(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def blank_grants(level: str = "standard") -> dict:
    return dict(level=level, folders={}, network=False, ports=None, sound=set(),
                devices=set(), caps=set(), exec_deny=True, write_app=False)


def normalize(gs: dict) -> dict:
    """A grant set with every key present and the set-valued ones as real sets (JSON gives lists).

    Strict means what 17.2's table says -- a private home only, no network, no bus and so no desktop
    services, the install folder read-only -- so at that level the grants that would widen it are
    dropped here, where every reader of a grant set passes: the launcher, the chips, the badge
    comparisons and the identity marker then agree. (Round three, R3-2: a review saying `Sandbox:
    strict` with a `Sandbox folders` line, or a Strict set customized in the dialog, had the folder
    and the sound sockets bound while the chips also showed a network the launcher never gave.)
    The X11 device grant stays: it is about the display, which every level has."""
    out = blank_grants(gs.get("level", "standard"))
    strict = out["level"] == "strict"
    out["folders"] = {} if strict else dict(gs.get("folders") or {})
    out["network"] = False if strict else bool(gs.get("network", False))
    out["ports"] = None if strict else gs.get("ports")
    out["sound"] = set() if strict else set(gs.get("sound") or [])
    out["devices"] = set(gs.get("devices") or []) & ({"x11"} if strict else set(gs.get("devices") or []))
    out["caps"] = set() if strict else set(gs.get("caps") or [])
    out["exec_deny"] = bool(gs.get("exec_deny", True))
    out["write_app"] = False if strict else bool(gs.get("write_app", False))      # writable app folder (17.7.1)
    return out


def to_json(gs: dict) -> dict:
    """A grant set with sets turned into sorted lists, for storing in the install record."""
    gs = normalize(gs)
    return dict(level=gs["level"], folders=gs["folders"], network=gs["network"], ports=gs["ports"],
                sound=sorted(gs["sound"]), devices=sorted(gs["devices"]), caps=sorted(gs["caps"]),
                exec_deny=gs["exec_deny"], write_app=gs["write_app"])


# -------------------------------------------------------------------------- templates (17.3)

# Each built-in template, as a normalized grant set. folders: {path: "ro"|"rw"}; the actual folder a
# template like offline-editor or developer binds is supplied by the user/review as an override (17.3.1).
# devices "x11": on a Wayland session, also give XWayland, for apps that can't use Wayland (17.9) — on
# by default so ordinary apps open; turning it off keeps the app off X11 entirely there.
TEMPLATES: dict[str, dict] = {
    "strict":         dict(level="strict",   folders={},             network=False, ports=None, sound=set(),               devices={"x11"},        caps=set(),                                 exec_deny=True),
    "standard":       dict(level="standard", folders={},             network=True,  ports=None, sound=set(),               devices={"x11"},        caps={"notifications"},                     exec_deny=True),
    "offline-editor": dict(level="standard", folders={},             network=False, ports=None, sound=set(),               devices={"x11"},        caps=set(),                                 exec_deny=True),
    "online-app":     dict(level="standard", folders={},             network=True,  ports=None, sound={"play"},            devices={"x11"},        caps={"notifications"},                     exec_deny=True),
    "messenger":      dict(level="standard", folders={},             network=True,  ports=None, sound={"play", "record"},  devices={"camera", "x11"}, caps={"tray", "notifications", "inhibit"},  exec_deny=True),
    "media-player":   dict(level="standard", folders={},             network=False, ports=None, sound={"play"},            devices={"x11"},        caps={"mpris", "inhibit"},                  exec_deny=True),
    "developer":      dict(level="standard", folders={},             network=True,  ports=None, sound=set(),               devices={"x11"},        caps=set(),                                 exec_deny=False),
    "cli-tool":       dict(level="standard", folders={"$cwd": "rw"}, network=False, ports=None, sound=set(),               devices={"x11"},        caps=set(),                                 exec_deny=False),
}
TEMPLATE_ORDER = ("strict", "standard", "offline-editor", "online-app", "messenger", "media-player", "developer", "cli-tool")

TEMPLATE_LABELS = {"strict": "Strict", "standard": "Standard", "offline-editor": "Offline editor", "online-app": "Online app",
                   "messenger": "Messenger", "media-player": "Media player", "developer": "Developer tool",
                   "cli-tool": "Command-line tool", "off": "Off", "custom": "Custom"}
TEMPLATE_BLURB = {
    "strict": "Private home, no files, no network, no desktop services.",
    "standard": "Network and notifications; private home, no folders of its own.",
    "offline-editor": "Works on a folder you pick (Documents, Pictures…); no network.",
    "online-app": "Network and sound, notifications; no file access beyond its own.",
    "messenger": "Network, camera, microphone, tray and notifications for a chat or call app.",
    "media-player": "Plays a media folder you pick (read-only), keeps the screen awake, media-key controls.",
    "developer": "A projects folder you pick (read-write) and network, for building and running your own code.",
    "cli-tool": "Sees only the directory it's run in; the rest of your home stays hidden.",
    "off": "No sandbox — the app runs with your full account (not recommended).",
    "custom": "Your own mix of access, built from a template.",
}


# The templates made for a folder the user picks (17.3): its mode, and the user folders (XDG names)
# offered in one click for it. They come with none: which folder is the user's to say (review 2, F10:
# the table promised one and the dialog never asked).
FOLDER_TEMPLATES = {"offline-editor": {"mode": "rw", "suggest": ["DOCUMENTS", "PICTURES"]},
                    "media-player": {"mode": "ro", "suggest": ["MUSIC", "VIDEOS"]},
                    "developer": {"mode": "rw", "suggest": []}}
# The user folders the Files group offers in one click (17.2.1), by their XDG names
USER_FOLDERS = ("DOCUMENTS", "DOWNLOAD", "PICTURES", "VIDEOS", "MUSIC")


def resolve_template(name: str) -> dict:
    """A built-in template, or `off`, as a fresh grant set."""
    if name == "off":
        return blank_grants("off")
    return normalize(TEMPLATES[name])


GRANT_KEYS = ("level", "folders", "network", "ports", "sound", "devices", "caps", "exec_deny", "write_app")


def as_overrides(template: str, gs: dict) -> dict:
    """The overrides that make built-in `template` into grant set `gs` (17.3.1): what a customization
    is saved as, so the app keeps its template's name ("Offline editor · customized", Reset to
    template) rather than becoming "Custom" (review 2, F10). Normalized,
    grants_from_config({"template": template, "overrides": as_overrides(template, gs)}) is gs."""
    base, want = resolve_template(template), normalize(gs)
    ov: dict = {}
    for k in GRANT_KEYS:
        if k == "folders":
            f: dict = {f"+{p}": m for p, m in want["folders"].items() if base["folders"].get(p) != m}
            f.update({f"-{p}": None for p in base["folders"] if p not in want["folders"]})
            if f:
                ov["folders"] = f
        elif want[k] != base[k]:
            ov[k] = sorted(want[k]) if isinstance(want[k], set) else want[k]
    return ov


def _closest_template(gs: dict) -> str:
    """The built-in template at `gs`'s level that takes the fewest changes to become it."""
    n = normalize(gs)
    same = [t for t in TEMPLATE_ORDER if TEMPLATES[t]["level"] == n["level"]] or list(TEMPLATE_ORDER)
    return min(same, key=lambda t: sum(len(v) if isinstance(v, (dict, list)) else 1 for v in as_overrides(t, n).values()))


def as_review(template: str, gs: dict) -> tuple[dict, list[tuple[str, str]]]:
    """The user's own sandbox as a review's Settings options (10.3.1; review 2, F9): {"sandbox":
    template, "sandboxFolders": "+~/Notes, -$cwd", ...}, each line only where the set differs from
    the template, and [(what, why)] for what a review can't carry (a secret folder, the keyring).
    A merged or bespoke set ("custom") is written as the closest template at its level. The
    Landlock extras (exec_deny, ports) aren't enforced in v1 (17.18), so they aren't written."""
    n = normalize(gs)
    if n["level"] == "off":
        return {"sandbox": "off"}, []
    kept, refused = strip_secrets(n)
    kept, never = strip_protected(kept)          # never shared, whoever asks (17.3.1)
    refused += never
    if template not in TEMPLATES or TEMPLATES[template]["level"] != kept["level"]:
        template = _closest_template(kept)
    base, ov = resolve_template(template), as_overrides(template, kept)
    out: dict = {"sandbox": template}
    if "folders" in ov:
        out["sandboxFolders"] = ", ".join(
            (f"-{p[1:]}" if p.startswith("-") else f"{p}" + (":ro" if m == "ro" else "")) for p, m in sorted(ov["folders"].items()))
    if "network" in ov:
        out["sandboxNetwork"] = bool(ov["network"])
    for grant, key in (("sound", "sandboxSound"), ("devices", "sandboxDevices"), ("caps", "sandboxServices")):
        if grant in ov:
            words = LINE_WORDS[grant]
            out[key] = ", ".join([f"+{words[x]}" for x in sorted(kept[grant] - base[grant])] +
                                 [f"-{words[x]}" for x in sorted(base[grant] - kept[grant])])
    if "write_app" in ov:
        out["sandboxAppFolder"] = bool(ov["write_app"])
    return out, refused


# how each grant reads in a sentence (the Sandbox dialog, the Audit, the review badge, a review)
_PHRASES = {("sound", "play"): "sound", ("sound", "record"): "recording", ("devices", "camera"): "the camera",
            ("devices", "x11"): "X11 apps", ("caps", "notifications"): "notifications",
            ("caps", "inhibit"): "keeping the screen awake", ("caps", "tray"): "a tray icon", ("caps", "mpris"): "media keys",
            ("caps", "secrets"): "saved passwords", ("caps", "secrets-provide"): "the password service"}


def _folder_phrase(path: str, mode: str) -> str:
    return ("the folder it's run in" if path == "$cwd" else path) + (" (read-write)" if mode == "rw" else " (read-only)")


def changes(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """What `after` adds to and removes from `before`, as phrases: (["~/Notes (read-write)", "the
    network"], ["notifications"]). A folder whose mode changed is added with its new mode. The level
    is each caller's to say (the Audit has a field for it, the badge says it first)."""
    a, b = normalize(before), normalize(after)
    added, removed = [], []
    for p, m in sorted(b["folders"].items()):
        if a["folders"].get(p) != m:
            added.append(_folder_phrase(p, m))
    removed += [_folder_phrase(p, m) for p, m in sorted(a["folders"].items()) if p not in b["folders"]]
    if a["network"] != b["network"]:
        (added if b["network"] else removed).append("the network")
    for grant in ("sound", "devices", "caps"):
        added += [_PHRASES.get((grant, x), x) for x in sorted(b[grant] - a[grant])]
        removed += [_PHRASES.get((grant, x), x) for x in sorted(a[grant] - b[grant])]
    if a["write_app"] != b["write_app"]:
        (added if b["write_app"] else removed).append("changing its own files")
    return added, removed


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def describe(template: str, gs: dict) -> str:
    """A set as its template and the changes: "Standard, without the network and notifications, with
    ~/Shared (read-write)"; the template's name alone when nothing changed (review 2, F9, F10)."""
    if level_of(gs) == "off":
        return TEMPLATE_LABELS["off"]
    if template not in TEMPLATES:
        template = _closest_template(gs)
    added, removed = changes(resolve_template(template), gs)
    out = TEMPLATE_LABELS[template]
    if removed:
        out += ", without " + _and(removed)
    if added:
        out += ", with " + _and(added)
    return out


def suggestion_text(current: dict, suggested: dict, who: str = "A reviewer") -> str:
    """The review badge's words (17.11; review 2's nit: it listed the whole suggestion and never said
    what the difference means): what the suggestion adds and removes, then, with more access, that
    the app may not work fully until reviewed, and with less, that it may have more than it needs."""
    a, b = normalize(current), normalize(suggested)
    if b["level"] == "off":
        return f"{who} suggests running it with no sandbox. Until you review it, the app may not work fully."
    added, removed = changes(a, b)
    clauses = ([f"adding {_and(added)}"] if added else []) + ([f"removing {_and(removed)}"] if removed else [])
    more_level = LEVELS.index(b["level"]) < LEVELS.index(a["level"])
    out = f"{who} suggests"
    if a["level"] != b["level"]:
        out += f" {LEVEL_LABELS[b['level']]} instead of {LEVEL_LABELS[a['level']]}" + ("," if clauses else "")
    if not clauses and a["level"] == b["level"]:
        return ""
    out += (" " + " and ".join(clauses) if clauses else "") + "."
    if added or more_level:
        out += " Until you review it, the app may not work fully."
    if removed or (a["level"] != b["level"] and not more_level):
        out += " The app may have more access than it needs."
    return out


def customized(template: str, gs: dict) -> bool:
    """Whether `gs` differs from the built-in `template` it is named after (a merged or bespoke set,
    "custom", always does)."""
    return template not in TEMPLATES or normalize(gs) != resolve_template(template)


def user_folders(home: str | None = None) -> list[dict]:
    """The user's Documents, Downloads, Pictures, Videos and Music folders, as this system names them
    (`~/.config/user-dirs.dirs`, in the user's language; the English names where it says nothing),
    those that exist and aren't the home itself: [{"key", "label", "path"}], path from `~` (17.2.1)."""
    home = home or os.path.expanduser("~")
    named = {}
    try:
        with open(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "user-dirs.dirs")) as f:
            for line in f:
                m = re.match(r'\s*XDG_([A-Z]+)_DIR\s*=\s*"(.*)"\s*$', line)
                if m:
                    named[m.group(1)] = m.group(2).replace("$HOME", home)
    except OSError:
        pass
    english = {"DOCUMENTS": "Documents", "DOWNLOAD": "Downloads", "PICTURES": "Pictures", "VIDEOS": "Videos", "MUSIC": "Music"}
    out = []
    for key in USER_FOLDERS:
        path = os.path.normpath(named.get(key) or os.path.join(home, english[key]))
        if path != os.path.normpath(home) and os.path.isdir(path):
            nice = "~" + path[len(home):] if path.startswith(home.rstrip("/") + "/") else path
            out.append({"key": key, "label": os.path.basename(path), "path": nice})
    return out


# -------------------------------------------------------------------------- overrides (17.3.1)

def parse_folders(spec: str) -> dict:
    """A `Sandbox folders` value → a folders-override map for :func:`apply_overrides`.

    Comma-separated entries, each a path with an optional `+`/`-` prefix (add to / remove from the
    template's set) and an optional `:ro`/`:rw` suffix (read-only / read-write; read-write by
    default). `- Sandbox folders: +~/Zettlr, ~/Media:ro, -~/Downloads`.
    """
    out: dict = {}
    for raw in (spec or "").split(","):
        entry = raw.strip()
        if not entry:
            continue
        mode = "rw"
        low = entry.lower()
        if low.endswith(":ro"):
            mode, entry = "ro", entry[:-3].strip()
        elif low.endswith(":rw"):
            mode, entry = "rw", entry[:-3].strip()
        if not entry:
            continue
        if entry[0] == "-":
            out[entry] = None           # "-path" removes; mode ignored
        else:
            out[entry] = mode           # "+path" adds, bare path sets
    return out


def apply_overrides(gs: dict, ov: dict) -> dict:
    """Overrides on a resolved grant set. `folders` entries may be `+path`/`-path`/`path` (17.3.1);
    other keys replace outright."""
    gs = normalize(gs)
    for k, v in (ov or {}).items():
        if k == "folders":
            for path, mode in (v or {}).items():
                if path.startswith("+"):
                    gs["folders"][path[1:]] = mode or "rw"
                elif path.startswith("-"):
                    gs["folders"].pop(path[1:], None)
                elif mode is None:
                    gs["folders"].pop(path, None)
                else:
                    gs["folders"][path] = mode
        elif k in ("sound", "devices", "caps"):
            if isinstance(v, dict):          # "+x"/"-x" entries change the template's set (10.3.1, F9)
                cur = set(gs[k])
                for e in v:
                    if e.startswith("+"):
                        cur.add(e[1:])
                    elif e.startswith("-"):
                        cur.discard(e[1:])
                gs[k] = cur
            else:
                gs[k] = set(v or [])
        else:
            gs[k] = v
    return gs


def config_from_review(opts: dict) -> dict | None:
    """A Trust's resolved Settings (10.3.1) → a sandbox config `{"template", "overrides"}`, or None
    when the review says nothing about the sandbox. `off` is a template name here."""
    name = (opts or {}).get("sandbox")
    if not name:
        return None
    name = str(name).lower()
    if name != "off" and name not in TEMPLATES:
        return None
    overrides: dict = {}
    folders = opts.get("sandboxFolders")
    if folders:
        overrides["folders"] = parse_folders(folders)
    if "sandboxNetwork" in opts:
        overrides["network"] = bool(opts["sandboxNetwork"])
    for key, grant in (("sandboxSound", "sound"), ("sandboxDevices", "devices"), ("sandboxServices", "caps")):
        if opts.get(key):
            overrides[grant] = parse_set(grant, opts[key])
    if "sandboxAppFolder" in opts:
        overrides["write_app"] = bool(opts["sandboxAppFolder"])
    return {"template": name, "overrides": overrides}


# The words a review uses for the set-valued grants (10.3.1; review 2, F9), each → the grant. Services
# take the names the dialog shows, and the internal ones too.
LINE_NAMES = {
    "sound": {"play": "play", "record": "record"},
    "devices": {"camera": "camera", "x11": "x11", "xwayland": "x11"},
    "caps": {"notifications": "notifications", "keep-awake": "inhibit", "inhibit": "inhibit", "tray": "tray",
             "media-keys": "mpris", "mpris": "mpris", "passwords": "secrets", "secrets": "secrets",
             "password-service": "secrets-provide", "secrets-provide": "secrets-provide"},
}
# ...and the word each grant is written as
LINE_WORDS = {"sound": {"play": "play", "record": "record"}, "devices": {"camera": "camera", "x11": "x11"},
              "caps": {"notifications": "notifications", "inhibit": "keep-awake", "tray": "tray", "mpris": "media-keys",
                       "secrets": "passwords", "secrets-provide": "password-service"}}


def parse_set(grant: str, spec: str):
    """A `Sandbox sound`/`devices`/`services` value → an override for :func:`apply_overrides`: entries
    with `+`/`-` change the template's set ({"+camera": True, "-x11": True}); plain entries, or `none`,
    replace it ([...]). Unknown words are ignored."""
    names = LINE_NAMES[grant]
    entries = [e.strip().lower() for e in str(spec).split(",") if e.strip()]
    if any(e[0] in "+-" for e in entries):
        return {e[0] + names[e[1:]]: True for e in entries if e[0] in "+-" and e[1:] in names}
    return sorted({names[e] for e in entries if e in names})


def config_error(config: dict | None) -> str:
    """Why a sandbox config can't be resolved, or "" when it can: a template must be a built-in
    name or `off`, and a custom set must be a grant set. "custom" is what :func:`choose` *reports*
    as the template name of a merged or bespoke set; it is not a template to resolve (round four,
    R4-1: the dialog sent it back as one, the lookup raised, and the choice was already saved)."""
    if not config:
        return ""
    if not isinstance(config, dict):
        return "not a sandbox config"
    if config.get("custom") is not None:
        return "" if isinstance(config["custom"], dict) else "the custom grant set is not a grant set"
    name = config.get("template", "strict")
    if name == "off" or name in TEMPLATES:
        return ""
    return f"'{name}' is not a sandbox template"


def grants_from_config(config: dict) -> dict:
    """A sandbox config → a grant set. config: `{"template": name, "overrides": {...}}`, or
    `{"custom": <grant set>}` for a bespoke one, or `{"template": "off"}`. Raises ValueError for a
    config :func:`config_error` refuses; callers that store a config check it first."""
    if not config:
        return resolve_template("strict")
    if why := config_error(config):
        raise ValueError(why)
    if config.get("custom") is not None:
        return normalize(config["custom"])
    gs = resolve_template(config.get("template", "strict"))
    return apply_overrides(gs, config.get("overrides", {}))


# -------------------------------------------------------------------------- protected folders (17.3.1)

def _protected_roots(apps_root: str | None = None) -> list[tuple[str, str]]:
    """(folder, what it holds) for the folders a grant may never share, nor anything inside or above
    them: AppKata's own areas (installed apps, the data folder with the database and every private
    home), the places that make a program start again later, the user's keys, and the session's
    runtime folder (the real, unfiltered session bus lives there)."""
    from .platform import apps_dir
    home = os.path.expanduser("~")
    h = lambda *parts: os.path.join(home, *parts)      # noqa: E731
    roots = [(apps_root or apps_dir(), "AppKata's installed apps"),
             (data_dir(), "AppKata's own data and the apps' private homes"),
             (h(".config", "autostart"), "autostart entries"),
             (h(".config", "autostart-scripts"), "autostart scripts"),
             (h(".config", "systemd"), "systemd user units"),
             (h(".local", "share", "systemd"), "systemd user units"),
             (h(".local", "share", "applications"), "app-menu entries"),
             (h(".local", "share", "dbus-1"), "D-Bus service activation"),
             (h(".local", "share", "flatpak"), "Flatpak's user installation"),
             (h(".local", "bin"), "programs on your PATH"),
             (h(".config", "environment.d"), "your login environment"),
             (h(".pam_environment"), "your login environment"),
             (h(".config", "plasma-workspace"), "KDE's login and logout scripts"),
             # the desktop's own extension and script folders: code there runs inside the shell at
             # the next login, or as the user from a file manager's menu (round four, R4-9)
             (h(".local", "share", "gnome-shell", "extensions"), "GNOME Shell extensions"),
             (h(".local", "share", "kwin", "scripts"), "KWin scripts"),
             (h(".local", "share", "plasma", "plasmoids"), "Plasma widgets"),
             (h(".local", "share", "nautilus", "scripts"), "file-manager scripts"),
             (h(".local", "share", "kservices5"), "file-manager service menus"),
             (h(".local", "share", "kio", "servicemenus"), "file-manager service menus"),
             (h(".mozilla", "native-messaging-hosts"), "programs Firefox extensions may start"),
             # Mint's file manager has the same script and action folders as Nautilus and KDE; Python's
             # user site runs a .pth file in every Python the user starts without -s (round five, R5-2)
             (h(".local", "share", "nemo", "scripts"), "file-manager scripts"),
             (h(".local", "share", "nemo", "actions"), "file-manager actions"),
             (h(".local", "lib"), "programs and Python modules on your own paths"),
             (h(".gitconfig"), "your git configuration (hooks, aliases)"),
             (h(".config", "git"), "your git configuration (hooks, aliases)"),
             (h(".ssh"), "SSH keys"),
             (h(".gnupg"), "GPG keys"),
             (os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "the session's runtime folder")]
    # the files a shell or the session reads at login: a "folder" grant binds a file as readily as
    # a folder, and a line appended to one of these runs as the user at the next login (17.3.1)
    roots += [(h(f), "your shell's startup files") for f in (
        ".bashrc", ".bash_profile", ".bash_login", ".profile", ".bash_logout",
        # what the distributions' default .bashrc sources in turn: Ubuntu's and Mint's ~/.bash_aliases,
        # Fedora's ~/.bashrc.d/* (round five, R5-2)
        ".bash_aliases", ".bashrc.d",
        ".zshrc", ".zprofile", ".zshenv", ".zlogin", ".zlogout", ".config/fish", ".kshrc", ".cshrc", ".tcshrc")]
    roots += [(h(f), "your session's startup files") for f in (".xsessionrc", ".xprofile", ".xinitrc", ".Xresources", ".xsession")]
    # a browser's native-messaging manifests name programs the browser starts, as the user, on an
    # extension's request; Firefox's folder is above, the Chromium family keeps theirs per profile
    # folder under ~/.config (named one by one: the match is on exact roots, not patterns)
    roots += [(h(".config", *parts, "NativeMessagingHosts"), "programs browser extensions may start") for parts in (
        ("chromium",), ("google-chrome",), ("google-chrome-beta",), ("google-chrome-unstable",),
        ("BraveSoftware", "Brave-Browser"), ("microsoft-edge",), ("vivaldi",), ("opera",))]
    return roots


def protected_folder(path: str, apps_root: str | None = None) -> str:
    """Why a folder grant for `path` is refused, or "" when it may be shared (17.3.1): a protected
    folder itself, anything inside one, and anything above one — the home folder and `/` included,
    since sharing a parent shares everything beneath it. Reviews and the Customize picker both go
    through this; the CLI tool's `$cwd` has its own run-time rule (17.3.3)."""
    if path == "$cwd":
        return ""
    # bwrap resolves a bind source from the host's root, realpath() below from AppKata's own working
    # directory: a folder named from neither (`home`, `run/user/1000`, `./x`, an unknown `~user`) would
    # be judged here as one place and bound there as another. Review 2, F1: `Sandbox folders: home`
    # passed as "<cwd>/home" and bound the real /home over the private one.
    if not os.path.isabs(os.path.expanduser(path)):
        return "not a full path (start it with / or ~/)"
    p = os.path.realpath(os.path.expanduser(path))
    home = os.path.realpath(os.path.expanduser("~"))
    if p == home:
        return "your whole home folder"
    if p == "/" or home.startswith(p + os.sep):
        return "everything, your home folder included"
    for root, what in _protected_roots(apps_root):
        r = os.path.realpath(root)
        if p == r or p.startswith(r + os.sep):
            return what
        if r.startswith(p + os.sep):
            return f"a folder above {what}"
    return ""


# -------------------------------------------------------------------------- secrets (17.3.1, review 2 F8)

def _secret_roots() -> list[tuple[str, str]]:
    """(folder, what it holds) for the folders a *review* may not grant, nor anything inside or above
    them: browsers' and mail clients' profiles, other sandboxes' data (Flatpak's and Snap's apps
    keep theirs here, as AppKata's keep theirs in folders already never shared), credentials for
    clouds, forges and registries, and password stores. The user's own picker may grant them, with
    a warning; a review can't (17.3.1). The goals promise "secrets stay private"; the never-shared
    list covered ~/.ssh and ~/.gnupg alone (review 2, F8)."""
    home = os.path.expanduser("~")
    h = lambda *parts: os.path.join(home, *parts)      # noqa: E731
    return [(h(".mozilla", "firefox"), "Firefox's profiles and saved logins"),
            (h(".thunderbird"), "Thunderbird's mail and saved logins"),
            (h(".var", "app"), "other apps' sandboxed data (Flatpak)"),
            (h("snap"), "other apps' sandboxed data (Snap)"),
            (h(".aws"), "cloud credentials"), (h(".azure"), "cloud credentials"), (h(".config", "gcloud"), "cloud credentials"),
            (h(".kube"), "cluster credentials"), (h(".docker"), "registry credentials"),
            (h(".config", "gh"), "your GitHub token"), (h(".git-credentials"), "your git passwords"),
            (h(".netrc"), "saved passwords for servers"), (h(".npmrc"), "registry tokens"), (h(".pypirc"), "registry tokens"),
            (h(".cargo", "credentials.toml"), "registry tokens"), (h(".cargo", "credentials"), "registry tokens"),
            (h(".config", "rclone"), "cloud storage tokens"), (h(".vault-token"), "a Vault token"),
            (h(".password-store"), "your password store"), (h(".local", "share", "keyrings"), "your keyring"),
            (h(".local", "share", "kwalletd"), "your KDE wallet")]


def secret_folder(path: str) -> str:
    """What a folder holds when it is (inside, or above) one of :func:`_secret_roots`, else ""."""
    if path == "$cwd" or not os.path.isabs(os.path.expanduser(path)):
        return ""
    p = os.path.realpath(os.path.expanduser(path))
    for root, what in _secret_roots():
        r = os.path.realpath(root)
        if p == r or p.startswith(r + os.sep):
            return what
        if r.startswith(p + os.sep):
            return f"a folder above {what}"
    return ""


# The capabilities in the secrets class (17.3.1, review 2 F8): what a review can never grant
SECRET_CAPS = {"secrets": ("Saved passwords", "a review can't grant the keyring, which holds every saved password"),
               "secrets-provide": ("Password service", "a review can't make an app the password service")}


def strip_secrets(gs: dict) -> tuple[dict, list[tuple[str, str]]]:
    """A review's grant set without its secret folders and keyring capabilities, and [(what, why)] for
    each dropped (17.3.1)."""
    gs = normalize(gs)
    refused = [(p, f"a review can't grant {why}") for p in sorted(gs["folders"]) if (why := secret_folder(p))]
    for p, _ in refused:
        gs["folders"].pop(p)
    for c in sorted(gs["caps"] & set(SECRET_CAPS)):
        gs["caps"].discard(c)
        refused.append(SECRET_CAPS[c])
    return gs, refused


def refused_chips(refused: list) -> list[list]:
    """Summary chips for folders a review asked for and was refused (:func:`strip_secrets`)."""
    return [[f"{p} · refused: {why}", "ban", "warn"] for p, why in refused or []]


def strip_protected(gs: dict, apps_root: str | None = None) -> tuple[dict, list[tuple[str, str]]]:
    """A grant set without its protected folders, and [(path, why)] for each one dropped."""
    gs = normalize(gs)
    refused = [(p, why) for p in sorted(gs["folders"]) if (why := protected_folder(p, apps_root))]
    for p, _ in refused:
        gs["folders"].pop(p)
    return gs, refused


# -------------------------------------------------------------------------- resolving sources (17.3.2)

def _intersect_ports(ap, bp):
    """Least-privilege port combination. `None` means unrestricted (all ports), so intersecting it
    with a list yields that list (both sides allow those); two lists give their overlap."""
    if ap is None and bp is None:
        return None
    if ap is None:
        return sorted(set(bp))
    if bp is None:
        return sorted(set(ap))
    return sorted(set(ap) & set(bp))


def intersect(a: dict, b: dict) -> dict:
    """The least-privilege combination of two grant sets, across Trusts (17.3.2): strictest level; a
    folder only if both grant it (read-write only if both do); network/sound/devices/caps the
    intersection; execute-deny if either denies.

    `off` means no sandbox — everything allowed — so it adds no limit of its own: off ∩ X is X. (Its
    grant set is empty only because Off has nothing to configure; taking that literally made a review
    saying "off" strip every grant from the other reviewers' choice.)"""
    a, b = normalize(a), normalize(b)
    if a["level"] == "off":
        return b
    if b["level"] == "off":
        return a
    folders = {}
    for p in set(a["folders"]) & set(b["folders"]):
        folders[p] = "rw" if a["folders"][p] == "rw" and b["folders"][p] == "rw" else "ro"
    return dict(
        level=stricter(a["level"], b["level"]),
        folders=folders,
        network=a["network"] and b["network"],
        ports=_intersect_ports(a["ports"], b["ports"]),
        sound=a["sound"] & b["sound"],
        devices=a["devices"] & b["devices"],
        caps=a["caps"] & b["caps"],
        exec_deny=a["exec_deny"] or b["exec_deny"],
        write_app=a["write_app"] and b["write_app"],
    )


def default_template(is_cli: bool, reviewed: bool, unreviewed_default: dict | None = None) -> dict:
    """The default sandbox config by app kind and review state (17.3.3). A reviewed app with no
    `Sandbox` line of its own uses the fixed baseline — `standard` for a GUI app, `cli-tool` for a
    CLI tool. An unreviewed app uses `unreviewed_default` (the user's Settings → Sandbox default for
    the kind, 17.15) when given, else `strict` for a GUI app and `cli-tool` for a CLI tool.

    `unreviewed_default` applies only to unreviewed apps: a user's chosen default never overrides the
    reviewed baseline, matching "Reviewed apps follow their review" in Settings → Sandbox.
    """
    if reviewed:
        return {"template": "cli-tool" if is_cli else "standard", "overrides": {}}
    if unreviewed_default:
        return dict(unreviewed_default)
    return {"template": "cli-tool" if is_cli else "strict", "overrides": {}}


def resolve(reviews: list[dict] | None = None, user: dict | None = None,
            is_cli: bool = False) -> tuple[str, dict]:
    """The grant set that applies and where it came from (17.3.2, 17.11): the user's own choice wins;
    else the merged reviews (least-privilege across Trusts); else the default template by app kind.

    `reviews`: each Trust's sandbox config (from :func:`config_from_review`). `user`: a config the
    user chose, or None.
    """
    if user is not None:
        return ("user", grants_from_config(user))
    reviews = [r for r in (reviews or []) if r]
    if not reviews:
        return ("default", grants_from_config(default_template(is_cli, reviewed=False)))
    gs = grants_from_config(reviews[0])
    for r in reviews[1:]:
        gs = intersect(gs, grants_from_config(r))
    return ("reviews", gs)


def choose(user: dict | None, pinned: dict | None, reviews: list[dict], default: dict,
           is_cli: bool = False) -> tuple[str, dict, str]:
    """Which grant set applies to an app, as (source, grant set, template name) (17.11):

    1. `user` — the config the user chose (install options or App Detail);
    2. `pinned` — the grant set the installed app has been running with (`{"grants", "template"}`).
       Reviews **never** change an installed app's grants on their own: a newer or changed review only
       raises the review badge, and an update keeps the pinned grants, so access is never silently
       widened (decision 5);
    3. `reviews` — each Trust's sandbox config, merged least-privilege (a fresh install);
    4. `default` — the default config by app kind and review state (17.3.3).
    """
    if user is not None:
        return "user", grants_from_config(user), user.get("template", "custom")
    if pinned and pinned.get("grants"):
        return "pinned", normalize(pinned["grants"]), pinned.get("template", "custom")
    reviews = [r for r in reviews if r]
    if reviews:
        _, gs = resolve(reviews=reviews, is_cli=is_cli)
        # A review narrows freely, but never turns the sandbox off by itself: where the merged reviews
        # say Off, the reviewed baseline (`default`) applies and the dialogs offer "Use theirs"
        # (17.3.2; review 2, F8: one Trust's `Sandbox: off` ran a fresh install unsandboxed).
        if gs["level"] != "off":
            return "reviews", gs, (reviews[0].get("template", "custom") if len(reviews) == 1 else "custom")
    return "default", grants_from_config(default), default.get("template", "strict")


# -------------------------------------------------------------------------- UI summaries

# capability/device → (chip label, icon name from the app's icon set) for the summary chips
_CAP_CHIP = {"notifications": ("Notifications", "info"), "inhibit": ("Keep screen awake", "clock"),
             "tray": ("Tray icon", "panel"), "mpris": ("Media keys", "play"),
             "secrets": ("Secrets", "key"), "secrets-provide": ("Password service", "key")}
_DEVICE_CHIP = {"camera": ("Camera", "panel")}


def summary_chips(gs: dict, apps_root: str | None = None, template: str | None = None) -> list[list]:
    """Plain-language chips [label, icon, tone] describing a grant set, for the install card, App
    Detail and the Sandbox dialog (A20/A21/C11). tone is "ok", "warn" or "track". `apps_root`: the
    app's install root, so a refused folder is the same one the launcher refuses (round two, R9: the
    chips checked the default root while the launcher checked the app's, and disagreed under a custom
    install folder). `template`: the template the set is named after; one made for a folder the user
    picks says "No folder yet" until it has one (review 2, F10)."""
    gs = normalize(gs)
    if gs["level"] == "off":
        return [["No sandbox", "ban", "warn"]]
    out = [["Strict · private home", "lock", "ok"] if gs["level"] == "strict" else ["Standard", "shieldCheck", "ok"]]
    if template in FOLDER_TEMPLATES and gs["level"] != "strict" and not any(p != "$cwd" for p in gs["folders"]):
        out.append(["No folder yet", "folder", "warn"])
    for path, mode in sorted(gs["folders"].items()):
        nice = "The folder it's run in" if path == "$cwd" else path
        if why := protected_folder(path, apps_root):     # never shared, whoever asked (17.3.1)
            out.append([f"{nice} · refused: {why}", "ban", "warn"])
            continue
        if secret_folder(path):                          # the user's own grant of a secret (17.3.1): said plainly
            out.append([nice + ("" if mode == "rw" else " · read-only") + " · holds passwords or tokens", "warn", "warn"])
            continue
        out.append([nice + ("" if mode == "rw" else " · read-only"), "folder", "track"])
    out.append(["Network", "globe", "track"] if gs["network"] else ["No network", "ban", "track"])
    # Any sound grant binds the PipeWire/Pulse sockets, and neither stops a client from recording
    # (17.8): play-only is said plainly, not shown as protection it isn't.
    if "record" in gs["sound"]:
        out.append(["Sound and microphone", "play", "track"])
    elif gs["sound"]:
        out.append(["Sound · can also record", "play", "warn"])
    for d in sorted(gs["devices"] - {"x11"}):      # the X11 fallback is the default, not worth a chip...
        lab, ic = _DEVICE_CHIP.get(d, (DEVICE_LABELS.get(d, d.title()), "panel"))
        out.append([lab, ic, "track"])
    if "x11" not in gs["devices"]:                  # ...but turning it off changes what runs (review 3, R3-15)
        out.append(["No XWayland", "ban", "track"])
    for c in sorted(gs["caps"]):
        lab, ic = _CAP_CHIP.get(c, (CAP_LABELS.get(c, c.title()), "gear"))
        out.append([lab, ic, "track"])
    if gs["write_app"]:
        out.append(["Can change its own files", "warn", "warn"])
    return out


def summary(gs: dict, apps_root: str | None = None, template: str | None = None) -> list[str]:
    """The chip labels alone (for comparisons and compact displays)."""
    return [c[0] for c in summary_chips(gs, apps_root, template)]


def level_of(gs: dict) -> str:
    return normalize(gs)["level"]


# -------------------------------------------------------------------------- availability & AppArmor (17.10)

PROFILE_PATH = "/etc/apparmor.d/appkata-sandbox"
# bwrap needs the `userns` carve-out where AppArmor restricts unprivileged user namespaces
# (Ubuntu 24.04 / Mint 22). flags=(unconfined) so the profile only grants, never confines (17.10).
# An AppArmor profile attaches to one executable path, so it names the bwrap that is really installed
# (resolved through symlinks); a profile for /usr/bin/bwrap does nothing for one in /usr/local/bin.
_PROFILE_TEMPLATE = (
    "abi <abi/4.0>,\n"
    "include <tunables/global>\n"
    "profile appkata-sandbox {bwrap} flags=(unconfined) {{\n"
    "  userns,\n"
    "  include if exists <local/appkata-sandbox>\n"
    "}}\n"
)
DEFAULT_BWRAP = "/usr/bin/bwrap"


def bwrap_path() -> str:
    """The bwrap the profile must name: the one on PATH, with symlinks resolved."""
    found = shutil.which("bwrap")
    return os.path.realpath(found) if found else DEFAULT_BWRAP


def profile_text(bwrap: str | None = None) -> str:
    return _PROFILE_TEMPLATE.format(bwrap=bwrap or bwrap_path())


PROFILE_TEXT = profile_text(DEFAULT_BWRAP)       # the common case, as the docs show it
_RESTRICT_FLAG = "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
APPARMOR_DIR = "/etc/apparmor.d"

# A profile header that attaches to a bwrap: `profile NAME /usr/bin/bwrap flags=(...) {`, or the
# attachment alone. Rules inside a profile end with a comma, never with a brace, so a rule naming
# bwrap (glycin's `/{,usr/}bin/bwrap mr,`) doesn't match.
_ATTACH_RE = re.compile(r"^\s*(?:profile\s+\S+\s+)?(\S*bin/bwrap)\s*(?:flags=\([^)]*\)\s*)?\{", re.M)

_userns_cache: bool | None = None
_userns_failed_at = 0.0
# A failed probe is asked again after this long: a timeout once mustn't stand for the session (F16).
PROBE_RETRY_S = 60.0
_nested_cache: bool | None = None


def have_tools() -> bool:
    """Whether this system can sandbox at all: bwrap is all a launcher needs. xdg-dbus-proxy only gives
    a Standard app its filtered session bus, and without it the app still runs sandboxed, with no bus
    (:func:`have_bus_filter`; review 2, F12: a missing proxy left every app, Strict too, unsandboxed)."""
    return bool(shutil.which("bwrap"))


def have_bus_filter() -> bool:
    """Whether xdg-dbus-proxy is here to give a Standard app its filtered session bus (17.5)."""
    return bool(shutil.which("xdg-dbus-proxy"))


# each tool the sandbox uses -> the package that brings it (the same name on apt and dnf)
TOOL_PACKAGES = {"bwrap": "bubblewrap", "xdg-dbus-proxy": "xdg-dbus-proxy"}


def missing_tools() -> list[str]:
    """The packages of the sandbox's tools this system lacks, in TOOL_PACKAGES' order."""
    return [pkg for exe, pkg in TOOL_PACKAGES.items() if not shutil.which(exe)]


def tools_hints(missing: list[str]) -> dict:
    """What Settings → Sandbox ("system") and App Detail say about missing tools (17.10): every
    sandbox needs bubblewrap; a Standard app's desktop services need xdg-dbus-proxy. Each names only
    what is missing, with the command that installs it. "app" is for an app that runs unsandboxed
    for it, "broken" for one that keeps its launcher and so can't start (review 2, F16). Empty when
    nothing is missing."""
    if not missing:
        return {"system": "", "app": "", "broken": ""}
    from .platform import linux_family
    cmd = ("sudo dnf install " if linux_family() == "fedora" else "sudo apt install ") + " ".join(missing)
    if "bubblewrap" in missing:
        what = "bubblewrap isn't installed" if len(missing) == 1 else "bubblewrap and xdg-dbus-proxy aren't installed"
        it = "it" if len(missing) == 1 else "them"
        return {"system": f"{what}, so apps run without a sandbox. Install {it} ({cmd}) and restart AppKata.",
                "app": f"Running unsandboxed: {what}. Install {it} ({cmd}) and restart AppKata to sandbox it.",
                "broken": f"Can't start: {what}, and it runs sandboxed. Install {it} ({cmd}), "
                          "or set its sandbox to Off to run it unsandboxed."}
    services = "notify, open links or files on this computer, or show a tray icon"
    return {"system": f"xdg-dbus-proxy isn't installed, so sandboxed apps get no desktop services: they can't {services}. "
                      f"Install it ({cmd}) and restart AppKata.",
            "app": f"Runs without desktop services: xdg-dbus-proxy isn't installed, so it can't {services}. "
                   f"Install it ({cmd}) and restart AppKata.", "broken": ""}


def userns_restricted() -> bool:
    """Whether this kernel restricts unprivileged user namespaces (the AppArmor case, 17.10)."""
    try:
        with open(_RESTRICT_FLAG) as f:
            return f.read().strip() not in ("", "0")
    except OSError:
        return False


def userns_works(refresh: bool = False) -> bool:
    """A one-off `bwrap --unshare-user` probe: whether bwrap can create a user namespace (17.10). A
    success stands for the session; a failure is asked again once PROBE_RETRY_S have passed, so one
    timeout doesn't stand for it (review 2, F16), while the UI's many reads of it stay cheap."""
    global _userns_cache, _userns_failed_at
    if _userns_cache is not None and not refresh and (_userns_cache or time.monotonic() - _userns_failed_at < PROBE_RETRY_S):
        return _userns_cache
    if OS != "linux" or not shutil.which("bwrap"):
        _userns_cache, _userns_failed_at = False, time.monotonic()
        return False
    try:
        p = subprocess.run(
            ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
             "--symlink", "usr/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev",
             "--unshare-user", "--die-with-parent", "--", "/usr/bin/true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        _userns_cache = p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        _userns_cache = False
    if not _userns_cache:
        _userns_failed_at = time.monotonic()
    return _userns_cache


def nested_userns_works(refresh: bool = False) -> bool:
    """Whether a program *inside* bwrap can make a user namespace of its own -- what Chromium's and
    Electron's own sandbox needs (17.10.2). Ubuntu 25.04 and later confine bwrap's children with
    `unpriv_bwrap`, which denies them that, so there it is False (review 2, F2: shown on 26.04, where
    `unshare --user` inside a generated launcher failed). True wherever bwrap itself can't run, or the
    probe can't be made: nothing to adapt to then."""
    global _nested_cache
    if _nested_cache is not None and not refresh:
        return _nested_cache
    unshare = shutil.which("unshare") or ""
    if not userns_works(refresh) or not unshare.startswith("/usr/"):
        _nested_cache = True
        return True
    try:
        p = subprocess.run(
            ["bwrap", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
             "--symlink", "usr/bin", "/bin", "--proc", "/proc", "--dev", "/dev", "--unshare-user", "--die-with-parent",
             "--", unshare, "--user", "--map-root-user", "/usr/bin/true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        _nested_cache = p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        _nested_cache = True
    return _nested_cache


def other_bwrap_profiles(bwrap: str | None = None) -> list[str]:
    """The AppArmor profiles other than AppKata's that attach to a bwrap, by file name: Ubuntu's own
    `bwrap-userns-restrict` since 25.04 (17.10.2). Two profiles on one path don't combine -- with
    AppKata's loaded beside Ubuntu's, bwrap could create no user namespace at all, live and after a
    reboot (review 2, F2, shown on 26.04) -- so AppKata never installs its own beside one, and removes
    its own when one has arrived (an upgrade). Profiles a `disable/` link switches off don't count."""
    try:
        names = sorted(os.listdir(APPARMOR_DIR))
    except OSError:
        return []
    try:
        disabled = set(os.listdir(os.path.join(APPARMOR_DIR, "disable")))
    except OSError:
        disabled = set()
    mine = os.path.basename(PROFILE_PATH)
    out = []
    for name in names:
        f = os.path.join(APPARMOR_DIR, name)
        if name == mine or name in disabled or not os.path.isfile(f):
            continue
        try:
            with open(f, errors="replace") as fh:
                text = fh.read(1 << 20)
        except OSError:
            continue
        if _ATTACH_RE.search(text):
            out.append(name)
    return out


def support_status() -> dict:
    """System support for sandboxing, for Settings → Sandbox (17.15) and the per-app indicator.

    status: "ok" (works), "setup-needed" (restricted and the probe fails — needs the profile),
    "conflict" (AppKata's profile sits beside the system's own bwrap profile, as after an upgrade to
    Ubuntu 25.04+, and bwrap can't start: it needs removing, 17.10.2), "unsupported" (no bwrap),
    "n/a" (not Linux). `innerSandbox`: whether an app's own sandbox (Chromium, Electron) can run
    inside AppKata's here (17.10.2). `busFilter`: whether xdg-dbus-proxy is here; `missing` and
    `toolsHint`/`appToolsHint`/`brokenHint`: the tools that aren't, and what the UI says of them
    (review 2, F12, F16)."""
    if OS != "linux":
        return {"status": "n/a", "tools": False, "restricted": False, "busFilter": False, "missing": [],
                "toolsHint": "", "appToolsHint": "", "brokenHint": ""}
    tools = have_tools()
    works = userns_works()
    missing = missing_tools()
    hints = tools_hints(missing)
    base = {"tools": tools, "restricted": userns_restricted(), "profile": is_profile_installed(),
            "otherProfiles": other_bwrap_profiles(), "busFilter": have_bus_filter(), "missing": missing,
            "toolsHint": hints["system"], "appToolsHint": hints["app"], "brokenHint": hints["broken"]}
    if not tools:
        return {**base, "status": "unsupported"}
    if base["profile"] and base["otherProfiles"]:
        return {**base, "status": "conflict"}
    if works:
        return {**base, "status": "ok", "innerSandbox": nested_userns_works()}
    return {**base, "status": "setup-needed"}


def is_profile_installed() -> bool:
    return os.path.exists(PROFILE_PATH)


# The Wayland compositor known to withhold screen capture, the clipboard and input injection from an
# ordinary client: GNOME's mutter (17.9; shown in the session image, nothing of the kind advertised).
# KDE's kwin hides screencast and fake input from untrusted clients but offers zwlr_data_control --
# the clipboard -- to every client (round seven, R7-1: kwin 5.27, a sandboxed app read what the user
# had copied), so a KDE session gets its own warning. Every other Wayland session gets the full one:
# the wlroots family was confirmed to leak (round 2), and a compositor this code has never heard of is
# not assumed safe. Round five, R5-1: this was a list of seven wlroots names, so sway started from a TTY
# (which sets no XDG_CURRENT_DESKTOP) and any compositor outside the list were reported as clear.
_CLEAR = ("gnome",)
_WLROOTS = ("sway", "hyprland", "wlroots", "river", "wayfire", "labwc", "niri")      # named in the wording


def given_display(env=None) -> str:
    """The display the launcher gives an app in this environment (17.9): "wayland" when
    $WAYLAND_DISPLAY names a socket in the runtime folder -- the launcher's own test, `[ -e
    "$rt/$WAYLAND_DISPLAY" ]` -- else "x11" when $DISPLAY is set, else "". The warning asks this, not
    $XDG_SESSION_TYPE: a compositor started from a console keeps logind's "tty" there, and sway sets
    only WAYLAND_DISPLAY, DISPLAY and SWAYSOCK (review 3, R3-13: sway from a TTY got no warning)."""
    env = os.environ if env is None else env
    wd = env.get("WAYLAND_DISPLAY", "")
    rt = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if wd and os.path.exists(rt + "/" + wd):
        return "wayland"
    return "x11" if env.get("DISPLAY") else ""


# The Wayland globals that let an ordinary client capture the screen, read and change the clipboard,
# or inject input (17.9). A compositor that offers one leaks it, whatever the desktop's name says:
# Budgie's and Phosh's sessions list GNOME but run wlroots compositors (review 2, F7).
LEAKING_GLOBALS = {
    "zwlr_screencopy_manager_v1": "capture", "ext_image_copy_capture_manager_v1": "capture",
    "zwlr_data_control_manager_v1": "clipboard", "ext_data_control_manager_v1": "clipboard",
    "zwp_virtual_keyboard_manager_v1": "input", "zwlr_virtual_pointer_manager_v1": "input",
    "org_kde_kwin_fake_input": "input",
}


def compositor_globals(env=None, timeout: float = 2.0) -> set[str] | None:
    """The interfaces the Wayland compositor offers an ordinary client, from one registry round trip
    on the socket the launcher binds (17.9; review 2, F7: the desktop's name was used instead). None
    when there's no Wayland socket or it doesn't answer. AppKata asks as an ordinary client itself,
    which is what a sandboxed app is to the compositor until the security-context protocol (17.18)."""
    import socket as _socket
    import struct
    env = os.environ if env is None else env
    wd = env.get("WAYLAND_DISPLAY", "")
    path = (env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") + "/" + wd
    if not wd or not os.path.exists(path):
        return None
    try:
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as c:
            c.settimeout(timeout)
            c.connect(path)
            # wl_display (object 1): get_registry (opcode 1, new id 2), then sync (opcode 0, new id 3)
            c.sendall(struct.pack("=IIIIII", 1, (12 << 16) | 1, 2, 1, (12 << 16) | 0, 3))
            buf, names = b"", set()
            while True:
                chunk = c.recv(65536)
                if not chunk:
                    return None
                buf += chunk
                while len(buf) >= 8:
                    obj, word = struct.unpack_from("=II", buf)
                    size, op = word >> 16, word & 0xFFFF
                    if size < 8:
                        return None
                    if len(buf) < size:
                        break
                    msg, buf = buf[8:size], buf[size:]
                    if obj == 2 and op == 0:          # wl_registry.global(name, interface, version)
                        n = struct.unpack_from("=I", msg, 4)[0]
                        names.add(msg[8:8 + n - 1].decode(errors="replace"))
                    elif obj == 3 and op == 0:        # wl_callback.done: every global has been sent
                        return names
                    elif obj == 1 and op == 0:        # wl_display.error
                        return None
    except (OSError, struct.error):
        return None


def compositor_leaks(env=None) -> set[str] | None:
    """Which of capture, clipboard and input the compositor's globals leak; None when unread."""
    names = compositor_globals(env)
    return None if names is None else {LEAKING_GLOBALS[n] for n in names if n in LEAKING_GLOBALS}


X11_WARNING = {"session": "x11",
               "text": "On X11 the sandbox protects your files, but an app can still capture the screen, read the "
                       "clipboard and send keystrokes to other windows. Log into a GNOME Wayland session to close "
                       "this (KDE's closes all but the clipboard), or accept it per app."}


def session_warning() -> dict:
    """The display-leak warning for the display a sandboxed app is given (17.9): on X11, and on any
    Wayland compositor other than GNOME/mutter, a sandboxed app can still screenshot, read the
    clipboard and inject input; on KDE the clipboard alone. The desktop's name gives the verdict;
    the compositor's globals can only add to it, never clear one (review 2, F7: Budgie:GNOME and
    Phosh:GNOME, wlroots compositors, were cleared by name). Returns {} when there's nothing to warn
    about: GNOME Wayland whose compositor offers nothing that leaks, or no display at all."""
    if OS != "linux":
        return {}
    given = given_display()
    desk = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if given == "wayland":
        name = desk.split(":")[0] if desk else ""
        leaks = compositor_leaks() or set()
        gnome, kde = any(c in desk for c in _CLEAR), "kde" in desk
        if gnome and not leaks:
            return {}
        if kde and not leaks - {"clipboard"}:
            return {"session": "wayland", "compositor": name, "leak": "clipboard",
                    "text": "On KDE the sandbox protects your files, the screen and your keystrokes, but an app "
                            "can still read and change the clipboard (KWin offers the clipboard-manager protocol "
                            "to every program). The fix (the Wayland security-context protocol) comes later."}
        if gnome and leaks == {"clipboard"}:
            return {"session": "wayland", "compositor": name, "leak": "clipboard",
                    "text": f"On {name} the sandbox protects your files, the screen and your keystrokes, but an app "
                            "can still read and change the clipboard (its compositor offers the clipboard-manager "
                            "protocol to every program). The fix (the Wayland security-context protocol) comes later."}
        where = (f"On {name} (a wlroots compositor)" if any(c in desk for c in _WLROOTS)
                 else f"On {name}" if name else "On this Wayland compositor")
        return {"session": "wayland", "compositor": name,
                "text": f"{where} the sandbox protects your files, but an app can still capture the "
                        "screen, read the clipboard and send keystrokes to other windows: only GNOME is "
                        "known to block all three. The fix (the Wayland security-context protocol) "
                        "comes later."}
    if given == "x11":
        return dict(X11_WARNING)
    return {}


def bus_warning() -> dict:
    """The abstract session-bus warning (17.9; review 3, R3-8), or {} when there's nothing to say.
    The network grant shares the host's network namespace, and an abstract-namespace socket belongs
    to it: where dbus is 1.12 (Mint 21.3, Ubuntu 22.04, RHEL 9), a session bus started with
    dbus-run-session or dbus-launch is one, and an app with the network grant reaches it directly,
    past the filtering proxy (17.5). A desktop's own login uses systemd's user bus, a path."""
    if OS != "linux":
        return {}
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not any(a.strip().startswith("unix:abstract=") for a in addr.split(";")):
        return {}
    return {"text": "This session's bus listens on an abstract socket, which an app with network access can reach "
                    "directly: for such apps the bus filter doesn't hold. A session started by the desktop's own login "
                    "doesn't have this (it comes from dbus-run-session or dbus-launch); until then, keep apps you don't "
                    "trust offline."}


def _bwrap_probe_words(bwrap: str) -> str:
    """The userns_works() probe as shell words, for the setup script to run as the user."""
    return " ".join(shlex.quote(w) for w in [
        bwrap, "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc", "--dev", "/dev", "--unshare-user", "--die-with-parent", "--", "/usr/bin/true"])


def setup_script(bwrap: str | None = None) -> str:
    """What the one-time setup runs as root behind pkexec (17.10): write and load the profile, then
    run the bwrap probe *as the user who asked* (pkexec sets PKEXEC_UID) -- loading a profile is not
    the goal, bwrap working for the user is. If it doesn't, the profile is unloaded and removed in the
    same run, so a failed setup leaves nothing behind (review 2, F2: on Ubuntu 26.04 a profile loaded
    beside Ubuntu's own left bwrap unable to start for anyone, and it stayed, across reboots)."""
    bwrap = bwrap or bwrap_path()
    p = shlex.quote(PROFILE_PATH)
    return (
        "set -e\n"
        f"cat > {p} <<'AAEOF'\n{profile_text(bwrap)}AAEOF\n"
        f"apparmor_parser -r {p}\n"
        'if [ -n "${PKEXEC_UID:-}" ] && command -v setpriv >/dev/null 2>&1; then\n'
        '  gid=$(getent passwd "$PKEXEC_UID" | cut -d: -f4)\n'
        f'  if ! setpriv --reuid="$PKEXEC_UID" --regid="${{gid:-$PKEXEC_UID}}" --clear-groups -- {_bwrap_probe_words(bwrap)} >/dev/null 2>&1; then\n'
        f"    apparmor_parser -R {p} >/dev/null 2>&1 || true\n"
        f"    rm -f {p}\n"
        '    echo "the profile loaded, but bwrap still couldn\'t create a user namespace for you, so it was removed again" >&2\n'
        "    exit 3\n"
        "  fi\n"
        "fi\n")


def _run_privileged(script: str, what: str) -> None:
    if not shutil.which("pkexec"):
        raise SandboxError("pkexec isn't available to ask for administrator rights")
    try:
        p = subprocess.run(["pkexec", "/bin/sh", "-c", script], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise SandboxError(f"couldn't run the {what}: {e}") from None
    if p.returncode == 126:
        raise SandboxError("the administrator prompt was dismissed")      # pkexec: not authorized / cancelled
    if p.returncode == 127:
        raise SandboxError("pkexec isn't available to ask for administrator rights")
    if p.returncode != 0:
        raise SandboxError((p.stderr or p.stdout or f"the {what} failed").strip().splitlines()[-1])


def install_profile() -> bool:
    """Write and load the AppArmor profile behind a single pkexec prompt (17.10). Returns True on
    success. Raises SandboxError on failure (declined, no pkexec, parser error, the user's bwrap
    still refused -- then nothing is left installed), and refuses outright where the system has its
    own profile for bwrap (Ubuntu 25.04+, 17.10.2): AppKata's beside it would break bwrap."""
    if OS != "linux":
        raise SandboxError("AppArmor setup is only needed on Linux")
    if others := other_bwrap_profiles():
        raise SandboxError(f"this system has its own AppArmor profile for bwrap ({', '.join(others)}); "
                           "AppKata's beside it would stop bwrap working, so it isn't installed")
    _run_privileged(setup_script(), "AppArmor setup")
    # The script checked as the user; check again from here, in case this process differs.
    if not userns_works(refresh=True):
        raise SandboxError("the AppArmor profile loaded, but bwrap still can't create a user namespace here")
    nested_userns_works(refresh=True)
    return True


def remove_profile() -> bool:
    """Unload and delete AppKata's AppArmor profile behind a single pkexec prompt: the repair for
    status "conflict", AppKata's profile left beside the system's own after an upgrade (17.10.2)."""
    if OS != "linux":
        raise SandboxError("AppArmor setup is only needed on Linux")
    p = shlex.quote(PROFILE_PATH)
    _run_privileged(f"apparmor_parser -R {p} >/dev/null 2>&1 || true\nrm -f {p}\n", "AppArmor repair")
    userns_works(refresh=True)
    nested_userns_works(refresh=True)
    return True


class SandboxError(Exception):
    pass


# -------------------------------------------------------------------------- identity & homes (17.6, 17.14)

def sandboxes_root() -> str:
    return os.path.join(data_dir(), "sandboxes")


def sandbox_home(app_id: str) -> str:
    """The app's private home, mounted over $HOME (17.4)."""
    return os.path.join(sandboxes_root(), app_id)


def runs_sandboxed(rec: dict) -> bool:
    """Whether an installed app runs sandboxed: its install record names a launcher, and the
    launcher is there (17.4). App Detail and the Apps list's 17.12 rule ask it through
    Backend._runs_sandboxed (review 3, R3-27: one read the file, the other only the record)."""
    lp = (rec or {}).get("launcher")
    return bool(lp and os.path.exists(lp))


def app_identity(app_id: str) -> str:
    """The app's stable identity, `io.appkata.<app>` (17.6). It is also a D-Bus well-known name
    (`--own`) and the document portal's `by-app/<id>` folder, and a bus-name element may not start
    with a digit: xdg-dbus-proxy refuses `--own=io.appkata.7zip` and exits, leaving the app no bus
    at all. Such a slug gets a leading underscore (`io.appkata._7zip`); hyphens are accepted by both."""
    return f"io.appkata.{'_' if app_id[:1].isdigit() else ''}{app_id}"


def identity_path(app_id: str) -> str:
    """Where the app's `.flatpak-info` marker lives on the host. Deliberately *outside* its private home:
    the app can write anything in its home, so a marker there could be swapped for a symlink to a
    host file (bwrap resolves bind sources on the host side, so that file would be bound read-only at
    /.flatpak-info for the app to read, and the next regeneration would overwrite it). The sandbox
    never sees this folder."""
    return os.path.join(sandboxes_root(), ".identity", app_id)


def write_flatpak_info(app_id: str, network: bool = False) -> str:
    """The `.flatpak-info` identity marker (17.6), written at launcher generation and bound in the
    *app's* root only. PipeWire/WirePlumber read it there (the app is a sandboxed client, 17.8), and
    GLib reads it to use the portals and -- from `[Context] shared=network` -- to report the network
    as available, so `network` says whether the app has it. The portals never see it: they look at
    the bus proxy's root, which has no marker, so the app is a host caller to them (17.6.1).

    Written to a temporary file and renamed over the target, so a symlink at the target is replaced
    rather than followed. A marker left in the private home by an older AppKata is removed (unlinked,
    never followed)."""
    os.makedirs(sandbox_home(app_id), exist_ok=True)
    legacy = os.path.join(sandbox_home(app_id), ".flatpak-info")
    if os.path.lexists(legacy):
        os.unlink(legacy)
    path = identity_path(app_id)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(flatpak_info_text(app_id, network))
    os.replace(tmp, path)
    return path


def flatpak_info_text(app_id: str, network: bool = False) -> str:
    """The identity marker's text (:func:`write_flatpak_info`)."""
    return (f"[Application]\nname={app_identity(app_id)}\n\n"
            f"[Instance]\ninstance-id={app_id}\n"
            + ("\n[Context]\nshared=network;\n" if network else ""))


def remove_identity(app_id: str) -> None:
    """Remove the app's identity marker: it belongs with the launcher, not with the private home, so
    an uninstall that keeps the home (17.14) leaves nothing behind in `.identity/` (round two, R10)."""
    if os.path.lexists(identity_path(app_id)):
        os.unlink(identity_path(app_id))


def home_owner_path(app_id: str) -> str:
    """Where AppKata records which app (its URL) a private home belongs to: beside the homes, never
    inside one, so no sandbox sees or writes it."""
    return os.path.join(sandboxes_root(), ".owners", app_id)


def record_home_owner(app_id: str, url: str) -> None:
    """Say that the private home of `app_id` belongs to the app at `url` (17.6). It outlives the
    install when an uninstall keeps the home (17.14), so a later app with the same name can tell the
    home is not its own (review 2, F19)."""
    path = home_owner_path(app_id)
    try:
        with open(path) as f:
            if f.read().strip() == url:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(url + "\n")
    os.replace(tmp, path)


def home_belongs_to_another(app_id: str, url: str) -> bool:
    """Whether a private home already exists for `app_id` and isn't the app at `url`'s: a home an
    uninstall kept, of an app with the same name from another Source. A home with no owner recorded
    (made before owners were) counts as another's -- the safe direction: the worst case is a
    reinstalled app starting with a fresh home under a new id, never an app reading another's."""
    if not os.path.isdir(sandbox_home(app_id)):
        return False
    try:
        with open(home_owner_path(app_id)) as f:
            return f.read().strip() != url
    except OSError:
        return True


def remove_sandbox_home(app_id: str) -> None:
    """Remove the app's private home on uninstall (17.14), its identity marker and its owner record."""
    shutil.rmtree(sandbox_home(app_id), ignore_errors=True)
    remove_identity(app_id)
    if os.path.lexists(home_owner_path(app_id)):
        os.unlink(home_owner_path(app_id))


# -------------------------------------------------------------------------- D-Bus proxy (17.5)

# A tray icon's bus name is org.kde.StatusNotifierItem-<pid>-<n>. xdg-dbus-proxy only accepts a
# trailing `.*` as a wildcard (`StatusNotifierItem-*` is rejected as an invalid name and the proxy
# exits), so own the exact names an app gets in bwrap's pid namespace: the app is pid 2 (as in
# Flatpak) when exec'd straight, 3 when its AppRun runs it as a child -- and higher for every
# process the AppRun forked before that (a command substitution is one: round six, R6-3, shown with
# a watcher stand-in; the item then had pid 4 and no owned name). Pids 2..6 cover an AppRun that
# forks a few times; n counts icons.
_TRAY_OWNS = [f"--own=org.kde.StatusNotifierItem-{pid}-{n}" for pid in (2, 3, 4, 5, 6) for n in (1, 2, 3)]

_PORTAL = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"


def _portal_call(interface: str, obj: str = _PORTAL_PATH) -> str:
    return f"--call={_PORTAL}=org.freedesktop.portal.{interface}.*@{obj}"


# capability → the extra xdg-dbus-proxy arguments it adds (local-proxy-test-plan.md). Where a portal
# covers the need, the capability opens *both* roads -- the portal interface, which GLib/GTK apps
# take when they see /.flatpak-info, and the direct name the others use -- so the capability is the
# one switch, and an app without it has neither (round three, R3-6: the Notification and Inhibit
# portals were open to every Standard app, so an offline-editor with no "Notifications" chip still
# notified through GLib). Wildcard owns use xdg-dbus-proxy's `.*` suffix (names below a prefix).
CAP_PROXY_ARGS = {
    "notifications": [_portal_call("Notification"), "--talk=org.freedesktop.Notifications"],
    "inhibit": [_portal_call("Inhibit"), "--talk=org.freedesktop.ScreenSaver"],
    "tray": ["--talk=org.kde.StatusNotifierWatcher", *_TRAY_OWNS],
    "mpris": ["--own=org.mpris.MediaPlayer2.*"],
    "secrets": ["--talk=org.freedesktop.secrets"],
    "secrets-provide": ["--own=org.freedesktop.secrets"],
}

# The portal interfaces a sandboxed app may call (17.5). The portals see the app as a *host* caller
# (the proxy's root carries no .flatpak-info, 17.6.1), and some portals trust a host caller with
# things a sandbox must not get: Background writes the caller's command into ~/.config/autostart,
# DynamicLauncher installs desktop entries, Camera/ScreenCast/RemoteDesktop/Screenshot/Location
# hand over devices and sessions without the sandbox's consent, Documents could export and share
# files, Realtime acts on any of the user's threads, Account reads the user's name and avatar.
# FileChooser is left out too: for a host caller it returns real paths the sandbox cannot open, so
# the app's own dialog is used instead, showing exactly what the sandbox sees (17.6.3). What
# remains acts on the caller's behalf only, with the user in the loop where it matters, and is what
# a Flatpak app gets too -- except Notification and Inhibit, which come with their capabilities
# (CAP_PROXY_ARGS), so the summary's "Notifications" and "Keep screen awake" chips are the truth.
# Properties (version probes) are not allowed either. What keeps each toolkit on its own file
# dialog, as shown with real apps behind generated launchers (scripts/test-sandbox.sh filedialogs,
# round four R4-5): GTK3 and Qt up to 6.4 never ask -- they take $XDG_RUNTIME_DIR/flatpak-info or
# GTK_USE_PORTAL as the sign of a sandbox, neither of which the launcher provides; GTK4 and Qt 6.5+
# read /.flatpak-info and do ask -- Qt keeps its own dialog whatever the proxy answers (6.8), GTK
# 4.14 fell back to its own when OpenFile was refused but GTK 4.18 shows none (round six, R6-4),
# so the launcher sets GDK_DEBUG=no-portals and GTK4 never asks.
# Chromium/Electron reads `version` first and cancels its dialog when OpenFile then fails, so for it
# the Properties denial is the one that matters -- keep both denied; nothing here needs `version`.
PORTAL_INTERFACES = ("OpenURI", "Settings", "Print", "Email", "NetworkMonitor", "ProxyResolver", "MemoryMonitor")
# the broadcast signals those interfaces emit (replies and the Request/Session signals, which are
# sent to the caller alone, always pass the proxy)
PORTAL_SIGNALS = ("Settings.SettingChanged", "NetworkMonitor.changed", "MemoryMonitor.LowMemoryWarning")


def portal_rules() -> list[str]:
    """xdg-dbus-proxy `--call`/`--broadcast` rules for the Desktop portal: the interfaces above on
    the portal object, plus Request and Session objects (cancel, close), nothing else on that name."""
    rules = [_portal_call(i) for i in PORTAL_INTERFACES]
    rules += [_portal_call("Request", f"{_PORTAL_PATH}/request/*"), _portal_call("Session", f"{_PORTAL_PATH}/session/*"),
              # the interface listing: `gdbus call` (xdg-open and the shim) types its arguments from it
              f"--call={_PORTAL}=org.freedesktop.DBus.Introspectable.*@{_PORTAL_PATH}"]
    rules += [f"--broadcast={_PORTAL}=org.freedesktop.portal.{s}@{_PORTAL_PATH}" for s in PORTAL_SIGNALS]
    return rules


# The portals IBus and Fcitx provide for sandboxed apps: with them an app's input method works
# inside (review 2, F15; review 3, R3-18 -- the owner's decision, shown with real IBus in the
# `inputmethod` harness)
INPUT_METHOD_PORTALS = ("org.freedesktop.portal.IBus", "org.freedesktop.portal.Fcitx")


def proxy_args(gs: dict, app_id: str) -> list[str]:
    """The xdg-dbus-proxy filter arguments for a grant set: the safe part of the Desktop portal, the
    input-method portals and the app's own name, plus each granted capability (17.5, 17.5.1)."""
    args = ["--filter", *portal_rules(), *[f"--talk={n}" for n in INPUT_METHOD_PORTALS], f"--own={app_identity(app_id)}"]
    for cap in sorted(normalize(gs)["caps"]):
        args += CAP_PROXY_ARGS.get(cap, [])
    return args


def uses_bus(gs: dict) -> bool:
    """Whether the level uses the session bus (Standard does; Strict adds no bus proxy, 17.4)."""
    return normalize(gs)["level"] == "standard"


# -------------------------------------------------------------------------- terminal injection (17.4)

# A classic-BPF seccomp filter, handed to bwrap with --seccomp, that refuses the two ioctls a sandboxed
# program could use to type into the user's terminal (CVE-2017-5226): TIOCSTI (push input) and
# TIOCLINUX (its console cousin). This replaces bwrap's --new-session, which also guards against it but
# detaches the program from its terminal -- no /dev/tty, no resize or job-control signals -- breaking
# terminal tools. Flatpak does the same. Only the low 32 bits of the request are compared: the kernel's
# ioctl takes an unsigned int, so that is what it acts on. Each ABI a process can make syscalls through
# is covered (x86-64 incl. x32, i386 via int 0x80; aarch64, arm compat); others are allowed through, and
# the launcher falls back to --new-session on a machine whose native ABI isn't listed.
_TIOCSTI, _TIOCLINUX = 0x5412, 0x541C
_AUDIT_ARCH = {"x86_64": 0xC000003E, "i386": 0x40000003, "aarch64": 0xC00000B7, "arm": 0x40000028}
_IOCTL_NR = {"x86_64": (16, 0x40000000 | 514), "i386": (54,), "aarch64": (29,), "arm": (54,)}
_NATIVE = {"x86_64": ("x86_64", "i386"), "aarch64": ("aarch64", "arm")}


def seccomp_filter(machine: str | None = None) -> bytes | None:
    """The compiled filter for this machine's ABIs, or None where none is defined."""
    import struct
    machine = machine or os.uname().machine
    abis = _NATIVE.get(machine)
    if not abis:
        return None
    LD_W_ABS, JEQ, RET = 0x20, 0x15, 0x06
    ALLOW, DENY = 0x7FFF0000, 0x00050000 | 1            # SECCOMP_RET_ALLOW, SECCOMP_RET_ERRNO|EPERM
    prog: list = []                                      # (code, jt label|int, jf label|int, k), labels resolved below
    labels: dict = {}

    def op(code, k, jt=0, jf=0):
        prog.append([code, jt, jf, k])

    op(LD_W_ABS, 4)                                      # seccomp_data.arch
    for abi in abis:
        op(JEQ, _AUDIT_ARCH[abi], jt=f"abi:{abi}")
    op(RET, ALLOW)
    for abi in abis:
        labels[f"abi:{abi}"] = len(prog)
        op(LD_W_ABS, 0)                                  # seccomp_data.nr
        for nr in _IOCTL_NR[abi]:
            op(JEQ, nr, jt="check")
        op(RET, ALLOW)
    labels["check"] = len(prog)
    op(LD_W_ABS, 24)                                     # low 32 bits of args[1], the ioctl request
    op(JEQ, _TIOCSTI, jt="deny")
    op(JEQ, _TIOCLINUX, jt="deny")
    op(RET, ALLOW)
    labels["deny"] = len(prog)
    op(RET, DENY)
    out = b""
    for i, (code, jt, jf, k) in enumerate(prog):
        jt = labels[jt] - i - 1 if isinstance(jt, str) else jt
        jf = labels[jf] - i - 1 if isinstance(jf, str) else jf
        out += struct.pack("=HBBI", code, jt, jf, k)
    return out


def seccomp_path() -> str:
    """Where the filter lives on the host (outside every sandbox), written with the launchers."""
    return os.path.join(sandboxes_root(), ".identity", "seccomp-tty.bpf")


def write_seccomp_filter() -> str | None:
    data = seccomp_filter()
    if data is None:
        return None
    path = seccomp_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


# -------------------------------------------------------------------------- file arguments (17.6.2)

# Runs on the host, from the launcher, when the app was given arguments (17.6.2). An argument naming a
# file or folder -- a path, a file:// URI, or an option's value (`--file=PATH`, `-oPATH` with a full
# path) -- becomes the path the app finds it at: inside a granted folder, the folder's own mount path
# plus the rest, unless the argument already resolves there (a CLI tool's relative paths in its shared
# folder, an absolute path written through no link); outside every granted folder, the document
# portal's re-export of it (Documents.Add + GrantPermissions for a file, AddFull with the
# export-directory flag for a folder, what the file chooser portal does for a pick), at
# $XDG_RUNTIME_DIR/doc/<id>/<name>, where the launcher binds the app's by-app view. Done from the host
# side, it works whatever the portal makes of the sandbox's marker (17.6.1). Review 2, F6: a relative
# path or `.` from a granted folder reached the private home; review 3, R3-17: a link outside the
# granted folders to a file inside one was passed by the link's path, which the app can't see; R3-16:
# option values and folders were never handed over. Prints the new arguments shell-quoted, one line;
# an argument that can't be handed over passes unchanged, and any failure of the whole leaves the
# launcher passing them all unchanged.
# argv: <app identity> <runtime dir> <the folder relative paths resolve in inside, or ""> [visible folder...] -- <arguments...>
FORWARD_HELPER = """import os, shlex, sys, urllib.parse
ident, rt, incwd, rest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
sep = rest.index("--")
pairs = [(d, os.path.realpath(d)) for d in rest[:sep]]        # (where the app sees it, where the host has it)
args = rest[sep + 1:]
in_place = bool(incwd) and os.path.realpath(incwd) == os.path.realpath(os.getcwd())


def inside(path):
    real = os.path.realpath(path)
    for seen, host in pairs:
        if real == host or real.startswith(host + os.sep):
            return seen + real[len(host):]
    return None


def as_file(arg):
    if arg.startswith("file://"):
        u = urllib.parse.urlsplit(arg)
        return (urllib.parse.unquote(u.path), True) if u.netloc in ("", "localhost") else (None, True)
    if "://" in arg:
        return None, False
    return arg, False


bus = None


def portal():
    global bus
    from gi.repository import Gio
    if bus is None:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return bus


def export(path):
    from gi.repository import Gio, GLib
    fdl = Gio.UnixFDList.new()
    i = fdl.append(os.open(path, os.O_RDONLY))
    res, _ = portal().call_with_unix_fd_list_sync(
        "org.freedesktop.portal.Documents", "/org/freedesktop/portal/documents", "org.freedesktop.portal.Documents",
        "Add", GLib.Variant("(hbb)", (i, True, False)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 5000, fdl, None)
    doc = res.unpack()[0]
    perms = ["read"] + (["write"] if os.access(path, os.W_OK) else [])
    portal().call_sync("org.freedesktop.portal.Documents", "/org/freedesktop/portal/documents", "org.freedesktop.portal.Documents",
                       "GrantPermissions", GLib.Variant("(ssas)", (doc, ident, perms)), None, Gio.DBusCallFlags.NONE, 5000, None)
    return os.path.join(rt, "doc", doc, os.path.basename(path))


def export_dir(path):
    from gi.repository import Gio, GLib
    fdl = Gio.UnixFDList.new()
    i = fdl.append(os.open(path, os.O_PATH | os.O_DIRECTORY))
    perms = ["read"] + (["write"] if os.access(path, os.W_OK) else [])
    res, _ = portal().call_with_unix_fd_list_sync(       # 1: reuse an existing export, 8: export a directory
        "org.freedesktop.portal.Documents", "/org/freedesktop/portal/documents", "org.freedesktop.portal.Documents",
        "AddFull", GLib.Variant("(ahusas)", ([i], 1 | 8, ident, perms)), GLib.VariantType("(asa{sv})"),
        Gio.DBusCallFlags.NONE, 5000, fdl, None)
    return os.path.join(rt, "doc", res.unpack()[0][0], os.path.basename(os.path.realpath(path)))


def hand(path, uri):
    if not os.path.exists(path) or (in_place and not uri and not os.path.isabs(path)):
        return None
    seen = inside(path)
    if seen is not None:
        if os.path.isabs(path) and os.path.normpath(path) == seen:
            return None                 # already the path the app sees
        new = seen
    else:
        try:
            new = export(path) if os.path.isfile(path) else export_dir(path) if os.path.isdir(path) else None
        except Exception:
            return None
    if new is None:
        return None
    if path.endswith("/") and not new.endswith("/"):
        new += "/"
    return "file://" + urllib.parse.quote(new) if uri else new


def one(arg):
    path, uri = as_file(arg)
    new = hand(path, uri) if path else None
    return arg if new is None else new


out = []
for a in args:
    new = one(a)
    if new == a and a.startswith("--") and "=" in a:
        name, val = a.split("=", 1)
        new = name + "=" + one(val)
    elif new == a and a.startswith("-") and not a.startswith("--") and a[2:3] == "/":
        new = a[:2] + one(a[2:])
    out.append(new)
print(" ".join(shlex.quote(a) for a in out))
"""


def forward_path() -> str:
    """Where the file-argument helper lives on the host, written with the launchers."""
    return os.path.join(sandboxes_root(), ".identity", "forward-files.py")


def write_forward_helper() -> str:
    path = forward_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(FORWARD_HELPER)
    os.replace(tmp, path)
    return path


# -------------------------------------------------------------------------- opening things on the host (17.6.3)

# `xdg-open` as a sandboxed app sees it, first on its PATH. The desktop's own xdg-open would start the
# host's browser or viewer *inside* the sandbox -- a second Firefox with an empty profile, or nothing
# at all. This one asks the host through the OpenURI portal, which the proxy allows: a URL goes to
# the host's default handler; a file is passed as a file descriptor, and the portal opens the file
# it points to with a host program, asking the user which one as it does for a Flatpak app. That
# works for a file in a granted folder or the hand-over view, which have the same path on both
# sides; a file in the private home reaches the portal as $HOME/<x> -- the private home is mounted
# over $HOME -- where the host has no such file, so the portal refuses it (17.6.3). GLib-based apps
# reach the same portal on their own (they read /.flatpak-info) -- but only because the launcher
# hides the host's desktop entries from them (17.4): GLib prefers any handler it can find and asks
# the portal when there is none. Qt calls the portal itself when it sees the marker. This covers the
# rest -- Electron and anything else that runs xdg-open. Options go to the real xdg-open (usage,
# --version).
XDG_OPEN_SHIM = """#!/bin/sh
# Written by AppKata for its sandboxed apps (requirement 17.6.3): opens links and files on the host
# through the OpenURI portal, instead of starting a host program inside the sandbox.
set -u
case "${1:-}" in ""|-*) exec /usr/bin/xdg-open "$@" ;; esac
if [ ! -S "${XDG_RUNTIME_DIR:-/nonexistent}/bus" ]; then      # no bus: its address leads nowhere (R3-33)
  echo "AppKata: this app runs Strict, with no desktop services, so it can't open $1 on this computer (App Detail > Sandbox to change that)." >&2
  exit 3
fi
case "$1" in
  file://*|/*|./*|../*) ;;
  *:*)
    if command -v gdbus >/dev/null 2>&1; then
      exec gdbus call --session --dest org.freedesktop.portal.Desktop --object-path /org/freedesktop/portal/desktop \\
        --method org.freedesktop.portal.OpenURI.OpenURI "" "$1" '{}' >/dev/null
    elif command -v busctl >/dev/null 2>&1; then
      exec busctl --user call org.freedesktop.portal.Desktop /org/freedesktop/portal/desktop \\
        org.freedesktop.portal.OpenURI OpenURI 'ssa{sv}' "" "$1" 0 >/dev/null
    fi
    echo "AppKata: neither gdbus nor busctl is available to open $1 on the host" >&2; exit 3 ;;
esac
# The Python below exits 0 when the host opened the file (or is still asking), 4 when the host could
# not open it (said on stderr), 5 when the user cancelled; anything else is the call itself failing.
python3 - "$1" <<'PY'
import os, sys, urllib.parse
from gi.repository import Gio, GLib
target = sys.argv[1]
if target.startswith("file://"):
    target = urllib.parse.unquote(urllib.parse.urlsplit(target).path)
fdl = Gio.UnixFDList.new()
i = fdl.append(os.open(target, os.O_RDONLY))
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
# The call returns a Request at once; whether the host could open the file comes later, as the
# Request's Response signal (0 opened, 1 the user cancelled a chooser, 2 failed). Wait for it, as
# GLib does, so a file the host can't locate -- one in this app's private home -- is reported here
# rather than opening nothing in silence (round five, R5-6: shown with the real portal).
token = "appkata%d" % os.getpid()
req = "/org/freedesktop/portal/desktop/request/%s/%s" % (bus.get_unique_name()[1:].replace(".", "_"), token)
loop, result = GLib.MainLoop(), {}
def response(conn, sender, path, iface, signal, params):
    result["code"] = params.unpack()[0]
    loop.quit()
bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request", "Response", req, None,
                     Gio.DBusSignalFlags.NONE, response)
bus.call_with_unix_fd_list_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
    "org.freedesktop.portal.OpenURI", "OpenFile",
    GLib.Variant("(sha{sv})", ("", i, {"handle_token": GLib.Variant("s", token)})), None,
    Gio.DBusCallFlags.NONE, 30000, fdl, None)
GLib.timeout_add_seconds(120, loop.quit)       # a chooser may be up; past that, assume the host has it
loop.run()
code = result.get("code", 0)
if code == 2:
    print("AppKata: the host couldn't open %s. A file in this app's private home isn't visible outside the sandbox; "
          "keep it in a folder the app is given (App Detail > Sandbox) to open it on this computer." % sys.argv[1], file=sys.stderr)
    sys.exit(4)
sys.exit(5 if code == 1 else 0)
PY
st=$?
[ "$st" = 0 ] && exit 0
{ [ "$st" = 4 ] || [ "$st" = 5 ]; } && exit 1
echo "AppKata: couldn't ask the host to open $1 (is python3-gi installed?)" >&2; exit 3
"""

SHIMS_MOUNT = "/run/appkata"            # where the launcher binds the shims, first on the app's PATH


def shims_dir() -> str:
    """The host folder holding the programs the sandbox sees first on its PATH, written with the
    launchers, outside any private home."""
    return os.path.join(sandboxes_root(), ".identity", "bin")


def write_shims() -> str:
    d = shims_dir()
    os.makedirs(d, mode=0o755, exist_ok=True)
    path = os.path.join(d, "xdg-open")
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(XDG_OPEN_SHIM)
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)
    return d


# -------------------------------------------------------------------------- the launcher (17.4)

# environment variables passed through from the host (theming, locale, session), set only when present
_ENV_PASSTHROUGH = (
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_NUMERIC", "LC_TIME", "TERM",
    "USER", "LOGNAME", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
    "GTK_THEME", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE", "XCURSOR_THEME", "XCURSOR_SIZE",
    "GDK_SCALE", "GDK_DPI_SCALE", "QT_SCALE_FACTOR",
    # the user's regional formats, time zone, Qt's per-screen scaling (Plasma's X11 session sets it)
    # and input method: the session carries them, and an app without them looks or types wrong
    # (review 2, F15; review 3, R3-18 -- the owner's decision)
    "LC_MONETARY", "LC_PAPER", "LC_MEASUREMENT", "LC_ADDRESS", "LC_TELEPHONE", "LC_NAME", "LC_COLLATE",
    "LC_IDENTIFICATION", "TZ", "QT_SCREEN_SCALE_FACTORS", "QT_AUTO_SCREEN_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING",
    "GTK_IM_MODULE", "QT_IM_MODULE", "XMODIFIERS", "SDL_IM_MODULE",
)
# The proxy settings, passed only to an app with the network grant: they can carry the proxy's
# credentials, and only an app that has the network uses them (review 2, F15)
_PROXY_PASSTHROUGH = ("http_proxy", "https_proxy", "ftp_proxy", "all_proxy", "no_proxy",
                      "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY")
# DBUS_SESSION_BUS_ADDRESS is deliberately NOT passed through: the sandboxed app must reach the
# *filtered* proxy socket, so the launcher sets it explicitly to unix:path=$rt/bus after --clearenv
# (below). Passing the host address through would point the app at the real (unfiltered) bus address.

_LAUNCHER_HEADER = """#!/bin/sh
# Generated by AppKata for {name}. Do not edit — regenerated on update / settings change (req 17.4).
set -eu
id={id}
rt="${{XDG_RUNTIME_DIR:-/run/user/$(id -u)}}"
home={home}
info={info}
appdir={appdir}
exe={exe}
# Without a session runtime folder (no logind session: ssh without one, cron, a bare container)
# nothing below can work -- the proxy socket, the display sockets and the document view all live
# there -- so say which folder is missing rather than fail on the first mkdir.
mkdir -p "$home" "$rt/appkata" || {{ echo "AppKata: can't use the session's runtime folder $rt (XDG_RUNTIME_DIR); the sandbox needs a logged-in session." >&2; exit 1; }}
# Where stderr goes (requirement 14.2). Started by AppKata's Open, it is already this app's log.
# Started from the app menu, a file manager or a shortcut -- the desktop entry passes the word
# --appkata-menu first -- there is no terminal, so nothing would show a refused launch: stderr is
# appended to that same log, rotated at 2 MB like AppKata's own, under a dated line. Started any
# other way (a command link in a terminal or a script) it stays the caller's, so a tool's `2>file`
# and pipelines keep meaning what they say. $logging tells the run-time line below.
log={log}
logging=0
if [ /dev/fd/2 -ef "$log" ]; then
  logging=1
elif [ "${{1:-}}" = --appkata-menu ]; then
  shift
  mkdir -p "${{log%/*}}" 2>/dev/null || true
  if [ "$(stat -c %s "$log" 2>/dev/null || echo 0)" -gt 2097152 ]; then mv -f "$log" "${{log%.log}}-prev.log"; fi
  if printf -- '--- %s AppKata: starting %s (from the menu)\\n' "$(date '+%Y-%m-%d %H:%M:%S')" {qname} >> "$log" 2>/dev/null; then
    exec 2>>"$log"
    logging=1
  fi
fi
# bwrap is the sandbox. Without it the app can't run sandboxed, and AppKata never runs it any other
# way unasked (17.10; review 2, F16), so say so rather than leave the shell's "not found".
command -v bwrap >/dev/null 2>&1 || {{ printf "AppKata: bubblewrap (bwrap) isn't installed, so %s can't run sandboxed here. Install it, or set its sandbox to Off in AppKata (App Detail > Sandbox).\\n" {qname} >&2; exit 1; }}
{cwd}{forward}{note}# The bwrap words decided at run time are prepended to "$@", ahead of the program and its own
# arguments, each word quoted -- so paths and values with spaces or glob characters stay whole.
set -- -- "$appdir/$exe" "$@"
"""

# File arguments (17.6.2), Standard apps only -- Strict ones have no bus and so no document portal.
# {visible}: the granted folders (and, for a CLI tool, the directory it runs in), where a file is
# already in view and keeps its real path.
_FORWARD_BLOCK = """# A file or folder the app was given as an argument ("Open with", a drop on the menu entry, `tool
# ~/x.txt`, `--file=~/x.txt`) is a host path: one in a granted folder becomes the path the app sees it
# at, the rest are handed over through the document portal from the host side. Without python3-gi or
# a document portal the arguments pass through unchanged (requirement 17.6.2).
if [ $# -gt 0 ] && command -v python3 >/dev/null 2>&1; then
  if fwd=$(python3 {helper} "$id" "$rt" {incwd} {visible} -- "$@" 2>/dev/null); then eval "set -- $fwd"; fi
fi
"""

# Lazy, sandboxed AppImage extraction (17.7): run the publisher's own runtime inside a Strict bwrap
# that can write only a staging dir. Redone when $appdir (the derived cache) is missing or was made from
# a different file: "$appdir.stamp" records the .AppImage's size, mtime and inode, since the cache is
# named by version only and an .AppImage can be replaced in place (a fixed-name app, a reinstall).
# Launches serialize on "$appdir.lock" (flock, where present) so simultaneous first launches don't
# extract over each other. The runtime decides what it leaves behind, so only a real directory
# squashfs-root is accepted -- a symlink would make the launcher bind whatever it points at.
_EXTRACT_BLOCK = """img={img}
stamp=$(stat -L -c '%s %Y %i' "$img")
if [ ! -d "$appdir" ] || [ "$(cat "$appdir.stamp" 2>/dev/null)" != "$stamp" ]; then
  if command -v flock >/dev/null 2>&1; then exec 9>"$appdir.lock"; flock 9; fi
  if [ ! -d "$appdir" ] || [ "$(cat "$appdir.stamp" 2>/dev/null)" != "$stamp" ]; then
    stg=$(mktemp -d "$appdir.new.XXXXXX")
    bwrap --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 \\
      --symlink usr/bin /bin --symlink usr/sbin /sbin --ro-bind /etc /etc --proc /proc --dev /dev --tmpfs /tmp \\
      --ro-bind "$img" "$img" --bind "$stg" "$stg" --chdir "$stg" \\
      --unshare-all --die-with-parent --new-session \\
      --clearenv --setenv HOME "$stg" --setenv PATH /usr/bin:/bin -- "$img" --appimage-extract >/dev/null || {{
      st=$?; rm -rf "$stg"
      echo "AppKata: $img's own runtime couldn't unpack it (exit $st); not running it. A type-1 AppImage or a broken download can't be sandboxed; run it Off or re-download it." >&2
      exit 1
    }}
    if [ -L "$stg/squashfs-root" ] || [ ! -d "$stg/squashfs-root" ]; then
      rm -rf "$stg"
      echo "AppKata: $img didn't unpack to a folder; not running it." >&2
      exit 1
    fi
    rm -rf "$appdir" "$appdir.stamp"; mv "$stg/squashfs-root" "$appdir"; rm -rf "$stg"
    printf '%s\\n' "$stamp" > "$appdir.stamp"
  fi
  exec 9>&-
fi
"""


# Where the system's own bwrap profile (Ubuntu 25.04+, `bwrap-userns-restrict`) confines everything
# bwrap runs, no program inside the sandbox can make a user namespace, and Chromium's own sandbox --
# Electron's too -- needs one; an AppImage's chrome-sandbox isn't setuid to fall back on, so the app
# would refuse to start. There the launcher passes --no-sandbox to a program that brings Chromium's
# sandbox (chrome-sandbox or chrome_crashpad_handler beside it): it stays inside AppKata's sandbox and
# loses only its inner one (17.10.2; review 2, F2, owner's decision). Decided after the AppImage is
# unpacked, before anything is prepended: "$@" is still `-- program args`.
_INNER_BLOCK = """d=$(dirname "$appdir/$exe")
for f in "$appdir/chrome-sandbox" "$appdir/chrome_crashpad_handler" "$d/chrome-sandbox" "$d/chrome_crashpad_handler"; do
  if [ -e "$f" ]; then
    shift 2
    set -- -- "$appdir/$exe" --no-sandbox "$@"
    break
  fi
done
"""


# A Strict app sees its private home alone: a file or folder named on its command line isn't in view,
# and nothing hands it over (no bus, 17.6.2). Started from a terminal with arguments, it says so,
# rather than a tool failing on every argument in silence (17.3.3; review 2, F4: shown with a Strict
# tool run from a project folder). Not said where nothing shows stderr.
_STRICT_NOTE = """if [ $# -gt 0 ] && [ -t 2 ]; then
  printf 'AppKata: %s runs Strict: it sees only its own private home, so files and folders named here are not visible to it (App Detail > Sandbox to change that).\\n' {qname} >&2
fi
"""


def _launcher_env(net: bool = False) -> list[str]:
    # Pass through theming/locale/session vars that are set on the host (names are our own fixed list,
    # so the indirect `eval` is safe), and the proxy settings with the network grant. Unset vars are
    # skipped so we never force an empty locale; a var set to "" is passed as "" (one quoted word),
    # never dropped.
    # The names come from the exported environment the launcher was started with, not from its shell's
    # own variables: bash, /bin/sh on RHEL and Fedora, sets TERM=dumb when it is unset, without
    # exporting it (review 3, R3-20: every app started from the menu there got TERM=dumb).
    # `export -p` is the shell's own list of exported variables ("export NAME=..." in dash and in bash
    # as sh, "declare -x NAME=..." in bash otherwise), so no outside program is needed.
    return ['exported=$(export -p)',
            'for v in ' + " ".join(_ENV_PASSTHROUGH + (_PROXY_PASSTHROUGH if net else ())) + '; do',
            '  case "',
            '$exported" in *"',
            'export $v="*|*"',
            'declare -x $v="*) ;; *) continue ;; esac',
            '  eval "val=\\$$v"',
            '  set -- --setenv "$v" "$val" "$@"',
            'done']


# Mount destinations under $HOME land inside the private home, which the app writes freely. bwrap
# resolves a destination through whatever is there, so a symlink the app left at any path component
# (`~/.themes`, `~/bin` above its own version folder, `~/.Xauthority`) is followed on the host side:
# bwrap creates the missing file or folders at the link's target as the user (confirmed on 0.4.0 and
# 0.9.0), or aborts the launch when it can't. A symlink is never legitimate at these paths, so the
# launcher drops any it finds before mounting; `rm` on a link never follows it. A second, already
# running instance could still plant one between this check and bwrap's mounts — bwrap offers no
# fd-based destination to close that — so the guard covers the persistent case, not a live race.
# Nested folder grants (~/Projects rw with ~/Projects/sub/deep ro) don't reopen the hole from the
# source side: a link the app plants at the outer grant lands on the host, but bwrap resolves the
# *source* on the host too, where /oldroot does not exist, so --bind-try skips the mount, and a link
# to a path that resolves on both sides mounts inside the private home. Checked in round two.
_GUARD_FN = """guard() {
  case "$1" in "$HOME"/*) ;; *) return 0 ;; esac
  rel=${1#"$HOME"/}; p=$home
  while [ -n "$rel" ]; do
    case "$rel" in */*) seg=${rel%%/*}; rel=${rel#*/} ;; *) seg=$rel; rel= ;; esac
    [ -n "$seg" ] || continue
    p="$p/$seg"
    if [ -L "$p" ]; then
      echo "AppKata: removing a link the app left at $p (a mount point)." >&2
      rm -f "$p"
    fi
    [ -e "$p" ] || return 0
  done
}
"""

# The CLI-tool template's "$cwd" grant (17.3.3): the directory the tool is run in, except where that
# would hand over far more than a project folder — the home folder or anything above it (the whole
# home, or the whole filesystem at /), or AppKata's own areas (installed apps, other apps' private
# homes). There the tool runs in its private home instead and says why. Paths are compared physically
# (`pwd -P`), so a symlinked route to the same place is caught too. The decision is made in the
# header, before the file-argument block, which counts the directory as visible only when it will
# be shared (round three, R3-3: it always counted "$PWD", so a file named from a refused folder was
# neither visible nor handed over). When shared, the bind and a --chdir into it are added after the
# words are fixed; otherwise a --chdir into the private home (bwrap warns if given two).
_CWD_DECIDE = """here=$(pwd -P 2>/dev/null || echo /)
hm=$(cd "$HOME" 2>/dev/null && pwd -P || echo "$HOME")
share=1
[ "$here" = / ] && share=0
for d in "$hm" {protected}; do
  case "$d/" in "$here"/*) share=0 ;; esac
done
for d in {protected}; do
  case "$here/" in "$d"/*) share=0 ;; esac
done
cwdvis=
[ "$share" = 1 ] && cwdvis=$here
"""
_CWD_WORDS = """if [ "$share" = 1 ]; then
  guard "$here"
  set -- {bind} "$here" "$here" --chdir "$here" "$@"
else
  set -- --chdir "$HOME" "$@"
  printf "%s runs sandboxed and can't see %s (your home folder or a folder above it, AppKata's own files, or a folder like ~/.config, ~/.ssh, ~/.local/bin or the session's runtime folder).\\n" {name} "$here" >&2
  echo "Run it from a project folder, or give it a folder in AppKata (App Detail > Sandbox). A file you name on the command line is handed over either way." >&2
fi
"""


def build_launcher(app_id: str, name: str, appdir: str, exec_rel: str, gs: dict,
                   appimage_path: str | None = None, apps_root: str | None = None,
                   seccomp: str | None = None, log_path: str | None = None, forward: str | None = None,
                   shims: str | None = None, inner_sandbox: bool = True, bus_filter: bool = True) -> str:
    """The text of `~/bin/apps/<app>/run` with the resolved grant set baked in (17.4). The launcher
    does no run-time policy resolution; its text is exactly what runs (shown in App Detail, audited).

    `appdir`: the app's current version folder (the extracted dir for an AppImage). `exec_rel`: the
    program, relative to `appdir`. `appimage_path`: the kept `.AppImage` (sets APPIMAGE), or None.
    `apps_root`: the install root, which a CLI tool's working-directory grant must never expose.
    `seccomp`: the terminal-injection filter (:func:`write_seccomp_filter`); without one the program
    runs in a new session instead, safe but cut off from its terminal. `log_path`: the app's log
    (:func:`applog.app_log_path`), where the launcher sends its stderr when no terminal shows it.
    `forward`: the file-argument helper (:func:`write_forward_helper`); without one, file arguments
    are passed through as they are. `shims`: the folder of programs the app finds first on its PATH
    (:func:`write_shims`, the portal-aware xdg-open); without one the app gets the desktop's.
    `inner_sandbox`: whether an app's own sandbox (Chromium, Electron) can run inside this one here
    (:func:`nested_userns_works`); where it can't, such an app is started with --no-sandbox (17.10.2).
    `bus_filter`: whether xdg-dbus-proxy is here (:func:`have_bus_filter`); without it a Standard app
    runs with no session bus, and the files it is given still reach it (17.10; review 2, F12).
    """
    from . import applog
    gs, refused = strip_protected(gs, apps_root)
    q = shlex.quote
    home = sandbox_home(app_id)
    strict = gs["level"] == "strict"
    cli = "$cwd" in gs["folders"]

    # Standard's file hand-over is the host's document portal, asked from outside the sandbox; only its
    # session bus needs the proxy.
    standard = uses_bus(gs)
    bus = standard and bus_filter
    cwd = ""
    if cli:
        # The same folders a grant may never share (17.3.1), plus the private homes and the runtime
        # folder as the launcher sees it: "$rt" holds the real session bus, and a bind of it would land
        # after the proxy socket's and put the unfiltered bus back.
        roots = [sandboxes_root()] + [r for r, _ in _protected_roots(apps_root)]
        protected = " ".join(q(os.path.realpath(r)) for r in roots) + ' "$rt"'
        cwd = _CWD_DECIDE.format(protected=protected)
    fwd = ""
    if forward and standard:
        # the working directory counts as visible only when the block above will share it
        visible = [q(os.path.expanduser(p)) for p in sorted(gs["folders"]) if p != "$cwd"] + (['${cwdvis:+"$cwdvis"}'] if cli else [])
        # where a relative path resolves inside: a CLI tool's shared folder, else nowhere it does outside
        incwd = '"${cwdvis:-}"' if cli else '""'
        fwd = _FORWARD_BLOCK.format(helper=q(forward), incwd=incwd, visible=" ".join(visible))
    # Text that lands in a *comment* is not a shell word, so a newline in it would end the comment
    # and run what follows: the name and a refused path are flattened there, quoted everywhere else.
    c = lambda s: " ".join(str(s).split())         # noqa: E731
    note = _STRICT_NOTE.format(qname=q(name)) if strict else ""
    out = [_LAUNCHER_HEADER.format(name=c(name), qname=q(name), id=app_identity(app_id), home=q(home),
                                   info=q(identity_path(app_id)), appdir=q(appdir), exe=q(exec_rel),
                                   log=q(log_path or applog.app_log_path(app_id)), cwd=cwd, forward=fwd, note=note), _GUARD_FN]
    for path, why in refused:            # said in the launcher itself, which App Detail can show
        out.append(f"# Refused folder grant {c(path)}: {c(why)} (requirement 17.3.1).")
    if appimage_path is not None:
        out.append(_EXTRACT_BLOCK.format(img=q(appimage_path)))
    if not inner_sandbox:
        out.append(_INNER_BLOCK)
    if cli:
        bind = "--bind" if gs["folders"]["$cwd"] == "rw" else "--ro-bind"
        out.append(_CWD_WORDS.format(name=q(name), bind=bind))

    # 1. The filtered session-bus proxy (Standard only; Strict adds none).
    if standard and not bus:
        out.append("# No session bus: xdg-dbus-proxy isn't installed here, so this Standard app gets none,\n"
                   "# and no desktop services, until it is (requirement 17.10).\n")
    if bus:
        pargs = " ".join(shlex.quote(a) for a in proxy_args(gs, app_id))
        # The socket is named by a hash of the id: a Unix socket path holds 107 bytes, and an id is the
        # app name's slug, of any length (review 3, R3-12: an id past ~60 characters couldn't start).
        tag = hashlib.sha256(app_id.encode()).hexdigest()[:16]
        out.append(
            f'sock="$rt/appkata/bus-{tag}.$$"\n'
            'rm -f "$sock"\n'
            '# Read the host bus with a default so `set -u` can\'t abort the launcher when it is unset.\n'
            'upstream="${DBUS_SESSION_BUS_ADDRESS:-}"\n'
            '# Proxy in its own tmpfs-root bwrap, with $rt bound rw so its socket is visible to the\n'
            '# launcher (the P1 gotcha, resolved — local-proxy-test-plan.md). It carries *no*\n'
            '# /.flatpak-info: the portals judge the caller by the proxy\'s root, and xdg-desktop-portal\n'
            '# 1.18+ refuses a marked caller that is not a running Flatpak (requirement 17.6.1), so the\n'
            '# app is a host caller to them and the proxy allows only the portal interfaces safe for one.\n'
            '# Its own pid namespace ends it with bwrap: killing bwrap kills the namespace\'s first\n'
            '# process (bwrap\'s, which keeps --die-with-parent), and with it everything inside. The\n'
            '# proxy\'s own death signal is not enough: the kernel clears it at an exec that changes\n'
            '# the security domain, as entering Ubuntu 25.04+\'s unpriv_bwrap does, and every launch\n'
            '# there left its proxy running (review 2, F2; requirement 17.10.2).\n'
            'bwrap --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 \\\n'
            '  --symlink usr/bin /bin --ro-bind /etc /etc --proc /proc --dev /dev \\\n'
            '  --bind "$rt" "$rt" --unshare-pid --die-with-parent -- \\\n'
            '  xdg-dbus-proxy "$upstream" "$sock" ' + pargs + ' &\n'
            'proxy=$!\n'
            '# Wait for the socket, but stop early if the proxy died (e.g. no host bus) instead of\n'
            '# blocking for the full timeout.\n'
            'i=0; while [ ! -S "$sock" ] && kill -0 "$proxy" 2>/dev/null && [ "$i" -lt 50 ]; do i=$((i+1)); sleep 0.1; done\n'
            '# Said plainly when it didn\'t start, rather than left to bwrap ("Can\'t find source path").\n'
            'if [ ! -S "$sock" ]; then\n'
            '  kill "$proxy" 2>/dev/null || true\n'
            f"  printf 'AppKata: the session-bus filter (xdg-dbus-proxy) did not start, so %s cannot run sandboxed here.\\n' {q(name)} >&2\n"
            '  exit 1\n'
            'fi\n')

    # Display: the Wayland socket if present, else X11 with XAUTHORITY (17.9), decided at run time.
    # On Wayland, X11 (XWayland) is added too when the "x11" device grant allows it, so an app that
    # only speaks X11 still opens; one that speaks Wayland keeps preferring it. The --setenv words land
    # after --clearenv, like everything prepended to "$@".
    out.append(
        'x11=0\n'
        'if [ -n "${WAYLAND_DISPLAY:-}" ] && [ -e "$rt/$WAYLAND_DISPLAY" ]; then\n'
        '  set -- --ro-bind "$rt/$WAYLAND_DISPLAY" "$rt/$WAYLAND_DISPLAY" --setenv WAYLAND_DISPLAY "$WAYLAND_DISPLAY" "$@"\n'
        + ('  [ -n "${DISPLAY:-}" ] && x11=1\n' if "x11" in gs["devices"] else '') +
        'elif [ -n "${DISPLAY:-}" ]; then\n'
        '  x11=1\n'
        'fi\n'
        'if [ "$x11" = 1 ]; then\n'
        '  set -- --ro-bind-try /tmp/.X11-unix /tmp/.X11-unix --setenv DISPLAY "$DISPLAY" "$@"\n'
        '  xa="${XAUTHORITY:-$HOME/.Xauthority}"\n'
        '  if [ -e "$xa" ]; then guard "$xa"; set -- --ro-bind "$xa" "$xa" --setenv XAUTHORITY "$xa" "$@"; fi\n'
        'fi\n')

    # DNS for a network grant: /etc is bound, but on Ubuntu/Mint (systemd-resolved) /etc/resolv.conf is
    # a symlink into /run/systemd/resolve, and NetworkManager may point it into /run too. Bind where it
    # really lives: the resolved directory (stub file and the varlink socket nss-resolve uses), or the
    # one file elsewhere outside /etc and /usr.
    net = gs["network"] and not strict
    if net:
        out.append(
            'rc=$(readlink -f /etc/resolv.conf 2>/dev/null || true)\n'
            'case "$rc" in\n'
            '  /run/systemd/resolve/*) set -- --ro-bind /run/systemd/resolve /run/systemd/resolve "$@" ;;\n'
            '  ""|/etc/*|/usr/*) ;;\n'
            '  *) if [ -e "$rc" ]; then set -- --ro-bind "$rc" "$rc" "$@"; fi ;;\n'
            'esac\n')

    # The host's desktop entries, hidden (17.6.3). GLib opens a link or file with the default handler
    # it finds and asks the OpenURI portal only when it finds none; /usr is in view, so on a desktop
    # it found firefox.desktop and xed.desktop and started them *inside* the sandbox (round three,
    # R3-1, shown with GLib 2.80). A Flatpak runtime has no desktop entries; an empty tmpfs over each
    # applications folder that exists gives the same. There is no --tmpfs-try, and a folder missing
    # under the read-only /usr can't be created, so only the ones present are masked. The MIME
    # database (/usr/share/mime) stays. These words land in "$@", after the /usr bind.
    out.append('for d in /usr/share/applications /usr/local/share/applications; do\n'
               '  if [ -d "$d" ]; then set -- --tmpfs "$d" "$@"; fi\n'
               'done\n')

    out += _launcher_env(net)
    # Every baked destination that can sit inside the private home (see guard above).
    dests = ['"$HOME/.themes"', '"$HOME/.icons"', '"$HOME/.fonts"', '"$HOME/.config/fontconfig"',
             '"$HOME/.local/share/fonts"', '"$HOME/.local/share/icons"', '"$HOME/.local/share/themes"', '"$appdir"']
    if appimage_path is not None:
        dests.append('"$img"')
    dests += [q(os.path.expanduser(p)) for p in sorted(gs["folders"]) if p != "$cwd"]
    out.append("for d in " + " ".join(dests) + '; do guard "$d"; done')
    out.append("")

    # 2. The sandboxed app. Fixed args are baked; the run-time ones are in "$@", after them.
    # bwrap always runs as this shell's child, at every level, and its exit status is carried
    # through (set -e would otherwise abort before the teardown). --die-with-parent ties the sandbox
    # to bwrap's *parent*: when the Strict launcher exec'd bwrap, that parent was whatever started
    # the launcher -- AppKata's Open, the desktop shell, `gio launch` -- and the app died the moment
    # it exited (quit AppKata, and every Strict app it had opened vanished: round four, R4-2). The
    # shell waits here, so the parent lives exactly as long as the app.
    # The line AppKata's watcher times the start from (applog.watch): everything above is the
    # launcher's own work -- unpacking an AppImage can take a minute -- and a refusal before this line
    # is reported however long it took; a non-zero exit soon after it is the program dying at start.
    out.append('if [ "$logging" = 1 ]; then printf \'AppKata: running %s (%s)\\n\' "$appdir/$exe" "$(date +%s)" >&2; fi')
    out.append("status=0")
    if seccomp:
        out.append(f"exec 3< {q(seccomp)}")
    parts = [
        "bwrap \\",
        "  --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 \\",
        "  --symlink usr/bin /bin --symlink usr/sbin /sbin --ro-bind /etc /etc \\",
        "  --ro-bind-try /var/cache/fontconfig /var/cache/fontconfig \\",
        '  --proc /proc --dev /dev --dev-bind-try /dev/dri /dev/dri --tmpfs /tmp --dir "$rt" \\',
        # The document portal's hand-over (17.6): a file the user picks in a portal file chooser is
        # re-exported by xdg-document-portal on its FUSE mount, and the chooser returns the path
        # $rt/doc/<docid>/<name>. The portal's by-app/<id> view holds just this app's documents, so it is
        # bound at $rt/doc, as Flatpak does; without it the returned path doesn't exist in the sandbox
        # and a Standard app can't open any user file at all. The view is a directory as soon as the
        # portal runs, before anything is exported for the id (checked on xdg-desktop-portal 1.20), so
        # a file picked or passed during the app's very first run is visible at once; -try is only for
        # a session with no document portal, where the bind is skipped and nothing else changes.
        *(['  --bind-try "$rt/doc/by-app/$id" "$rt/doc" \\'] if standard else []),
        # The parts of /sys that GPU drivers and libdrm read to identify /dev/dri nodes (drmGetDevices2
        # maps a node's major:minor through /sys/dev/char); without them Mesa falls back to software
        # rendering. Read-only, the same set Flatpak gives every app.
        '  --ro-bind-try /sys/block /sys/block --ro-bind-try /sys/bus /sys/bus --ro-bind-try /sys/class /sys/class \\',
        '  --ro-bind-try /sys/dev /sys/dev --ro-bind-try /sys/devices /sys/devices \\',
        ('  --bind "$home" "$HOME" --bind "$appdir" "$appdir" \\' if gs["write_app"]
         else '  --bind "$home" "$HOME" --ro-bind "$appdir" "$appdir" \\'),
        '  --ro-bind-try "$HOME/.themes" "$HOME/.themes" --ro-bind-try "$HOME/.icons" "$HOME/.icons" \\',
        '  --ro-bind-try "$HOME/.fonts" "$HOME/.fonts" --ro-bind-try "$HOME/.config/fontconfig" "$HOME/.config/fontconfig" \\',
        # ... and where fonts, icons and themes are installed today (the XDG data dir), read-only too
        '  --ro-bind-try "$HOME/.local/share/fonts" "$HOME/.local/share/fonts" \\',
        '  --ro-bind-try "$HOME/.local/share/icons" "$HOME/.local/share/icons" \\',
        '  --ro-bind-try "$HOME/.local/share/themes" "$HOME/.local/share/themes" \\',
    ]
    # Keep the .AppImage itself visible read-only, so an app that reads $APPIMAGE (set below) resolves
    # it rather than a dangling path (17.7). $img is the extraction block's copy of appimage_path.
    if appimage_path is not None:
        parts.append('  --ro-bind-try "$img" "$img" \\')
    # Camera: the V4L2 devices themselves, which Chromium/Electron and most apps open directly. Without
    # the grant the app has no camera: the Camera portal is not among PORTAL_INTERFACES (for a host
    # caller it hands over devices without the sandbox's consent), so nothing asks (round six, R6-2).
    if "camera" in gs["devices"]:
        out.append('for d in /dev/video* /dev/media*; do\n'
                   '  if [ -c "$d" ]; then set -- --dev-bind "$d" "$d" "$@"; fi\n'
                   'done\n')
    # Folder grants (baked). $cwd (the CLI-tool template) binds the current directory (17.3.3).
    for path, mode in sorted(gs["folders"].items()):
        if path == "$cwd":           # added at run time by the working-directory block
            continue
        flag = "--bind-try" if mode == "rw" else "--ro-bind-try"
        p = q(os.path.expanduser(path))
        parts.append(f'  {flag} {p} {p} \\')
    # Sound: the PipeWire and Pulse sockets, the app identified as sandboxed by .flatpak-info (17.8).
    # PipeWire/WirePlumber don't stop such a client from recording (verified: WirePlumber 0.4.17,
    # PipeWire 1.0.5), so "play" and "record" bind the same sockets; enforcing the split is deferred.
    if gs["sound"]:
        parts.append('  --ro-bind-try "$rt/pipewire-0" "$rt/pipewire-0" \\')
        parts.append('  --ro-bind-try "$rt/pulse/native" "$rt/pulse/native" \\')
    # The identity marker, in the app's root only: PipeWire/WirePlumber take the app for a sandboxed
    # client from it, and GLib takes its portal use and network availability from it. The bus proxy
    # has none (above), so the portals see a host caller. Nothing binds it at $rt/flatpak-info, which
    # is what GTK3, Qt up to 6.4 and xdg-open would read to switch to the portal file chooser; GTK4,
    # Qt 6.5+ and Chromium read this one and then ask the FileChooser portal, which the proxy denies,
    # so each keeps its own dialog (17.6.3, PORTAL_INTERFACES).
    parts.append('  --ro-bind "$info" /.flatpak-info \\')
    if bus:
        parts.append('  --bind "$sock" "$rt/bus" \\')
    if shims:
        # xdg-open that asks the host through the OpenURI portal (17.6.3), first on PATH below. At
        # every level: a Strict app has no bus and so nothing to ask, and the shim says so and fails --
        # the desktop's own xdg-open, found in /usr, would start the host's browser inside the sandbox
        # under a desktop it doesn't know (round five, R5-4: shown with a fake firefox and no
        # XDG_CURRENT_DESKTOP; under Cinnamon or GNOME it failed quietly instead).
        parts.append(f'  --ro-bind-try {q(shims)} {SHIMS_MOUNT} \\')
    netarg = " --share-net" if net else ""
    session = "--seccomp 3" if seccomp else "--new-session"      # keep the terminal, refuse injection
    parts.append(f'  --unshare-all{netarg} --die-with-parent {session} \\')
    path_in = (SHIMS_MOUNT + ":" if shims else "") + "/usr/bin:/bin:/usr/sbin:/sbin"
    parts.append(f'  --clearenv --setenv HOME "$HOME" --setenv PATH {path_in} \\')
    parts.append('  --setenv XDG_RUNTIME_DIR "$rt" \\')
    # GTK4 reads /.flatpak-info and takes the portal road for its file dialog; the proxy denies the
    # FileChooser portal (for a host caller it returns paths the sandbox can't open, 17.6.3). GTK 4.14
    # fell back to its own dialog when refused; GTK 4.18 shows *no dialog at all* (round six, R6-4,
    # Ubuntu 25.04), and GTK_USE_PORTAL=0 doesn't stop a marked process from asking. GDK_DEBUG=no-portals
    # does: GTK4 then never asks and uses its own dialog, which shows exactly what the sandbox sees.
    # GTK3 ignores the flag and never asked anyway; GLib's own roads (links through OpenURI when no
    # handler is in view, notifications) read the marker, not this, and are unchanged. The cost is
    # GTK4's other portal dialogs (print, colour) -- the in-sandbox versions instead.
    parts.append('  --setenv GDK_DEBUG no-portals \\')
    # Point the app at the filtered proxy, set *after* --clearenv (and keepenv) so bwrap keeps it.
    # Emitted before --clearenv it was wiped; via the env passthrough it took the host bus address.
    # GTK_USE_PORTAL is deliberately not set either: the portal file chooser would answer a host
    # caller with real paths the sandbox cannot open, so apps use their own dialogs (17.6.3). An
    # app whose own AppRun sets GTK_USE_PORTAL=1 loses its GTK3 file dialog.
    # With no bus (Strict) the address is set all the same, and leads nowhere: unset, with a display,
    # GLib and libdbus *autolaunch* a bus through dbus-launch (dbus-x11, on every Mint and Ubuntu
    # desktop), inside the sandbox, and the first call on it starts the host's portal services from
    # /usr there too -- a Strict app's `gio open` then waited on them (review 3, R3-33).
    parts.append('  --setenv DBUS_SESSION_BUS_ADDRESS "unix:path=$rt/bus" \\')
    if appimage_path is not None:
        parts.append(f'  --setenv APPDIR "$appdir" --setenv APPIMAGE {q(appimage_path)} --setenv ARGV0 "$appdir/$exe" \\')
    if not cli:                      # a CLI tool's --chdir comes from the working-directory block
        parts.append('  --chdir "$HOME" \\')
    parts.append('  "$@" || status=$?')
    out.append("\n".join(parts))

    # 3. Tear down the proxy (only when there is one), and exit as the program did.
    if bus:
        out.append('\nkill "$proxy" 2>/dev/null || true\nrm -f "$sock"')
    out.append("exit $status")
    return "\n".join(out) + "\n"


def launcher_path(app_id: str, apps_root: str) -> str:
    return os.path.join(apps_root, app_id, "run")


def launcher_text(app_id: str, name: str, apps_root: str, appdir: str, exec_rel: str, gs: dict,
                  appimage_path: str | None = None) -> str:
    """The text :func:`write_launcher` writes for these inputs, without writing anything: the
    helpers it refers to live at fixed paths, so the text is a pure function of the app, its grant
    set and three facts about this machine (the seccomp filter's ABI, whether an app's own sandbox can
    run inside, 17.10.2, and whether xdg-dbus-proxy is here, 17.10), and the startup pass can tell a
    launcher an older AppKata wrote -- or one written before the system changed under it, an upgrade
    to Ubuntu 25.04+, the proxy installed since -- from today's (:func:`install.launcher_is_current`,
    round four R4-4)."""
    return build_launcher(app_id, name, appdir, exec_rel, gs, appimage_path, apps_root,
                          seccomp_path() if seccomp_filter() is not None else None,
                          forward=forward_path(), shims=shims_dir(), inner_sandbox=nested_userns_works(),
                          bus_filter=have_bus_filter())


def _marker_network(gs: dict) -> bool:
    n = normalize(gs)
    return bool(n["network"]) and n["level"] != "strict"


def helpers_current(app_id: str, gs: dict) -> bool:
    """Whether every file the launcher relies on but names only by path holds what AppKata would
    write today: the app's identity marker, the xdg-open shim (and its exec bit), the file-argument
    helper and the seccomp filter. Their contents aren't in the launcher's text, so comparing that
    alone left an older AppKata's shim or marker in place for good (review 2, F5; round four R4-4's
    class). The startup pass rewrites the launcher, and with it these, when any differs (17.4)."""
    want: list[tuple[str, bytes]] = [
        (identity_path(app_id), flatpak_info_text(app_id, _marker_network(gs)).encode()),
        (os.path.join(shims_dir(), "xdg-open"), XDG_OPEN_SHIM.encode()),
        (forward_path(), FORWARD_HELPER.encode())]
    if (filt := seccomp_filter()) is not None:
        want.append((seccomp_path(), filt))
    for path, data in want:
        try:
            with open(path, "rb") as f:
                if f.read() != data:
                    return False
        except OSError:
            return False
    return os.access(os.path.join(shims_dir(), "xdg-open"), os.X_OK)


def write_launcher(app_id: str, name: str, apps_root: str, appdir: str, exec_rel: str, gs: dict,
                   appimage_path: str | None = None) -> str:
    """Write `<apps_root>/<app>/run`, the identity marker and the shared helpers it calls, and return
    the launcher path (17.4)."""
    write_flatpak_info(app_id, network=_marker_network(gs))
    write_seccomp_filter()
    write_forward_helper()
    write_shims()
    path = launcher_path(app_id, apps_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Written beside and renamed over, never truncated in place: every running instance of the app
    # is a waiting `sh` with this file open that has yet to read its teardown, and a sandbox change,
    # an update or the startup pass rewrites it while apps run. Truncating the inode made such a shell
    # find EOF (no teardown, exit 0, the socket left behind) or read the new text at its old offset
    # (round five, R5-3). The old inode stays whole for the shells that hold it.
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        f.write(launcher_text(app_id, name, apps_root, appdir, exec_rel, gs, appimage_path))
    os.chmod(tmp, 0o755)
    os.replace(tmp, path)
    return path


# -------------------------------------------------------------------------- AppImage extraction (17.7)

def extracted_dir(appdir_parent: str, version: str) -> str:
    """Where a sandboxed AppImage is extracted: beside the kept `.AppImage` (17.7). Derived cache."""
    from .install import _safe
    return os.path.join(appdir_parent, _safe(version) + ".extracted")


def appimage_exec(extracted: str) -> str:
    """The program to run from an extracted AppImage, relative to the extracted dir (17.7). The
    AppImage spec puts `AppRun` at the root of squashfs-root, so it's always that. Extraction is
    lazy, in the launcher itself (`_EXTRACT_BLOCK`), so `extracted` need not exist yet."""
    return "AppRun"
