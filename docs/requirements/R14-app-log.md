# R14. App log

R14.1. A fixed-size text history of background activity: syncs, downloads, installs, Trust
checks, and anything that went wrong.

R14.2. Error messages, Qt and QML warnings, and the output of commands AppKata runs (git,
package managers, flatpak, pkexec) go here for diagnostics. Secrets (API tokens) never do.

R14.2.1. An app AppKata launches (R4.3.1.1) writes its own output to `logs/apps/<id>.log` in the
same folder, keyed by the install's own id (R17.6), so two apps with one name each have their own
(appended under a dated line at each launch; past 2 MB the file becomes `<id>-prev.log`), and its
last lines are copied into the App log when it exits. A log an older AppKata kept by name moves to
its install's id at start, unless two installs share the name (review 2, F14: they shared one log). A sandboxed app
started from the app menu, a file manager or a shortcut writes its launcher's errors to the same file
(the entry passes `--appkata-menu`; from a terminal or a script, stderr stays the caller's), so a
refused launch leaves the same trace whichever way it was started. If it fails to start — the
launcher's own refusal (a sandbox that couldn't start, an AppImage that didn't unpack, a command-line
tool refusing its folder, R17.3.3) however long the unpacking took, or the program exiting non-zero
within seconds of the launcher starting it — the user is told so, with the last line of output,
instead of nothing happening.

R14.3. The files are in the platform's log folder (R1.8): `~/.local/state/appkata` on Linux
(`$XDG_STATE_HOME`), `%LOCALAPPDATA%\AppKata\Logs` on Windows, `~/Library/Logs/AppKata` on macOS.

R14.4. There are two files: **AppKata.log** (current) and **AppKata-prev.log** (previous).

R14.4.1. When AppKata.log would pass 2 MB:

1. AppKata-prev.log is deleted, if it exists.
2. AppKata.log is closed and renamed to AppKata-prev.log.
3. A new AppKata.log is opened for writing.

R14.5. **Show app log** in the ⋮ menu (R5.4):

R14.5.1. Joins the two files, previous first, into `AppKata-log.txt` in the system's temp folder.

R14.5.2. Opens that file in the system's text editor (the desktop's default for text files on
Linux, `open -t` on macOS, Notepad on Windows).
