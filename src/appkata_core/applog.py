"""The App log (requirement 14): background activity, errors and command output, in two text
files of at most 2 MB each: AppKata.log (current) and AppKata-prev.log (previous)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import threading

from .platform import OS

LIMIT = 2 * 1024 * 1024
CURRENT, PREVIOUS = "AppKata.log", "AppKata-prev.log"


def log_dir() -> str:
    if override := os.environ.get("APPKATA_LOG_DIR"):
        return os.path.abspath(override)
    if os.environ.get("APPKATA_DATA"):
        return os.path.join(os.path.abspath(os.environ["APPKATA_DATA"]), "logs")
    if OS == "windows":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "AppKata", "Logs")
    if OS == "macos":
        return os.path.expanduser("~/Library/Logs/AppKata")
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "appkata")


class TwoFileHandler(logging.Handler):
    """Writes AppKata.log; at the limit, replaces AppKata-prev.log with it and starts a new one
    (requirement 14.4.1)."""

    def __init__(self, folder: str, limit: int = LIMIT):
        super().__init__()
        self.folder, self.limit = folder, limit
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, CURRENT)
        self.prev = os.path.join(folder, PREVIOUS)
        self._lock = threading.Lock()
        self.f = open(self.path, "a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record) + "\n"
            with self._lock:
                if self.f.tell() + len(line.encode("utf-8")) > self.limit and self.f.tell() > 0:
                    self._rotate()
                self.f.write(line)
                self.f.flush()
        except Exception:      # noqa: BLE001 — logging must never break the app
            self.handleError(record)

    def _rotate(self) -> None:
        self.f.close()
        if os.path.exists(self.prev):          # 14.4.1.1
            os.remove(self.prev)
        os.replace(self.path, self.prev)       # 14.4.1.2
        self.f = open(self.path, "a", encoding="utf-8")    # 14.4.1.3

    def close(self) -> None:
        with self._lock:
            self.f.close()
        super().close()


_handler: TwoFileHandler | None = None


def setup(level: int = logging.INFO) -> TwoFileHandler:
    global _handler
    if _handler:
        return _handler
    _handler = TwoFileHandler(log_dir())
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(_handler)
    root.setLevel(level)
    logging.getLogger("appkata").info("AppKata started (pid %d, %s)", os.getpid(), sys.platform)
    return _handler


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess.run that logs the command and its output (requirement 14.2)."""
    lg = logging.getLogger("appkata.cmd")
    lg.info("$ %s", " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    for stream, text in (("out", p.stdout), ("err", p.stderr)):
        for line in (text or "").splitlines()[-200:]:
            lg.info("  %s| %s", stream, line)
    if p.returncode:
        lg.warning("  exit %d", p.returncode)
    return p


APP_LOG_LIMIT = LIMIT
GRACE = 10.0


def app_log_path(app_id: str) -> str:
    """Where a launched app's own output goes: logs/apps/<id>.log, one file per install, keyed by the
    install's own id (install.app_id_of, unique among installs), appended to at each launch and
    replaced by <id>-prev.log past APP_LOG_LIMIT (requirement 14.2.1). Review 2, F14: it was keyed by
    the name, so two "Notes" from two Sources shared one log, and one's failed start could be
    reported with the other's line. A file rather than a pipe: the app outlives AppKata, and a pipe
    whose reader is gone would end an app the moment it next wrote a line. The generated launcher
    bakes this path in and writes its own stderr there when nothing else shows it (the app menu, a
    shortcut), so a refused launch leaves the same trace whichever way the app was started; it was
    opened fresh per launch before, so a second instance truncated the first's live output."""
    import re
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", app_id).strip("-") or "app"
    return os.path.join(log_dir(), "apps", safe + ".log")


def adopt_name_logs(installs: list[tuple[str, str]]) -> None:
    """Move each log an older AppKata kept by app name (logs/apps/<name>.log and its -prev) to its
    install's id, given [(id, name)] of every install. A name two installs share keeps its old log,
    unsplit: its lines are both apps'. Nothing is moved over a log the id already has (14.2.1)."""
    names = [n for _, n in installs]
    for app_id, name in installs:
        if names.count(name) > 1:
            continue
        for old, new in ((app_log_path(name), app_log_path(app_id)),
                         (app_log_path(name)[:-4] + "-prev.log", app_log_path(app_id)[:-4] + "-prev.log")):
            if old != new and os.path.exists(old) and not os.path.exists(new):
                try:
                    os.replace(old, new)
                except OSError:
                    pass


def open_app_log(app_id: str, name: str):
    """(path, file) for a launch: the install's log opened for appending, rotated past the limit, with
    a dated header line naming the app written — the same rotation and header the launcher itself
    does when it is the one redirecting (14.2)."""
    import time
    path = app_log_path(app_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if os.path.getsize(path) > APP_LOG_LIMIT:
            os.replace(path, path[:-4] + "-prev.log")
    except OSError:
        pass
    f = open(path, "a", encoding="utf-8", errors="replace")
    f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} AppKata: starting {name}\n")
    f.flush()
    return path, f


# The generated launcher's own line just before the program runs, with the epoch second: what the
# watcher measures the grace period from, so a first launch that unpacked an AppImage for a minute
# first still reports the program dying at start, and a refusal before this line is reported however
# long it took (see watch()).
RUNNING_MARK = "AppKata: running"


def _running_at(logfile: str, since: int) -> float | None:
    """The epoch second of the last RUNNING_MARK line written after offset `since`, or None."""
    import re
    try:
        with open(logfile, "rb") as f:
            f.seek(since)
            text = f.read(1 << 20).decode("utf-8", "replace")
    except OSError:
        return None
    found = re.findall(r"^" + re.escape(RUNNING_MARK) + r" .*\((\d+)\)$", text, re.M)
    return float(found[-1]) if found else None


def tail_of(path: str, lines: int = 8) -> list[str]:
    """The last non-empty lines of a text file (at most the last 4 KB of it)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4096))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [l.rstrip() for l in text.splitlines() if l.strip()][-lines:]


def watch(proc: subprocess.Popen, name: str, logfile: str, on_failed=None, grace: float = GRACE,
          since: int = 0, launcher: bool = False) -> threading.Thread:
    """Wait for a launched program in the background; copy the end of its output into the App log
    when it exits, and report a launch that fails by calling `on_failed(code, last_lines)` (from the
    watching thread). Sandboxed launches fail in new ways — bwrap refused, an AppImage that didn't
    unpack, a CLI tool told it can't see its folder — and every one of them vanished into /dev/null
    before. A program run directly "failed to start" when it exits non-zero within `grace` seconds.
    A generated launcher (`launcher=True`) writes RUNNING_MARK just before the program runs: a
    non-zero exit with no mark after offset `since` is the launcher's own refusal, reported however
    long it took (a first launch unpacks the AppImage first, longer than any grace); one within
    `grace` of the mark is the program dying at start; a later one is a crash, logged only."""
    import time
    lg = logging.getLogger("appkata.app")
    started = time.monotonic()

    def failed_at_start() -> bool:
        if not launcher:
            return time.monotonic() - started < grace
        ran = _running_at(logfile, since)
        return ran is None or time.time() - ran < grace + 1       # the mark has whole seconds

    def follow():
        code = proc.wait()
        tail = tail_of(logfile)
        for line in tail:
            lg.info("%s| %s", name, line)
        if code:
            lg.warning("%s exited with %d (its output: %s)", name, code, logfile)
            if on_failed and failed_at_start():
                on_failed(code, tail)
        else:
            lg.info("%s exited (its output: %s)", name, logfile)
    t = threading.Thread(target=follow, name=f"watch {name}", daemon=True)
    t.start()
    return t


def combined() -> str:
    """Both files, oldest first, joined into one temp file (requirement 14.5.1); returns its path."""
    d = log_dir()
    out = os.path.join(tempfile.gettempdir(), "AppKata-log.txt")
    with open(out, "w", encoding="utf-8") as o:
        for name in (PREVIOUS, CURRENT):
            p = os.path.join(d, name)
            if os.path.exists(p):
                with open(p, encoding="utf-8", errors="replace") as f:
                    o.write(f.read())
    return out


def open_in_editor(path: str) -> None:
    """The system's text editor (requirement 14.5.2)."""
    if OS == "windows":
        subprocess.Popen(["notepad.exe", path])
    elif OS == "macos":
        subprocess.Popen(["open", "-t", path])
    else:       # the desktop's default app for text files
        subprocess.Popen(["xdg-open", path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
