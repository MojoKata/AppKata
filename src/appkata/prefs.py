"""Per-user view preferences (theme, panel states, sort), stored next to the database."""

from __future__ import annotations

import json
import os

from appkata_core.platform import command_dir_default, data_dir

DEFAULTS = {"theme": "system", "trustPanelOpen": True, "sort": "trust", "reviewPath": "", "autoCommit": False,
            "autoPush": False, "syncHours": 6, "notifications": True, "startInTray": False, "minAgeDefault": 0,
            "prereleases": False, "installDir": "", "appMenu": True, "stableName": True, "commandLinks": True,
            "commandDir": command_dir_default(), "keepVersions": 2, "installFor": "me", "installDirEveryone": "",
            "includeDetails": None, "selfInstallDeclined": False,
            "sandboxGuiDefault": "strict", "sandboxCliDefault": "cli-tool",
            "followReviewerSandbox": True, "sandboxReviewBadge": True, "sandboxSetupDeclined": False,
            "relays": ["wss://relay.ngit.dev", "wss://gitnostr.com", "wss://nos.lol", "wss://relay.damus.io"]}


def _path() -> str:
    return os.path.join(data_dir(), "gui.json")


def load() -> dict:
    try:
        with open(_path()) as f:
            data = json.load(f)
        return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save(prefs: dict) -> None:
    p = _path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(prefs, f, indent=1)
        os.replace(tmp, p)
    except OSError:
        pass
