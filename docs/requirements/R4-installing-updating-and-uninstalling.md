# R4. Installing, updating and uninstalling

R4.1. AppKata manages only the apps it installed. Each install is recorded with:

- Its Source and version.
- The asset it came from.
- Its install type (R4.3).
- Everything needed to uninstall it.

R4.2. **Choosing an asset.** For the current OS and architecture:

1. The Source's asset filter (R2.6.4), if set.
2. Otherwise the manifest (R2.7).
3. Otherwise the asset file names are matched to the platform's formats in order of
   preference, then to the architecture. A name with `x86_64`, `x86-64`, `amd64`, `x64`, `win64` or
   `64bit` is this computer's. A file named for another architecture (`aarch64`, `arm64` or `armv8`;
   `i386` to `i686`, a 32-bit `x86` or `win32`; `armhf`, `armv7`, `armel`, `ppc64le`, `s390x`,
   `riscv64`, `loong64`, `mips`) is passed over, unless its name also gives this computer's. A file
   named for this computer's architecture comes before one marked `universal`, `all-arch` or
   `noarch`, which comes before one that names none.
   A filter is applied only if it narrows the list without emptying it.

Format order on Linux:

1. AppImage
2. Flatpak bundle
3. `.deb` (Debian-family) or `.rpm` (Fedora-family)
4. `.tar.gz` / `.tar.xz`

A Linux package wrapped in a `.zip` isn't looked inside: [G#56](https://github.com/MojoKata/AppKata/issues/56).

On Windows, portable first (R15.3): a portable `.zip`, a portable `.exe`, `.msi`, a `.exe`
installer, `.msix`. Only x64 files are chosen.

R4.2.1. **Portable or system package.** AppKata decides from the file, without asking:

| File | Install |
|---|---|
| AppImage, `.tar.*` with a program inside, Windows `.zip` with a `.exe` inside | Portable (R4.3.1) |
| `.deb`, `.rpm`, Flatpak bundle, `.msi`, `.msix` | System package (R4.3.2, R4.3.3) |
| Windows `.exe` | Probed: AppKata reads the file's first megabyte (a ranged download) for Inno Setup, NSIS, WiX and InstallShield markers, which also give the silent-install arguments (R4.3.3). Otherwise its name decides (`portable`, `standalone` → portable; `setup`, `installer` → installer). If neither does, it's **unknown** and the install dialog asks (R4.9). |

R4.3. **Install types.**

R4.3.1. **Portable** (AppImage, tarball, portable `.zip`). Each app gets its own
folder, `<install folder>/<app>/`, holding its versions side by side: an AppImage as its
versioned file (`LocalSend-1.18.2-x86_64.AppImage`: the release's own file name, with the version
added when the name holds none or is another version's, so `Tool-x86_64.AppImage` is kept as
`Tool-x86_64-2.0.AppImage`), an archive unpacked into a folder named after its version (`2.1/`).
A version is written in these names with `_` for each run of characters other than ASCII letters,
digits, `.`, `_`, `+` and `-`, and with `_` before one that starts with a dot (`_..`), so no
version's folder is the app's folder itself, the install folder above it, or hidden.

An archive's program, the one its links and its launcher start and its kind is read from (R17.3.3),
is on Linux the executable file the archive's own `.desktop` file starts; else the one named after
the app or its repository, or whose name holds one of those or is held by one (`codium` for
VSCodium); a compiled program before a script; then the one nearest the archive's top. It is never
a shared library, a `.sh` script, or a helper that comes with a program: Chromium's
`chrome-sandbox` and crash handler, or `<program>-bin` beside `<program>`.

The install folder is a setting (R11.1.4); by default it is:

- `~/bin/apps` on Linux, with command links (R4.3.1.3) directly in `~/bin`. Ubuntu, Debian and
  Mint put `~/bin` on the PATH at login when it exists.
- On Windows, by who the app is for (R15.4): `%LOCALAPPDATA%\Programs` for **Just me** (the
  default), `C:\Programs` for **Everyone**. Neither needs administrator rights.

The install folder and the command links folder (R4.3.1.3) are read the same way: a leading `~`
is the user's home folder, and environment variables are filled in (`$HOME/bin`; on Windows
`%LOCALAPPDATA%\Programs` too).

No elevation is needed. Changing the install folder applies to new installs: an app already
installed stays in the folder it is in through its updates, and is uninstalled from there. It goes
to the new folder only when it is uninstalled and installed again. Install options (R4.9.5) shows
that folder as the one it installs to; on Windows, a move to the other of Just me and Everyone
(R15.4.1) is a new install, which goes to that one's install folder in Settings.

R4.3.1.1. **App menu.** When on (the default), AppKata adds a launcher: a `.desktop` entry on
Linux, a Start-menu shortcut on Windows (R15.5). On Linux, an app its download shows to be a
command-line tool (R17.3.3) gets none unless the user or a Trust chose the option for it. The
`.desktop` entry starts the app through a small script AppKata keeps for it in its own folder
(`~/.local/share/appkata/menu/<app>`, which runs what the app runs by its own path), run by
`/bin/sh`, the entry's program. So the entry never holds a path in the install folder, and no
install folder is refused for its name: a `%` in it, which an entry must write as `%%`, made GLib's
menus (Cinnamon, GNOME, MATE, Xfce) take the app for one that isn't installed. Nor does a `%` in
the path of AppKata's own folder keep an app out of the menu, and an app starts from the menu where
that folder is on a mount that runs no programs (`noexec`), since the script is only read. Started
from the menu, the app has its own path as its name, as it
does started any other way, so a program that finds its files beside itself starts. The script
goes with the entry.

R4.3.1.2. **Stable name.** When on (the default), the current version also gets a link with a
stable name next to it: `LocalSend.AppImage` → `LocalSend-1.18.2-x86_64.AppImage`, or
`current` → `2.1/` for an unpacked archive. Launchers and command links point at the stable
name, so they keep working across updates; for a sandboxed app they point at its launcher,
`~/bin/apps/<app>/run`, which runs the current version (17.4). (On Windows, `current` is a directory junction,
which needs no extra rights, R15.5.)

R4.3.1.3. **Command links.** When on (the default), AppKata puts a link named after the app
(`localsend`) in the command links folder (default `~/bin`), so the app can be started
from a terminal. On Linux no link is made for a name that is already a command on this computer
(something elsewhere on the `PATH`, or in the system's own folders, answers to it), or that is one of a short
list kept for the system's own commands whether or not they are installed (`python3`, `sudo`, `ssh`,
`git`, the commands AppKata and its sandbox launchers run by name, R17.4): the name is the app's
publisher's to pick, and `~/bin` comes first on the `PATH`. Such an app is installed with its
app-menu entry and no command, and the install says why; its option stays on, so the link is made
at a later update or start of AppKata once the name is free, and a link whose name has since become
a command is removed then. AppKata never replaces or removes a file there that isn't a link it made
(a link that leads into the install folder), whether or not it made a link at that place before: an
install or update stops with an error instead ("… exists and isn't a link AppKata made; not
replacing it"), whatever the `PATH` and whether or not that file answers as a command, and
uninstalling leaves it. A change to an installed
app's sandbox, and the launcher AppKata rewrites at its start (R17.4), don't stop there: they are
made in full, without the command link, which is made at a later start or update once its place is
free. On Windows a command link is a `<app>.cmd` file (R15.6).

R4.3.1.4. Uninstalling removes the app's folder (every version), its launcher and its links.

R4.3.1.5. **Older versions.** After an update, AppKata keeps up to *N* previous versions in the
app's folder (Keep older versions, R11.1.4; default 2) and removes older ones. A kept version
reinstalls instantly, without downloading (R5.7.5.1); the user can also remove a kept version
from the version list.

R4.3.1.6. **Per-app options.** The three options above (app menu, stable name, command link) are
copied into each app's own settings when it's installed, so changing Settings later doesn't
change apps already installed. An app's options can be changed from **Install options…** (R4.9.5).
For a new install the starting values are, in order: the app's own saved options, the options a
Trust recommends for it (R10.3.1, yours first), then Settings.

R4.3.2. **Flatpak bundle.** Installed with `flatpak install --user`.

R4.3.3. **System packages** (`.deb`, `.rpm`, `.msi`, `.exe` installers, `.msix`).
These need elevation (R1.3). Installers run silently when the installer type is recognized:

| Installer | Silent arguments |
|---|---|
| MSI | `msiexec /i … /qn` |
| Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES` |
| NSIS | `/S` |
| WiX Burn bundle | `/quiet /norestart` |
| InstallShield | `/s` |
| Squirrel | `--silent` |
| Unrecognized | Runs interactively |

On Windows, who an installer installs for, elevation, exit codes and uninstalling are in R15.4,
R15.7 and R15.8.

R4.4. **Verifying downloads.** Before installing, AppKata:

1. Checks the file against `SHA256SUMS`, `*.sha256` or a forge-provided digest, when one
   exists.
2. Checks a minisign or GPG signature, or a sigstore bundle, when one exists.
3. Reads Windows' code-signing status, Authenticode (R15.11).

The App Detail panel shows the result as a chip: **Verified** (a signature checked),
**Checksum** (a checksum only), or **Unverified**. Unverified downloads can still be
installed. A failed check blocks the install and explains why.

R4.5. **Foreign installs.** An app is **foreign-installed** when AppKata finds it on the system
but didn't install it. AppKata looks for it in:

- The package database (dpkg, rpm, flatpak).
- On Windows, the places listed in R15.12.
- `/Applications` (by bundle ID).
- The Start menu or `.desktop` entries.

The match uses the manifest's IDs, the AppStream ID, or the app name.

R4.5.1. Foreign-installed apps are flagged with an **Installed outside AppKata** badge
wherever they appear: Catalog tiles, the App Detail panel, and Source rows. The badge's
tooltip says where the install was found, and its version if known.

R4.5.2. Foreign-installed apps are never listed in the Apps view (R6) and are never managed by
AppKata, unless the user adopts one that a package channel matches exactly (R16.4.2).

R4.5.3. AppKata does not install on top of a foreign install. The Install button is replaced
by a disabled **Installed outside AppKata** button with the note "Uninstall the existing copy
first to manage it with AppKata." When a package channel matches it exactly, the button is
**Adopt** instead (R16.4.2).

R4.5.4. Adding a Source for a foreign-installed app is allowed, and the row is flagged
(R7.1.1).

R4.6. **Updating** installs the new version using the same install type, and keeps the
previous version's files until the update succeeds. A portable install that fails leaves nothing
of itself behind: after a first install there is no app folder, link, launcher or app-menu entry;
after an update, or a switch to a kept version, the version that was current still is, with its
links, its launcher and its app-menu entry.

R4.7. **Uninstalling** reverses what AppKata recorded at install (R4.1), after a confirmation.
User data in the home folder is kept. What AppKata recorded and didn't remove is named in the
notice ("<App> uninstalled. Not removed: <path>."): a folder that is no longer inside the install
folder the app was installed into or that couldn't be deleted, and something of the user's where
a command link was (R4.3.1.3).

R4.8. **Install progress.**

R4.8.1. **Phases**: Waiting, Downloading, Verifying, Installing. One install runs at a time;
**Update all** and further installs queue behind it as "Waiting". The progress shows:

- **Apps row**: the phase ("Downloading 45%", "Verifying…", "Waiting") above a progress bar,
  with "41.4 MB of 92.0 MB · 3.4 MB/s" beside it when the row is wide enough. The Update and
  Uninstall buttons give way to an icon-only **Cancel** (✕; for a waiting app, "Remove from the
  queue").
- **App Detail panel**: the Install or Update button shows the phase and percentage, followed by
  a **Cancel** button, a progress bar, and the size and speed.
- **Catalog tile**: the state mark becomes "Installing 45%".
- **Header bar**: a turning sync icon in the Apps segment while anything installs.

R4.8.2. **Resuming.** Downloads go to `<data folder>/downloads/<app>/<file>.part`. `<file>` is
the release's own name for its file, as one file name: what follows its last `/` or `\`, so a
release that names its file as a path (`../../x.tar.gz`) reaches no folder but the app's own, here
and where the file is installed (R4.3.1). A file whose name is then empty, starts with a dot or
holds a control character, or on Windows is one Windows reserves or can't hold (R15.16), isn't
installed, and the install says so. If the
connection breaks, AppKata retries up to three times, continuing from where it stopped with a
Range request, as long as the server still has the same file (`If-Range` with its ETag or
Last-Modified date). Otherwise it starts over. A download that still fails, or that was
interrupted by quitting, is kept and resumed the next time the app is installed or updated.
The checksum (R4.4) is always checked over the whole file. A complete file that fails its
checksum or its install is deleted.

R4.8.3. **Cancelling** is possible until the Installing phase starts. It deletes the partial
download and installs nothing.

R4.9. **Install options on the first install.** The first time an app is installed, AppKata
probes the release's files for this computer (R4.2, R4.2.1) and shows a dialog only when a choice
is needed to get the app's settings right:

R4.9.1. **When it asks:** the app also has a package channel on Linux (R16.3.3), or the release has both a portable file and a system package (for
example an AppImage and an `.rpm`), or a Windows `.exe` it couldn't classify. Otherwise it
installs straight away with the preferred file.

R4.9.2. **The dialog**, titled "Install <App> <version>":

- One card per kind of file, in order of preference, the first marked **Recommended**. On Linux,
  one card per package channel too (R16.3.1). Each
  shows the kind (AppImage, `.rpm` package…), a **Portable** or **System package** chip, what it
  means ("Runs from your install folder; no admin password. Updates replace the file." or
  "Installed for all users with dnf; needs your admin password."), the file name and its size.
- For an unclassified `.exe`: "This file is **A portable program** / **An installer**"; Install
  stays disabled until one is picked.
- For a portable choice: where it will go (`<install folder>/<app>`), and this app's **Add to
  the app menu** and **Command `<app>` in `<folder>`** checkboxes, starting from Settings (R11.1.4).
  On Linux the command checkbox is disabled and unticked when no command link would be made for
  the app's name (R4.3.1.3), with the reason as its tooltip ("No command will be added: `ls` is
  already a command on this computer (/usr/bin/ls)."); the option itself stays as it was.
  On Linux, **It is**: "As the download shows" (or "Decide from the download" before it's known), "An
  app with a window" or "A command-line tool" (R17.3.3); choosing one moves the Sandbox card with it.
- On Windows, **Install for**: **Just me** or **Everyone on this computer** (R15.4), when the file
  supports both; otherwise a note saying which one it does.
- On Linux, for an AppImage or a tarball, the **Sandbox** card: the template the app will run under
  and its summary chips, **Change…** (the Sandbox dialog, R17.3), the reviewers' suggestion with
  **Use theirs** when it differs (R17.3.2, R17.11), and for an AppImage the cost of unpacking it (R17.7).
- **This app updates itself** (R4.10), checked when a Trust says so, with "<Trust> says it updates
  itself", and the hint "AppKata installs it and shows new releases, but leaves updating to the
  app. AppKata can't turn an app's own updater off." — with, when it will run sandboxed, "While it
  runs sandboxed it can't update itself, so AppKata updates it." (R4.10.5)
- "You can change this later from the app's ⋯ menu.", **Cancel** and **Install**.

R4.9.3. **The answer is saved** with the app (the kind of file, what an `.exe` is, the two
portable options, on Linux the app's kind and the sandbox when the card was changed, and on Windows
who it's for) and recorded in the Audit. Updates use it without asking; if a later release
lacks that kind of file, the preferred one is used.

R4.9.4. Apps installed before a choice was saved keep to the kind of file they were installed
from.

R4.9.5. The App Detail panel shows how the app is, or would be, installed: a chip such as
"AppImage · portable" or ".rpm · system package". For installed apps, the ⋯ menu has **Install
options…**, which opens the same dialog with **Save** instead of Install; changes apply from the
next update, except the Sandbox card's, which applies at once (R17.13).

R4.9.6. On Windows, AppKata uninstalls apps installed by their own installer with the uninstall
command it recorded at install (R15.8).

R4.10. **Apps that update themselves.** Some apps download and install their own updates
(electron-updater, Sparkle, their own updaters), on some or all platforms.

R4.10.1. AppKata still finds, installs, tracks and uninstalls them. It doesn't update them: their
state is **Updates itself** (a chip on the Apps row and in the App Detail panel, with "<version>
is out" when a newer release exists), they have no Update button, **Update all** skips them, and
older versions can't be installed from the Versions list.

R4.10.2. A portable app that updates itself is installed as `<install folder>/<app>/<App>.AppImage`
(or an `app` folder for archives), with no version folders, kept versions or `current` link, since
the app replaces its own files.

R4.10.3. **Whether an app updates itself** is a statement about the app, not a switch: AppKata
can't turn an app's own updater on or off, it only steps back. Unticking it means "this app
doesn't update itself", and AppKata then updates it. It comes from, in order: the app's own setting (the **This
app updates itself** checkbox in the install dialog and Install options…, R4.9), then the
`Auto update` option of the highest-Score Trust that sets one for this platform, as its review for the installed or latest version has it (R10.3.3; its
`(<platform>)` line, else its line without one; R10.3.1, R7.6.8).
The App Detail panel says where it came from ("Kenji's app reviews says it updates itself; change
this in Install options.", or "You marked it as updating itself in Install options.").

R4.10.4. Turning off an app's own updater from outside (Syncthing's `STNOUPGRADE`, VSCodium's
`update.mode`, Joplin's preference) so AppKata can update it instead isn't supported; it would need
a recipe per app.

R4.10.5. **While it runs sandboxed** (R17), an app that updates itself can't: its files, and an
AppImage's own file, are read-only. AppKata then updates it as if it didn't update itself — it has
the Update button, Update all includes it, and its next update moves it from the fixed-name layout
of R4.10.2 to version folders — and App Detail and the install dialog say why (R17.12). When its
sandbox is turned Off, it updates itself again, in the fixed-name layout: AppKata renames its
current version to the fixed name of R4.10.2 and removes its kept versions and its `current` link.
