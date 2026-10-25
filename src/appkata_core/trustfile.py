"""The AppKata.md trust file: parsing (requirement 10.1–10.4) and editing a review (8.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cmp_to_key

from . import versions
from .urls import try_normalize

COLUMNS = ["app", "source", "tags", "trust", "rating"]
HEADER = "| App | Source | Tags | Trust | Rating |\n|---|---|---|---|---|"
TAG_RE = re.compile(r"^[a-z][a-z0-9]*$")
PREDEFINED_TAGS = ["foss", "donation", "freemium", "saas", "spyware", "malware", "ads", "tracking", "nonfreenet",
                   "nonfreedep", "nonfreeassets", "upstreamnonfree", "knownvuln", "unmaintained", "archived", "nsfw",
                   "reproducible", "signed", "offline", "portable"]
WARNING_TAGS = {"spyware", "malware", "ads", "tracking", "knownvuln"}
TAG_MEANINGS = {
    "foss": "Free and open source", "donation": "The author accepts donations", "freemium": "Free, with paid features",
    "saas": "An account is required to use the app", "spyware": "Collects data about the user without consent",
    "malware": "Harmful or malicious", "ads": "Shows advertising", "tracking": "Telemetry or analytics",
    "nonfreenet": "Relies on a non-free network service", "nonfreedep": "Depends on non-free components",
    "nonfreeassets": "Artwork or data under a non-free license",
    "upstreamnonfree": "Upstream contains non-free parts that are stripped out",
    "knownvuln": "Has a known, unfixed vulnerability", "unmaintained": "No upstream activity for a long time",
    "archived": "The repository is archived", "nsfw": "Adult content", "reproducible": "Reproducible builds verified",
    "signed": "Release binaries are signed or have checksums", "offline": "Works fully without a network",
    "portable": "Runs without installation",
}


# "## <App>::Settings" and "### <App>[<version>]::Settings" (requirement 10.3.1): a review's Trust,
# Rating and Tags, its recommended install options (4.3.1, 4.10), the Source settings that are about the
# app rather than the user (forge and download filter, 2.6), and its package channels (16.1.3); Track only
# and pre-releases are personal, so not here. Each line is "- <Option>: <value>" or
# "- <Option> (<platform>): <value>"; a platform line overrides the line without one there.
SETTINGS_KEYS = {"app menu": "appMenu", "command link": "commandLink", "stable name link": "stableName",
                 "forge": "forge", "download filter": "assetFilter", "auto update": "autoUpdate", "auto updates": "autoUpdate",
                 "flatpak": "flatpak", "debian package": "debianPackage", "fedora package": "fedoraPackage", "channel": "channel",
                 "sandbox": "sandbox", "sandbox folders": "sandboxFolders", "sandbox network": "sandboxNetwork",
                 "sandbox sound": "sandboxSound", "sandbox devices": "sandboxDevices", "sandbox services": "sandboxServices",
                 "sandbox app folder": "sandboxAppFolder"}
SETTINGS_LABELS = {"appMenu": "App menu", "commandLink": "Command link", "stableName": "Stable name link",
                   "forge": "Forge", "assetFilter": "Download filter", "autoUpdate": "Auto update",
                   "flatpak": "Flatpak", "debianPackage": "Debian package", "fedoraPackage": "Fedora package", "channel": "Channel",
                   "sandbox": "Sandbox", "sandboxFolders": "Sandbox folders", "sandboxNetwork": "Sandbox network",
                   "sandboxSound": "Sandbox sound", "sandboxDevices": "Sandbox devices", "sandboxServices": "Sandbox services",
                   "sandboxAppFolder": "Sandbox app folder"}
SETTINGS_ORDER = ("appMenu", "commandLink", "stableName", "forge", "assetFilter", "autoUpdate",
                  "flatpak", "debianPackage", "fedoraPackage", "channel",
                  "sandbox", "sandboxFolders", "sandboxNetwork", "sandboxSound", "sandboxDevices", "sandboxServices",
                  "sandboxAppFolder")
# The suggested sandbox template, and each kind of grant changed from it (17.3, 10.3.1); Linux-only.
# Kept equal to sandbox.TEMPLATE_ORDER (a test checks), without importing the sandbox module here.
SANDBOX_TEMPLATES = ("strict", "standard", "offline-editor", "online-app", "messenger", "media-player", "developer", "cli-tool")
# The words each sandbox set line knows, equal to sandbox.LINE_NAMES (a test checks), as above
SANDBOX_SETS = {"sandboxSound": {"play", "record"}, "sandboxDevices": {"camera", "x11", "xwayland"},
                "sandboxServices": {"notifications", "keep-awake", "inhibit", "tray", "media-keys", "mpris", "passwords",
                                    "secrets", "password-service", "secrets-provide"}}
VERDICT = ("trust", "rating", "tags")          # a review's own values, never platform-specific (10.3.1)
CHANNELS = ("release", "flatpak", "package")
FORGE_NAMES = {"github": "github", "github enterprise": "ghe", "ghe": "ghe", "gitlab": "gitlab", "forgejo": "forgejo",
               "codeberg": "forgejo", "gitea": "gitea"}
FORGE_WRITE = {"github": "github", "ghe": "github enterprise", "gitlab": "gitlab", "forgejo": "forgejo", "gitea": "gitea"}
_FLATPAK = re.compile(r"^(?:[A-Za-z0-9_.-]+\s+)?[A-Za-z][\w-]*(?:\.[\w-]+){2,}$")
_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+._-]*$")


def _setting_value(key: str, raw: str):
    """A Settings line's value, or None when it isn't valid for that option."""
    raw = raw.strip()
    if key == "assetFilter":            # a regex, best written in backticks so Markdown leaves it alone
        rx = raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == "`" else raw
        try:
            re.compile(rx)
        except re.error:
            return None
        return rx
    if key == "forge":
        return FORGE_NAMES.get(raw.strip("`").lower())
    if key == "flatpak":
        v = " ".join(raw.strip("`").split())
        return v if _FLATPAK.match(v) else None
    if key in ("debianPackage", "fedoraPackage"):
        v = raw.strip("`").strip()
        return v if _PACKAGE.match(v) else None
    if key == "channel":
        v = raw.strip("`").strip().lower()
        return v if v in CHANNELS else None
    if key == "sandbox":                 # a template name or "off" (17.3)
        v = raw.strip("`").strip().lower()
        return v if v in SANDBOX_TEMPLATES or v == "off" else None
    if key == "sandboxFolders":          # kept as written; parsed by sandbox.parse_folders (17.3.1)
        v = raw.strip("`").strip()
        return v or None
    if key in SANDBOX_SETS:              # kept as written, its known words only; parsed by sandbox.parse_set
        words = [w.strip() for w in raw.strip("`").split(",") if w.strip()]
        ok = [w for w in words if w.lower().lstrip("+-") in SANDBOX_SETS[key] or w.lower() == "none"]
        return ", ".join(ok) or None
    v = raw.split()[0].lower() if raw else ""
    return True if v in ("yes", "true", "on", "1") else False if v in ("no", "false", "off", "0") else None
# platform names in AppKata.md → the internal values (LINUX, WIN, MAC), and back
PLATFORM_NAMES = {"linux": "LINUX", "win": "WIN", "windows": "WIN", "mac": "MAC", "macos": "MAC"}
PLATFORM_WRITE = {"LINUX": "linux", "WIN": "windows", "MAC": "macos"}
PLATFORM_OF_OS = {"linux": "LINUX", "windows": "WIN", "macos": "MAC"}
_SETTING_LINE = re.compile(r"^\s*[-*]\s*([^:(]+?)\s*(?:\(\s*([A-Za-z]+)\s*\))?\s*:\s*(.+?)\s*$")


def settings_heading(app: str, version: str = "") -> str:
    return f"### {app}[{version}]::Settings" if version else f"## {app}::Settings"


def _parse_block(lines: list[str], where: str = "") -> tuple[dict, dict, list[str]]:
    """A Settings sub-section's lines: (options as {"appMenu": True, …, "platforms": {"WIN": {…}}},
    the review's own Trust/Rating/Tags, parse warnings). Unknown options and platforms are ignored."""
    out: dict = {}
    verdict: dict = {}
    warns: list[str] = []
    for l in lines:
        m = _SETTING_LINE.match(l)
        if not m:
            continue
        name = m.group(1).strip().lower()
        if name in VERDICT:
            if m.group(2):
                warns.append(f"{where}: a platform on “{m.group(1).strip()}” is ignored.")
                continue
            if name == "tags":
                tags = [t.strip().lower() for t in m.group(3).split(",") if t.strip()]
                bad = [t for t in tags if not TAG_RE.match(t)]
                if bad:
                    warns.append(f"{where}: invalid tag{'s' if len(bad) > 1 else ''} {', '.join(bad)}.")
                    continue
                verdict["tags"] = list(dict.fromkeys(tags))
            else:
                try:
                    verdict[name] = parse_value(m.group(3))
                except ValueError as e:
                    warns.append(f"{where}: “{e}” isn't a value from 0 to 5.")
            continue
        key = SETTINGS_KEYS.get(name)
        if not key:
            continue
        value = _setting_value(key, m.group(3))
        if value is None:
            continue
        if m.group(2):
            plat = PLATFORM_NAMES.get(m.group(2).lower())
            if plat:
                out.setdefault("platforms", {}).setdefault(plat, {})[key] = value
        else:
            out[key] = value
    return out, verdict, warns


def _is_heading(line: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S", line))


def _section_blocks(app: str, lines: list[str]) -> list[tuple[str, str, int, int]]:
    """The parts of an app's section (requirement 10.3), the lines after its `# <App>` heading:
    (kind, version, start, end). Kinds: "app" (the app review's text), "appsettings", "version"
    (from its `## <App>[<version>]` heading), "details", "vsettings", and "text": other text after a
    Settings or Details list, which belongs to the review before it (its version, or "" for the app)."""
    a = re.escape(app)
    rx_set = re.compile(rf"^##\s+{a}\s*::\s*Settings\s*#*\s*$", re.I)
    rx_ver = re.compile(rf"^##\s+{a}\s*\[([^\]]*)\]\s*#*\s*$", re.I)
    rx_sub = re.compile(rf"^###\s+{a}\s*\[([^\]]*)\]\s*::\s*(Details|Settings)\s*#*\s*$", re.I)
    blocks: list[tuple[str, str, int, int]] = []
    kind, ver, start, owner, in_code = "app", "", 0, "", False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        if rx_set.match(line):
            new = ("appsettings", "")
        elif (m := rx_ver.match(line)):
            new = ("version", m.group(1).strip())
        elif (m := rx_sub.match(line)):
            new = ("details" if m.group(2).lower() == "details" else "vsettings", m.group(1).strip())
        elif kind in ("appsettings", "details", "vsettings") and _is_heading(line):
            new = ("text", owner)
        else:
            continue
        blocks.append((kind, ver, start, i))
        kind, ver, start = new[0], new[1], i
        if kind == "version":
            owner = ver if ver else "\0"
        elif kind == "appsettings":
            owner = ""
    blocks.append((kind, ver, start, len(lines)))
    return blocks


def _details_lines(lines: list[str]) -> list[list[str]]:
    out = []
    for l in lines:
        m = re.match(r"^\s*[-*]\s*([^:]+?)\s*:\s*(.*?)\s*$", l)
        if m:
            out.append([m.group(1), m.group(2)])
    return out


def parse_section(app: str, section: str) -> tuple[dict, list[str]]:
    """An app's section (requirement 10.3): ({"text": the app review's text, "opts": its options,
    "verdict": its own Trust/Rating/Tags, "versions": [{"v", "text", "details", "opts", "verdict"}]},
    parse warnings). Version reviews are in file order."""
    lines = (section or "").splitlines()
    out = {"text": [], "opts": {}, "verdict": {}, "versions": []}
    vers: dict[str, dict] = {}
    warns: list[str] = []
    subs = []
    for kind, v, s, e in _section_blocks(app, lines):
        if kind == "app":
            out["text"] += lines[s:e]
        elif kind == "text":
            if v == "":
                out["text"] += lines[s:e]
            elif v in vers:
                vers[v]["text"] += lines[s:e]
        elif kind == "appsettings":
            opts, verdict, w = _parse_block(lines[s + 1:e], f"{app}::Settings")
            out["opts"] = merge_settings(out["opts"], {k: x for k, x in opts.items() if k != "platforms"}, "")
            for p, d in (opts.get("platforms") or {}).items():
                out["opts"].setdefault("platforms", {}).setdefault(p, {}).update(d)
            out["verdict"].update(verdict)
            warns += w
        elif kind == "version":
            if not v:
                warns.append(f"“## {app}[]” names no version; it's ignored.")
            elif v in vers:
                warns.append(f"“{app}” has two reviews of {v}; the second is ignored.")
            else:
                vers[v] = {"v": v, "text": lines[s + 1:e], "details": [], "opts": {}, "verdict": {}}
                out["versions"].append(vers[v])
        else:
            subs.append((kind, v, s, e))
    for kind, v, s, e in subs:
        label = "Details" if kind == "details" else "Settings"
        if v not in vers:
            warns.append(f"“### {app}[{v}]::{label}” names no review of {app}; it's ignored.")
        elif kind == "details":
            vers[v]["details"] += _details_lines(lines[s + 1:e])
        else:
            opts, verdict, w = _parse_block(lines[s + 1:e], f"{app}[{v}]::Settings")
            vers[v]["opts"], vers[v]["verdict"] = opts, verdict
            warns += w
    out["text"] = "\n".join(out["text"]).strip("\n")
    for r in out["versions"]:
        r["text"] = "\n".join(r["text"]).strip("\n")
    return out, warns


def split_settings(app: str, section: str) -> tuple[str, dict]:
    """(the app review's text, its options), without version reviews (requirement 10.3, 10.3.1)."""
    p, _ = parse_section(app, section)
    return p["text"], p["opts"]


def _resolve_block(settings: dict, os_name: str) -> dict:
    out = {k: v for k, v in (settings or {}).items() if k != "platforms" and not k.startswith("_")}
    out.update(((settings or {}).get("platforms") or {}).get(PLATFORM_OF_OS.get(os_name, ""), {}))
    return out


def resolve_settings(settings: dict, os_name: str, version: str | None = None, dates: dict | None = None) -> dict:
    """The options that apply on this platform ("linux", "windows", "macos"): a platform's own
    line wins over the line without one. With version reviews, the options carried to `version`
    (the newest review when None; requirement 10.3.3, 10.3.5)."""
    if (settings or {}).get("_versions"):
        return review_for(settings, None, version, os_name, dates)["opts"]
    return _resolve_block(settings, os_name)


def _cmp(a: str, b: str, dates: dict | None) -> int | None:
    """Two versions compared as in 9.4; a version that isn't semver-like by its release's date."""
    c = versions.compare(a, b)
    if c is None and dates and dates.get(a) and dates.get(b):
        c = (dates[a] > dates[b]) - (dates[a] < dates[b])
    return c


def ordered_versions(revs: list[dict], dates: dict | None = None) -> list[dict]:
    return sorted(revs, key=cmp_to_key(lambda x, y: _cmp(x["v"], y["v"], dates) or 0))


def reviews_over_versions(settings: dict, table: dict | None, os_name: str, dates: dict | None = None) -> list[dict]:
    """A Trust's reviews of an app, the app review first, then its version reviews in version order,
    each with the Trust, Rating, Tags and options that apply from its version on (requirement 10.3.3):
    a review's own line, else the value carried from the review before it. The app review without
    its own Trust/Rating/Tags takes them from the earliest version review that has them, else the
    table row; the table row is the newest review's. table: {"trust", "rating", "tags"} or None."""
    s = settings or {}
    vers = ordered_versions(list(s.get("_versions") or []), dates)
    own = dict(s.get("_app") or {})
    for k in VERDICT:
        if k not in own:
            first = next((r["verdict"][k] for r in vers if k in (r.get("verdict") or {})), _NONE)
            if first is not _NONE:
                own[k] = first
            elif table and k in table:
                own[k] = table[k]
    chain = [{"version": "", "text": "", "details": [], "own": dict(s.get("_app") or {}),
              "trust": own.get("trust"), "rating": own.get("rating"), "tags": list(own.get("tags") or []),
              "opts": _resolve_block(s, os_name)}]
    for r in vers:
        prev, mine = chain[-1], r.get("verdict") or {}
        chain.append({"version": r["v"], "text": r.get("text", ""), "details": r.get("details") or [], "own": dict(mine),
                      **{k: (list(mine[k]) if k == "tags" else mine[k]) if k in mine else prev[k] for k in VERDICT},
                      "opts": {**prev["opts"], **_resolve_block(r.get("opts") or {}, os_name)}})
    if table is not None:
        chain[-1].update({k: table[k] for k in VERDICT if k in table})
    return chain


_NONE = object()


def review_for(settings: dict, table: dict | None, version: str | None, os_name: str, dates: dict | None = None,
               chain: list[dict] | None = None) -> dict:
    """A Trust's review that applies to `version` (requirement 10.3.5): its newest version review
    of that version or older, else its app review. A version that can't be placed matches only a
    review of exactly that version, else gets the newest review; None is the newest."""
    chain = chain or reviews_over_versions(settings, table, os_name, dates)
    if version is None or len(chain) == 1:
        return chain[-1] if version is None else chain[0]
    placed = exact = None
    comparable = False
    for r in chain[1:]:
        if r["version"] == version:
            exact = r
        c = _cmp(r["version"], version, dates)
        if c is None:
            continue
        comparable = True
        if c <= 0:
            placed = r
    return placed or exact or (chain[0] if comparable else chain[-1])


def verdict_lines(trust: int | None, rating: int | None, tags: list[str]) -> list[str]:
    out = []
    if trust is not None:
        out.append(f"- Trust: {trust}")
    if rating is not None:
        out.append(f"- Rating: {rating}")
    if tags:
        out.append(f"- Tags: {', '.join(tags)}")
    return out


# options whose right value depends on the platform; the review dialog writes them for this one.
# The Sandbox* lines are Linux-only (10.3.1), so they're written as this platform's lines too.
SANDBOX_KEYS = ("sandbox", "sandboxFolders", "sandboxNetwork", "sandboxSound", "sandboxDevices", "sandboxServices",
                "sandboxAppFolder")
PLATFORM_SPECIFIC = {"autoUpdate", "assetFilter", *SANDBOX_KEYS}


def merge_settings(old: dict, new: dict, os_name: str) -> dict:
    """The review dialog's options (this computer's, requirement 8.4.7) merged into the file's.
    Auto update and the download filter depend on the platform, so they're written as this
    platform's lines; the others become lines without a platform, and this platform's lines for
    them are dropped so the new values apply here too. Everything else in the file is kept."""
    out = {k: v for k, v in (old or {}).items() if k != "platforms"}
    plats = {p: dict(v) for p, v in ((old or {}).get("platforms") or {}).items()}
    me = PLATFORM_OF_OS.get(os_name, "")
    mine = plats.setdefault(me, {}) if me else {}
    for k, v in new.items():
        if v is None:                     # a line to drop: the sandbox is written whole (review 2, F9)
            out.pop(k, None)
            mine.pop(k, None)
        elif k in PLATFORM_SPECIFIC and me:
            mine[k] = v
        else:
            out[k] = v
            mine.pop(k, None)
    plats = {p: v for p, v in plats.items() if v}
    if plats:
        out["platforms"] = plats
    return out


def options_to_write(full: dict, version: str, new: dict, os_name: str, dates: dict | None = None) -> dict:
    """The options for a review's Settings (requirement 8.4.7): this computer's options merged
    into the review's own lines; for a version review, only those that differ from the values
    carried from the review before it (10.3.3)."""
    full = full or {}
    if not version:
        return merge_settings({k: v for k, v in full.items() if not k.startswith("_")}, new, os_name)
    vers = list(full.get("_versions") or [])
    mine = next((r for r in vers if r["v"] == version), None)
    others = {**full, "_versions": [r for r in vers if r["v"] != version]}
    carried = review_for(others, None, version, os_name, dates)["opts"] if others["_versions"] else _resolve_block(full, os_name)
    return merge_settings((mine or {}).get("opts") or {}, {k: v for k, v in new.items() if carried.get(k) != v}, os_name)


def _format_value(key: str, v) -> str:
    if key == "assetFilter":
        return f"`{v}`"
    if key == "forge":
        return FORGE_WRITE.get(v, v)
    if key in ("flatpak", "debianPackage", "fedoraPackage", "channel", "sandbox", "sandboxFolders", *SANDBOX_SETS):
        return str(v)
    return "yes" if v else "no"


def settings_rows(settings: dict) -> list[tuple[str, str, str]]:
    """(option, platform or "", line) in the order AppKata writes them: the lines without a
    platform, then each option's platform lines (LINUX, WIN, MAC)."""
    rows = [(k, "", f"- {SETTINGS_LABELS[k]}: {_format_value(k, settings[k])}") for k in SETTINGS_ORDER if k in settings]
    plats = settings.get("platforms") or {}
    for k in SETTINGS_ORDER:
        for p in ("LINUX", "WIN", "MAC"):
            if k in plats.get(p, {}):
                rows.append((k, p, f"- {SETTINGS_LABELS[k]} ({PLATFORM_WRITE[p]}): {_format_value(k, plats[p][k])}"))
    return rows


def format_settings(app: str, settings: dict, verdict: list[str] | None = None, version: str = "") -> str:
    rows = list(verdict or []) + [r[2] for r in settings_rows(settings)]
    return settings_heading(app, version) + "\n\n" + "\n".join(rows) if rows else ""


@dataclass
class Row:
    app: str
    source: str               # as written
    url: str                  # normalized (requirement 2.3)
    tags: list[str]
    trust: int | None
    rating: int | None
    line: int = 0


@dataclass
class TrustFile:
    rows: list[Row] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    # app → the app review's options, plus "_app" (its own Trust/Rating/Tags) and "_versions" (its
    # version reviews: {"v", "text", "details", "opts", "verdict"}) when there are any (requirement 10.3)
    settings: dict[str, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    has_table: bool = False

    def by_url(self) -> dict[str, Row]:
        return {r.url: r for r in self.rows}


def parse_value(cell: str) -> int | None:
    """0–5, or ⭐/★ repeated (☆ counts as empty); '' is no opinion. Raises ValueError otherwise."""
    s = cell.strip()
    if not s:
        return None
    if re.fullmatch(r"[0-5]", s):
        return int(s)
    if re.fullmatch(r"(?:⭐|★|☆|\ufe0f|\s)+", s):
        n = s.count("⭐") + s.count("★")
        if n > 5 or n + s.count("☆") > 5:
            raise ValueError(s)
        return n
    if s in ("-", "–", "—"):
        return 0
    raise ValueError(s)


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    out, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"; i += 2; continue
        if s[i] == "|":
            out.append(cur.strip()); cur = ""
        else:
            cur += s[i]
        i += 1
    out.append(cur.strip())
    return out


def _is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*", line))


def _find_table(lines: list[str]) -> tuple[int, int] | None:
    """(header line, first line after the table) of the trust table, or None."""
    in_code = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if in_code or "|" not in line or i + 1 >= len(lines):
            continue
        if [c.lower() for c in _cells(line)] == COLUMNS and _is_sep(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|") or (j < len(lines) and "|" in lines[j] and lines[j].strip()):
                j += 1
            return i, j
    return None


def parse(text: str) -> TrustFile:
    tf = TrustFile()
    lines = (text or "").splitlines()
    span = _find_table(lines)
    if not span:
        tf.warnings.append("No trust table found (expected the columns App | Source | Tags | Trust | Rating).")
        return tf
    tf.has_table = True
    seen: set[str] = set()
    for n in range(span[0] + 2, span[1]):
        c = _cells(lines[n])
        if not any(c):
            continue
        if len(c) != 5:
            tf.warnings.append(f"Line {n + 1}: expected 5 columns, found {len(c)}.")
            continue
        app, source, tags_s, trust_s, rating_s = c
        if not app:
            tf.warnings.append(f"Line {n + 1}: the App column is empty.")
            continue
        if app.lower() in seen:
            tf.warnings.append(f"Line {n + 1}: “{app}” is listed twice; the second row is skipped.")
            continue
        url = try_normalize(_unlink(source))
        if not url:
            tf.warnings.append(f"Line {n + 1}: “{source}” isn't a repository URL.")
            continue
        tags, bad = [], []
        for t in (x.strip().lower() for x in tags_s.split(",")):
            if not t:
                continue
            (tags if TAG_RE.match(t) else bad).append(t)
        if bad:
            tf.warnings.append(f"Line {n + 1}: invalid tag{'s' if len(bad) > 1 else ''} {', '.join(bad)}.")
            continue
        try:
            trust = parse_value(trust_s)
            rating = parse_value(rating_s)
        except ValueError as e:
            tf.warnings.append(f"Line {n + 1}: “{e}” isn't a value from 0 to 5.")
            continue
        seen.add(app.lower())
        tf.rows.append(Row(app, source, url, list(dict.fromkeys(tags)), trust, rating, n + 1))
    # sections: "# <App>" exactly matching an App cell (requirement 10.3)
    rows = {r.app: r for r in tf.rows}
    cur, buf = None, []
    def flush():
        if cur is not None:
            if cur in rows:
                p, warns = parse_section(cur, "\n".join(buf).strip("\n"))
                tf.warnings.extend(warns)
                tf.sections[cur] = p["text"]
                opts = dict(p["opts"])
                if p["verdict"]:
                    opts["_app"] = p["verdict"]
                if p["versions"]:
                    opts["_versions"] = p["versions"]
                if opts:
                    tf.settings[cur] = opts
                # the table row is the newest review's Trust, Rating and Tags (10.3.3)
                newest = ordered_versions(p["versions"])[-1]["verdict"] if p["versions"] else p["verdict"]
                row = rows[cur]
                differ = [k for k in VERDICT if k in newest and newest[k] != getattr(row, k)]
                if differ:
                    tf.warnings.append(f"“{cur}”: the newest review's {', '.join(differ)} differ{'s' if len(differ) == 1 else ''}"
                                       " from the table row; the table row is used.")
            else:
                tf.warnings.append(f"Section “# {cur}” has no row in the table; it's ignored.")
    in_code = False
    for n, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if n < span[1]:          # a title above the table isn't a review section
            continue
        m = None if in_code else re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if m:
            flush()
            cur, buf = m.group(1), []
        elif cur is not None:
            buf.append(line)
    flush()
    return tf


def _unlink(s: str) -> str:
    m = re.fullmatch(r"\[[^\]]*\]\(([^)]+)\)|<([^>]+)>", s.strip())
    return (m.group(1) or m.group(2)) if m else s


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def format_row(app: str, source: str, tags: list[str], trust: int | None, rating: int | None) -> str:
    v = lambda x: "" if x is None else str(x)
    return f"| {_cell(app)} | {_cell(source)} | {', '.join(tags)} | {v(trust)} | {v(rating)} |"


def _section_span(lines: list[str], app: str) -> tuple[int | None, int]:
    """(the `# <App>` heading line, the line after its section), or (None, len)."""
    start, in_code = None, False
    for n, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(rf"^#\s+{re.escape(app)}\s*#*\s*$", line):
            start = n
            break
    if start is None:
        return None, len(lines)
    in_code = False
    for n in range(start + 1, len(lines)):
        if lines[n].lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#\s+\S", lines[n]):
            return start, n
    return start, len(lines)


def _tidy(lines: list[str]) -> list[str]:
    """No blank lines at either end, and no runs of them (outside code blocks)."""
    out, in_code = [], False
    for l in lines:
        if l.lstrip().startswith("```"):
            in_code = not in_code
        if not in_code and not l.strip() and (not out or not out[-1].strip()):
            continue
        out.append(l)
    while out and not out[-1].strip():
        out.pop()
    return out


def set_review(text: str, app: str, source: str, tags: list[str], trust: int | None, rating: int | None,
               section: str, settings: dict | None = None, version: str = "", details: list[list[str]] | None = None,
               dates: dict | None = None) -> str:
    """Write one review, leaving the rest of the file as it was (requirement 8.5): the app review
    (`# <App>` text and `## <App>::Settings`), or with `version` that version review (its text,
    Details and Settings), added after the app's other version reviews in version order. The
    Settings always hold the review's Trust, Rating and Tags (8.4.7); `settings` are its options.
    The table row is updated when the review is the app's newest; adding the first version review
    first writes the table row's values into `## <App>::Settings` when it has none of its own.
    details: [[line, value]]; None keeps the review's Details."""
    lines = (text or "").splitlines()
    url = try_normalize(source)
    tags = [t.lower() for t in tags]
    span = _find_table(lines)
    if not span:
        intro = ["# AppKata reviews", ""] if not any(l.strip() for l in lines) else []
        lines = intro + HEADER.splitlines() + [""] + lines
        span = _find_table(lines)
    hit = None
    for n in range(span[0] + 2, span[1]):
        c = _cells(lines[n])
        if len(c) == 5 and (c[0].lower() == app.lower() or (url and try_normalize(_unlink(c[1])) == url)):
            hit = n
            break
    old_row = None
    if hit is not None:
        c = _cells(lines[hit])
        try:
            old_row = {"trust": parse_value(c[3]), "rating": parse_value(c[4]),
                       "tags": [t.strip().lower() for t in c[2].split(",") if t.strip()]}
        except ValueError:
            old_row = None
    start, end = _section_span(lines, app)
    sec = lines[start + 1:end] if start is not None else []
    blocks = _section_blocks(app, sec)
    have = [v for k, v, _, _ in blocks if k == "version" and v]
    verdict = verdict_lines(trust, rating, tags)
    body = (section or "").strip("\n").splitlines()
    if not version:
        mine = [b for b in blocks if b[0] in ("app", "appsettings") or (b[0] == "text" and b[1] == "")]
        keep = [l for i, l in enumerate(sec) if not any(s0 <= i < e0 for _, _, s0, e0 in mine)]
        head = body + [""]
        st = format_settings(app, settings or {}, verdict)
        if st:
            head += st.splitlines() + [""]
        sec = head + keep
        newest = not have
    else:
        mine = [b for b in blocks if b[1] == version and b[0] in ("version", "text", "details", "vsettings")]
        old_details = next(([l for l in sec[s0 + 1:e0]] for k, _, s0, e0 in mine if k == "details"), None)
        at = next((s0 for k, _, s0, _ in mine if k == "version"), None)
        if at is None:          # a new review: before the first one of a later version, else at the end
            later = [s0 for k, v, s0, _ in blocks if k == "version" and v and (_cmp(v, version, dates) or 0) > 0]
            at = min(later) if later else len(sec)
        removed = sum(e0 - s0 for _, _, s0, e0 in mine if s0 < at)
        rest = [l for i, l in enumerate(sec) if not any(s0 <= i < e0 for _, _, s0, e0 in mine)]
        at -= removed
        group = [f"## {app}[{version}]", ""] + (body + [""] if body else [])
        if details is not None:
            if details:
                group += [f"### {app}[{version}]::Details", ""] + [f"- {k}: {v}" for k, v in details] + [""]
        elif old_details:
            group += [f"### {app}[{version}]::Details"] + old_details + [""]
        st = format_settings(app, settings or {}, verdict, version)
        if st:
            group += st.splitlines() + [""]
        rest[at:at] = [""] + group
        sec = rest
        if not have and old_row:          # the first version review: the app review keeps its values (8.5)
            sb = _section_blocks(app, sec)
            aset = next((b for b in sb if b[0] == "appsettings"), None)
            own = _parse_block(sec[aset[2] + 1:aset[3]])[1] if aset else {}
            add = [l for l in verdict_lines(old_row["trust"], old_row["rating"], old_row["tags"])
                   if l.split(":")[0][2:].lower() not in own]
            if add:
                if aset:
                    sec[aset[2] + 1:aset[2] + 1] = [""] + add
                else:
                    first = next((b[2] for b in sb if b[0] == "version"), len(sec))
                    sec[first:first] = [settings_heading(app), ""] + add + [""]
        newest = all((_cmp(v, version, dates) or 0) <= 0 for v in have if v != version)
    sec = _tidy(sec)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"# {app}", ""] + sec
    else:
        lines[start:end] = [f"# {app}", ""] + sec + ([""] if end < len(lines) else [])
    row = format_row(app, source, tags, trust, rating) if newest or old_row is None else None
    if row:
        if hit is None:
            span = _find_table(lines)
            lines.insert(span[1], row)
        else:
            lines[hit] = row
    return "\n".join(lines).rstrip("\n") + "\n"
