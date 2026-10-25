"""--tour: drive the real UI through the mockup screens and save screenshots (screenshots/README.md)."""

from __future__ import annotations

import os

from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from appkata_core import APPKATA_REPO

from . import layout

# (name, step, delay ms); urls refer to the demo data (scripts/demo_data.py)
GH = "https://github.com/"
MB = 1_000_000
# the design point (requirement 5.2.1): AppKata maximized on a 1920 x 1080 screen. On Windows the window
# takes what the screen leaves beside the taskbar, as maximized (scripts/test-windows-vm.sh sets the VM's
# screen to 1920 x 1080 first); offscreen, with no taskbar or panel, the size that leaves
DESIGN = (1920, 1040)
BUSY = {GH + "localsend/localsend": {"phase": "Downloading", "progress": 0.45, "got": 41.4 * MB, "total": 92 * MB, "speed": 3.4 * MB},
        GH + "VSCodium/vscodium": {"phase": "Waiting", "progress": 0, "got": 0, "total": 0, "speed": 0},
        APPKATA_REPO: {"phase": "Waiting", "progress": 0, "got": 0, "total": 0, "speed": 0}}
STEPS = [
    ("A01-apps", {"view": "apps", "hoverTrash": GH + "keepassxreboot/keepassxc"}, 1500),
    ("A02-apps-detail", {"view": "apps", "detail": GH + "localsend/localsend", "pencilHover": True, "expanded": 0}, 1800),
    ("A03-review-dialog", {"view": "apps", "detail": GH + "localsend/localsend", "review": GH + "localsend/localsend",
                           "reviewSet": {"version": "", "autoCommit": True, "autoPush": True}}, 1500),
    ("A04-review-avoid-unsigned", {"view": "apps", "detail": GH + "signalapp/Signal-Desktop", "review": GH + "signalapp/Signal-Desktop",
                                   "reviewSet": {"tags": ["saas", "tracking"], "trust": 0, "rating": 2, "autoCommit": True, "autoPush": True,
                                                 "text": "Needs a phone number and a Signal account; the desktop app\ncan't be used on its own.\n\n"
                                                         "- Crash reports go to a hosted endpoint by default.\n"
                                                         "- **My call:** avoid until linking works without a phone.",
                                                 "result": {"saved": True, "committed": "4e1c9a2", "signed": False, "pushed": False,
                                                            "error": "Commit 4e1c9a2 isn't signed, so it wasn't pushed."}}}, 1500),
    ("A05-apps-detail-versions", {"view": "apps", "detail": GH + "Zettlr/Zettlr", "scrollDetail": "versions", "versionsMore": True, "versionTip": 5}, 1800),
    ("A06-appkata-restart", {"view": "apps", "detail": APPKATA_REPO, "selfUpdated": True}, 1800),
    # installing (requirement 4.8): one download, the rest queued; the App Detail panel with Cancel
    ("A07-apps-installing", {"view": "apps", "busy": BUSY}, 1500),
    ("A08-apps-detail-installing", {"view": "apps", "detail": GH + "localsend/localsend", "busy": BUSY}, 1800),
    ("A09-app-updates-itself", {"view": "apps", "detail": GH + "syncthing/syncthing"}, 1800),
    ("A10-confirm-uninstall", {"view": "apps", "confirm": ["uninstall", {"url": GH + "keepassxreboot/keepassxc"}]}, 1300),
    # version reviews (requirement 10.6.5, 8.4.1.1): an installed version a Trust avoids; a new review of the installed version
    ("A18-apps-version-avoided", {"view": "apps", "detail": GH + "tukaani-project/xz", "expanded": 0}, 1800),
    ("A19-review-dialog-version", {"view": "apps", "detail": GH + "localsend/localsend", "review": GH + "localsend/localsend",
                                   "reviewSet": {"text": "Still my pick for LAN transfers.", "autoCommit": True, "autoPush": True}}, 1500),
    # package channels (requirement 16), from the demo data's channel facts (scripts/demo_data.py, demo-channels.json)
    ("A17-apps-detail-system-updated", {"view": "apps", "detail": GH + "localsend/localsend", "channels": True}, 1800),
    ("A11-confirm-remove-version", {"view": "apps", "detail": GH + "Zettlr/Zettlr", "scrollDetail": "versions",
                                    "confirm": ["removeVersion", {"url": GH + "Zettlr/Zettlr", "version": "4.6.0"}]}, 1500),
    # app sandboxing (requirement 17)
    ("A20-apps-detail-sandbox", {"view": "apps", "detail": GH + "keepassxreboot/keepassxc", "scrollDetail": "sandbox", "sandboxDemo": "x11"}, 1800),
    ("A21-sandbox-dialog", {"view": "apps", "detail": GH + "keepassxreboot/keepassxc", "sandbox": GH + "keepassxreboot/keepassxc", "sandboxDemo": "x11"}, 1800),
    ("A25-sandbox-advanced", {"view": "apps", "detail": GH + "keepassxreboot/keepassxc", "sandbox": GH + "keepassxreboot/keepassxc",
                              "sandboxScroll": "advanced", "sandboxDemo": "x11"}, 1800),
    ("A22-update-review-badge", {"view": "apps", "detail": GH + "Zettlr/Zettlr", "sandboxDemo": "x11"}, 1800),
    ("A23-confirm-uninstall-sandbox", {"view": "apps", "confirm": ["uninstall", {"url": GH + "keepassxreboot/keepassxc"}], "sandboxDemo": "x11"}, 1500),
    ("A24-sandbox-setup-needed", {"view": "apps", "detail": GH + "keepassxreboot/keepassxc", "sandboxDemo": "setup"}, 1800),
    ("C01-catalog", {"view": "catalog"}, 1800),
    ("C02-catalog-detail", {"view": "catalog", "detail": GH + "upscayl/upscayl", "expanded": 0}, 1800),
    ("C03-catalog-foreign", {"view": "catalog", "detail": GH + "obsproject/obs-studio"}, 1800),
    ("C04-catalog-search-veto", {"view": "catalog", "search": "vpn", "detail": "https://git.example.org/turboshield/vpn-desktop", "expanded": 0}, 1800),
    ("C06-install-options", {"view": "catalog", "detail": GH + "upscayl/upscayl", "installPlan": GH + "upscayl/upscayl"}, 2500),
    ("C11-install-sandbox", {"view": "apps", "detail": GH + "keepassxreboot/keepassxc", "installOptions": GH + "keepassxreboot/keepassxc",
                             "sandboxDemo": "x11"}, 2500),
    ("C10-install-channels", {"view": "catalog", "detail": GH + "localsend/localsend", "installPlan": GH + "localsend/localsend",
                              "channels": True}, 2500),
    ("C05-catalog-tags", {"view": "catalog", "tagsHover": GH + "keepassxreboot/keepassxc"}, 1500),
    ("C07-catalog-all-tags", {"view": "catalog", "allTags": True, "busy": {GH + "upscayl/upscayl": BUSY[GH + "localsend/localsend"]}}, 1500),
    ("S01-sources", {"view": "sources"}, 1500),
    ("S02-trust-detail", {"view": "sources", "trust": 3}, 1500),
    ("S03-source-menu", {"view": "sources", "sourceMenu": GH + "keepassxreboot/keepassxc"}, 1300),
    ("S04-add-source", {"view": "sources", "addSource": GH + "upscayl/upscayl"}, 6000),
    ("S05-remove-source", {"view": "sources", "removeSource": GH + "keepassxreboot/keepassxc"}, 1300),
    ("S06-source-in-trusts", {"view": "sources", "trustsHover": GH + "localsend/localsend"}, 1300),
    ("S07-explore", {"view": "sources", "explore": ["github", "password manager", 3]}, 7000),
    ("S17-explore-flathub", {"view": "sources", "explore": ["flathub", "notes", 5], "channels": True}, 2500),
    ("S08-source-settings", {"view": "sources", "sourceSettings": GH + "localsend/localsend",
                             "sourceSettingsSet": {"assetFilter": "linux-x86-64\\.AppImage$"}}, 1800),
    ("S09-source-highlight", {"view": "sources", "highlightSource": GH + "syncthing/syncthing"}, 1300),
    ("S10-confirm-remove-trust", {"view": "sources", "trust": 2, "confirm": ["removeTrust", {"id": 2}]}, 1500),
    ("S11-confirm-remove-authority", {"view": "sources", "trust": 3, "confirm": ["removeAuthority", {"trust": 3, "fp": "", "name": "Ade Bello",
                                                                                                    "trustName": "Desk Collective reviews"}]}, 1500),
    ("S12-confirm-trust-signer", {"view": "sources", "trust": 3, "confirm": ["trustSigner", {"trust": 3, "fp": "", "name": "nadia@desk.coop",
                                                                                              "trustName": "Desk Collective reviews"}]}, 1500),
    ("S13-confirm-ignore-signer", {"view": "sources", "trust": 3, "confirm": ["ignoreSigner", {"trust": 3, "fp": "", "name": "nadia@desk.coop",
                                                                                                "trustName": "Desk Collective reviews"}]}, 1500),
    ("U01-audit", {"view": "audit"}, 1500),
    ("U02-audit-sandbox", {"view": "audit", "auditFilter": "app"}, 1500),
    ("X01-app-menu", {"view": "catalog", "appMenu": True}, 1300),
    ("X06-about", {"view": "apps", "about": True}, 1300),
    ("X14-install-appkata", {"view": "catalog", "selfInstall": True}, 1500),     # first start of a downloaded AppImage (2.11.3.1)
    ("X16-first-start", {"view": "apps", "selfInstall": True}, 1500),           # the same, as it is: FRESH below
    ("X03-settings", {"view": "catalog", "settings": "top"}, 1500),
    ("X04-settings-portable", {"view": "catalog", "settings": "portable"}, 1500),
    ("X05-settings-data", {"view": "catalog", "settings": "data"}, 1500),
    ("X15-settings-sandbox", {"view": "catalog", "settings": "sandbox", "sandboxDemo": "setup"}, 1500),
    ("X07-confirm-remove-token", {"view": "catalog", "confirmOver": "settings", "confirm": ["removeToken", {"host": "git.example.net"}]}, 1500),
    ("X08-confirm-remove-relay", {"view": "catalog", "confirmOver": "settings", "confirm": ["removeRelay", {"relay": "wss://nos.lol"}]}, 1500),
    ("X09-confirm-quit", {"view": "apps", "busy": BUSY, "confirm": ["quit", {}]}, 1500),
]
# What the tour still finds drawn outside its box (layout.py), by screen and the start of the text,
# with the finding that keeps each: reported, not failed. One that no longer happens fails the tour,
# so the list shrinks (review 3, R3-22)
STILL_OUTSIDE: dict = {}


def shown_sandboxed(info: dict) -> bool:
    """App Detail's "Sandboxed" pill (17.4), from its sandboxInfo."""
    return bool(info.get("applicable") and info["active"] and info["level"] != "off")


# What no screen may show, whatever screenshots/README.md says: two parts of the app that tell one
# fact agree, under each state the tour stages. Review 3, R3-27: the tour forced App Detail's "runs
# sandboxed" alone, so A09 showed Syncthing sandboxed and updating itself. Each rule is (what's
# wrong, test(row, info)) for an installed app: its row in the Apps list and App Detail's sandboxInfo.
RULES = [
    ("shown sandboxed, and updating itself (17.12)", lambda a, s: shown_sandboxed(s) and a["state"] == "selfupdating"),
    ("AppKata updates it because it runs sandboxed, and it's shown not sandboxed (17.12)",
     lambda a, s: a["sandboxedUpdates"] and not shown_sandboxed(s)),
    ("its sandbox Off, and run sandboxed (17.4: the launch command offered)",
     lambda a, s: bool(s.get("applicable") and s["level"] == "off" and s["active"])),
    ("installed through a package channel, and sandboxed by AppKata (17.1)", lambda a, s: bool(a.get("ch")) and shown_sandboxed(s)),
]
# Each rule an app still breaks somewhere in the tour, as "App: rule", with the finding that keeps
# it: reported, not failed. One that no longer happens fails the whole tour, so the list shrinks
STILL_CONTRADICTS: dict = {}


def contradictions(backend) -> list[str]:
    """Each rule an installed app breaks as the backend shows it now, as "App: rule"."""
    out = []
    for a in [a for a in backend._apps if a["installed"]]:
        info = backend.sandboxInfo(a["url"])
        out += [f"{a['name']}: {text}" for text, broken in RULES if broken(a, info)]
    return out


# Each setting a step makes that nothing reads, as "screen: key", with the finding that keeps it:
# reported, not failed (review 3, R3-28). Main.qml records the keys read (tourKeys)
STILL_UNREAD: dict = {}


# Screens taken from an empty database (APPKATA_TOUR_FRESH=1, scripts/test-layout.sh's second pass),
# not the demo data: what every new user sees first, before any sync (review 3, R3-36)
FRESH = {"X16-first-start"}


def step_keys(step: dict) -> list[str]:
    """The settings a step makes: its keys, and a review's settings as "reviewSet.<key>"."""
    return list(step) + [f"reviewSet.{k}" for k in step.get("reviewSet") or {}]


# Linux's only: the sandbox (requirement 17), package channels (16) and the AppImage's first start
# (2.11.3.1). On Windows the tour leaves them out: there they'd show a half-empty Sandbox dialog and
# "Ubuntu 24.04"
LINUX_ONLY = {"A17-apps-detail-system-updated", "A20-apps-detail-sandbox", "A21-sandbox-dialog", "A22-update-review-badge",
              "A23-confirm-uninstall-sandbox", "A24-sandbox-setup-needed", "A25-sandbox-advanced", "C10-install-channels",
              "C11-install-sandbox", "S17-explore-flathub", "U02-audit-sandbox", "X14-install-appkata", "X15-settings-sandbox",
              "X16-first-start"}
if os.name == "nt":         # Windows only (requirement 15)
    STEPS = [s for s in STEPS if s[0] not in LINUX_ONLY]
    STEPS += [
        ("W01-close-app", {"view": "apps", "confirm": ["inUse", {"url": GH + "keepassxreboot/keepassxc", "name": "KeePassXC",
                                                                "action": "install", "version": "", "programs": ["KeePassXC.exe"]}]}, 1500),
        ("W02-install-options", {"view": "apps", "detail": GH + "keepassxreboot/keepassxc",
                                 "installOptions": GH + "keepassxreboot/keepassxc"}, 2500),
        ("W03-msvcrt", {"view": "apps", "detail": GH + "Zettlr/Zettlr", "msvcrt": GH + "Zettlr/Zettlr",
                        "confirm": ["msvcrt", {"url": GH + "Zettlr/Zettlr", "name": "Zettlr"}]}, 1500),
    ]


class Tour(QObject):
    def __init__(self, window, backend, out_dir: str, only: str = ""):
        super().__init__(window)
        names = [n for n in only.split(",") if n]
        themes = os.environ.get("APPKATA_TOUR_THEMES", "dark,light").split(",")
        light = {"A01-apps", "A02-apps-detail", "A03-review-dialog", "C01-catalog", "C02-catalog-detail",
                 "C04-catalog-search-veto", "C05-catalog-tags", "S01-sources", "S02-trust-detail", "S04-add-source",
                 "S06-source-in-trusts", "X01-app-menu", "A05-apps-detail-versions", "S07-explore", "U01-audit",
                 "X03-settings", "X04-settings-portable", "C06-install-options",
                 "A06-appkata-restart", "X06-about", "A07-apps-installing", "A09-app-updates-itself", "S08-source-settings",
                 "A10-confirm-uninstall", "S10-confirm-remove-trust", "C07-catalog-all-tags", "W01-close-app",
                 "W02-install-options", "W03-msvcrt", "C10-install-channels", "X14-install-appkata",
                 "A20-apps-detail-sandbox", "A21-sandbox-dialog", "C11-install-sandbox", "X15-settings-sandbox",
                 "X16-first-start"}
        fresh = os.environ.get("APPKATA_TOUR_FRESH") == "1"
        self.steps = [(n, s, d, t) for t in themes for (n, s, d) in STEPS
                      if (not names or n in names) and (t == "dark" or n in light) and (n in FRESH) == fresh]
        self.win, self.backend, self.out = window, backend, out_dir
        self.whole = not names and not fresh
        self.i = 0
        self.faults = []         # what a screen draws outside its box (layout.py), in DIR/layout.txt
        self.known = set()       # the STILL_OUTSIDE entries seen
        self.contradicted = {}   # each RULES break seen: the first screen that showed it
        self.unread = set()      # the STILL_UNREAD entries seen

    def start(self) -> None:
        if os.name == "nt":
            self.win.setGeometry(self.win.screen().availableGeometry())
        else:
            self.win.setWidth(DESIGN[0])
            self.win.setHeight(DESIGN[1])
        self.win.show()
        QTimer.singleShot(1500, self._step)

    def _step(self) -> None:
        if self.i >= len(self.steps):
            ran = {n for n, _, _, _ in self.steps}
            self.faults += [f"{n}: {t!r} no longer runs past its box: drop it from STILL_OUTSIDE"
                            for n, t in STILL_OUTSIDE if n in ran and (n, t) not in self.known]
            self.faults += [f"{where}: {c}" for c, where in self.contradicted.items() if c not in STILL_CONTRADICTS]
            self.faults += [f"{u}: read now, drop it from STILL_UNREAD" for u in STILL_UNREAD
                            if u.split(":")[0] in ran and u not in self.unread]
            if self.whole:          # a listed break may show on any screen: only the whole tour can say it's gone
                self.faults += [f"{c!r} no longer happens: drop it from STILL_CONTRADICTS"
                                for c in STILL_CONTRADICTS if c not in self.contradicted]
            os.makedirs(self.out, exist_ok=True)
            with open(os.path.join(self.out, "layout.txt"), "w", encoding="utf-8") as f:
                f.writelines(line + "\n" for line in self.faults)
            if self.faults:
                print(f"{len(self.faults)} faults: texts past their boxes, or a screen that contradicts itself (layout.txt)", flush=True)
            QApplication.exit(1 if self.faults else 0)
            return
        name, step, delay, theme = self.steps[self.i]
        # a screen that pins no sandbox state shows a working system, not the machine running the tour
        # (a container without bubblewrap said "Running unsandboxed" in App Detail)
        st = dict({"sandboxDemo": "ok"}, **step, theme=theme)
        QMetaObject.invokeMethod(self.win, "tour", Q_ARG("QVariant", st))
        QTimer.singleShot(400, lambda: self._popups(name, st, delay, theme))

    def _popups(self, name, st, delay, theme) -> None:
        if name == "S01-sources":      # hover the second avatar of the desk collective's Trust
            QMetaObject.invokeMethod(self.win, "tourSignerHover", Q_ARG("QVariant", 3), Q_ARG("QVariant", 1))
        QMetaObject.invokeMethod(self.win, "tourPopups", Q_ARG("QVariant", st))
        QTimer.singleShot(delay, lambda: self._when_settled(name, theme, 0))

    def _when_settled(self, name: str, theme: str, waited: int) -> None:
        """The shot, once nothing on the screen waits on the network (a check in Add source, a search
        in Explore: on a slow day the light S04 caught "Checking…"), for up to 30 s more."""
        busy = QMetaObject.invokeMethod(self.win, "tourBusy", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("QVariant"))
        if busy and waited < 30_000:
            QTimer.singleShot(500, lambda: self._when_settled(name, theme, waited + 500))
            return
        if busy:
            self.faults.append(f"{theme} {name}: still waiting on the network after 30 s")
        self._shot(name, theme)

    def _shot(self, name: str, theme: str) -> None:
        d = os.path.join(self.out, theme)
        os.makedirs(d, exist_ok=True)
        self.win.grabWindow().save(os.path.join(d, f"{name}.png"))
        try:
            found = layout.faults(self.win)
        except Exception as e:          # noqa: BLE001  (a check that fails is a fault, and the tour goes on)
            found = [{"text": "", "line": f"the layout check failed: {e!r}"}]
        for fault in found:
            known = next((k for k in STILL_OUTSIDE if k[0] == name and fault["text"].startswith(k[1])), None)
            if known:
                self.known.add(known)
                print("layout (listed):", theme, name, fault["line"], flush=True)
            else:
                self.faults.append(f"{theme} {name}: {fault['line']}")
                print("layout:", self.faults[-1], flush=True)
        try:
            broken = contradictions(self.backend)
        except Exception as e:          # noqa: BLE001
            broken = [f"the rules' check failed: {e!r}"]
        try:
            read = QMetaObject.invokeMethod(self.win, "tourKeys", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("QVariant"))
            read = set(read.toVariant() if hasattr(read, "toVariant") else read or [])
        except Exception as e:          # noqa: BLE001
            read = set()
            self.faults.append(f"{theme} {name}: the keys read are unknown: {e!r}")
        for k in step_keys(self.steps[self.i][1]):
            if k not in read:
                u = f"{name}: {k}"
                if u in STILL_UNREAD:
                    self.unread.add(u)
                    print("unread (listed):", theme, u, flush=True)
                else:
                    self.faults.append(f"{theme} {u}: the step sets it, and nothing read it")
                    print("unread:", self.faults[-1], flush=True)
        for c in broken:
            if c not in self.contradicted:
                self.contradicted[c] = f"{theme} {name}"
                print("contradicts" + (" (listed)" if c in STILL_CONTRADICTS else "") + ":", theme, name, c, flush=True)
        print("saved", theme, name, flush=True)
        self.i += 1
        QTimer.singleShot(150, self._step)
