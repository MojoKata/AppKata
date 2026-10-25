"""App metadata from a repository: icon, hero image, summary (requirement 3)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

BADGE = re.compile(r"shields\.io|badge|travis-ci|circleci|codecov|coveralls|/workflows/|actions/workflow|"
                   r"liberapay\.com/assets|ko-fi|buymeacoffee|opencollective\.com/.+/(backers|sponsors)|"
                   r"repology|flathub.*badge|get-it-on|download-on|weblate|translate\.|hosted\.weblate|"
                   r"img\.shields|snapcraft\.io/static|f-droid\.org/badge|github\.com/.+/raw/.+/badges?/", re.I)
IMG_MD = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
IMG_HTML = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
RASTER = re.compile(r"\.(png|jpe?g|webp|gif|svg)(\?.*)?$", re.I)


def summary(markdown: str, fallback: str = "") -> str:
    """The README's first prose paragraph (requirement 3.4.1)."""
    text = re.sub(r"<!--.*?-->", "", markdown or "", flags=re.S)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    paras, cur = [], []
    for line in text.splitlines():
        if line.strip():
            cur.append(line.strip())
        elif cur:
            paras.append(cur); cur = []
    if cur:
        paras.append(cur)
    for p in paras:
        p = [l for l in p if not re.match(r"^\[[^\]]+\]:\s*\S", l)]       # link reference definitions
        if not p:
            continue
        first = p[0]
        if first.startswith(("..", "|", ":")) or re.match(r"^[=\-~^*`#]{3,}$", first):  # reStructuredText markup
            continue
        if first.startswith(("#", "|", ">", "- ", "* ", "+ ", "===", "---", "[!", "<p", "<h", "<div", "<img", "<a ", "<picture", ":::")) \
           or re.match(r"^\d+\.\s", first) or re.match(r"^(=+|-+)$", p[-1]) and len(p) <= 2:
            continue
        joined = " ".join(p)
        stripped = IMG_MD.sub("", joined)
        stripped = re.sub(r"<[^>]+>", "", stripped)
        stripped = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", stripped)        # links → text
        stripped = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", stripped)
        stripped = re.sub(r"[*_`]{1,3}", "", stripped).strip()
        if len(re.sub(r"[^A-Za-z]", "", stripped)) < 20 or \
                (len(re.findall(r"\s[•·|]\s", stripped)) >= 2 and len(stripped.split()) < 16):   # badges, nav links
            continue
        return re.sub(r"\s+", " ", stripped)
    return fallback


def readme_images(markdown: str, hero: bool = True) -> list[str]:
    urls = IMG_MD.findall(markdown or "") + IMG_HTML.findall(markdown or "")
    out = [u for u in urls if not BADGE.search(u) and RASTER.search(u.split("#")[0])]
    if hero:      # a logo, sponsor badge or diagram isn't a hero image; screenshots are
        out = [u for u in out if not re.search(r"(logo|icon|avatar|favicon)[^/]*$|sponsor|backer|diagram|hierarch|architecture|"
                                               r"flowchart|graph", u.split("?")[0], re.I)]
        out.sort(key=lambda u: (not re.search(r"screen|shot|preview|demo|showcase|ui[-_.]|app[-_.]", u, re.I),
                                u.lower().split("?")[0].endswith(".svg")))
    return out


def resolve(url: str, raw_base: str, readme_dir: str = "") -> str:
    """Relative README links against the raw-file URL (requirement 3.4)."""
    if re.match(r"^[a-z]+://", url, re.I) or url.startswith("data:"):
        if "github.com/" in url and "/blob/" in url:
            return url.replace("github.com/", "raw.githubusercontent.com/", 1).replace("/blob/", "/", 1)
        return url
    path = url.lstrip("/") if url.startswith("/") else (readme_dir + "/" + url if readme_dir else url)
    parts = []
    for seg in path.split("/"):
        if seg == "..":
            parts and parts.pop()
        elif seg not in ("", "."):
            parts.append(seg)
    return raw_base.rstrip("/") + "/" + "/".join(parts)


ICON_NAMES = re.compile(r"(^|/)(icon|logo|app[-_]?icon|appicon|[\w.-]*?(?:logo|icon))[-_@]?(\d+x\d+|\d+|square|round|hd)?\.(svg|png)$", re.I)
SKIP_PATHS = re.compile(r"(^|/)(node_modules|vendor|third[-_]?party|thirdparty|external|deps|tests?|docs?/api|"
                        r"\.github/ISSUE|fixtures|examples?|demo|plugins?|addons?|extensions?|i18n|po|translations?)/", re.I)


def icon_candidates(paths: list[str], name: str = "") -> list[str]:
    """Repository files that are probably the app icon, best first (requirement 3.2)."""
    low = name.lower().replace(" ", "")
    scored = []
    for p in paths:
        if SKIP_PATHS.search(p):
            continue
        lp = p.lower()
        s = None
        if re.search(r"fastlane/metadata/[^/]+/[^/]+/images/icon\.png$", lp):
            s = 0
        elif ICON_NAMES.search(p) or (low and re.search(rf"(^|/){re.escape(low)}\.(svg|png)$", lp)):
            s = 10
            if lp.endswith(".svg"):
                s -= 5
            m = re.search(r"(\d+)x(\d+)", lp) or re.search(r"[-_@](\d+)\.png$", lp)
            if m:
                px = int(m.group(1))
                s -= min(px, 512) / 128
            depth = p.count("/")
            s += depth * 0.5
            if re.search(r"(icons?|logos?|assets|data|resources|res|images?|img|art|branding|media|share)/", lp):
                s -= 1
            if re.search(r"symbolic|mono|white|black|dark|light|tray|favicon|small|16|22|24", lp):
                s += 4
            if re.search(r"(^|/)(docs?|sphinx|website|site|www|web|blog|press)/", lp):     # documentation logos
                s += 4
            if re.search(r"linux/icons|appiconset|hicolor|/apps/|packaging|flatpak|snap/gui", lp):  # the shipped app icon
                s -= 2
            if low and low in lp.replace("-", "").replace("_", ""):
                s -= 2
            stem = re.sub(r"[-_@]?(\d+x\d+|\d+)$", "", lp.rsplit("/", 1)[-1].rsplit(".", 1)[0])
            tokens = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) >= 3]
            if stem not in ("icon", "logo", "appicon", "app-icon", "app_icon", "app") and \
                    not any(t in stem for t in tokens + ([low] if low else [])):
                s += 5          # "alert-icon", "close-icon": UI icons, not the app's
            if re.search(r"(^|/)build/icons?\.(png|svg)$|(^|/)build/icons/", lp):     # electron-builder's app icon
                s -= 2
        elif re.search(r"(^|/)(hicolor|icons)/(scalable|512x512|256x256)/apps/[^/]+\.(svg|png)$", lp):
            s = 6
        if s is not None:
            scored.append((s, p))
    scored.sort()
    return [p for _, p in scored]


def hero_candidates(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        lp = p.lower()
        if re.search(r"fastlane/metadata/[^/]+/[^/]+/images/featuregraphic\.(png|jpe?g)$", lp):
            out.insert(0, p)
        elif re.search(r"(^|/)(screenshot|screenshots|preview|banner|hero|social[-_]?preview)[^/]*\.(png|jpe?g|webp)$", lp) \
                and not SKIP_PATHS.search(p) and not re.search(r"/res/|drawable|mipmap|\.xcassets/", lp):
            out.append(p)
    return out


def metainfo_paths(paths: list[str]) -> list[str]:
    return [p for p in paths if re.search(r"\.(metainfo|appdata)\.xml(\.in)?$", p, re.I) and not SKIP_PATHS.search(p)]


def parse_metainfo(xml: str) -> dict:
    """name, summary, icon (remote URL), screenshot URL and id from AppStream metainfo."""
    out: dict = {}
    try:
        root = ET.fromstring(re.sub(r"<\?xml[^>]*\?>", "", xml, count=1).strip())
    except ET.ParseError:
        return out
    def first(tag):      # the component's own element, not <developer><name> and the like
        for el in root.findall(tag):
            if not el.attrib.get("{http://www.w3.org/XML/1998/namespace}lang"):
                return (el.text or "").strip()
        return ""
    out["id"] = first("id")
    out["name"] = first("name")
    out["summary"] = first("summary")
    for el in root.iter("icon"):
        if el.attrib.get("type") == "remote" and el.text:
            out["icon"] = el.text.strip()
            break
    for shot in root.iter("screenshot"):
        img = next((i for i in shot.iter("image") if i.text and i.attrib.get("type", "source") == "source"), None)
        if img is not None:
            out["screenshot"] = img.text.strip()
            if shot.attrib.get("type") == "default":
                break
    return out
