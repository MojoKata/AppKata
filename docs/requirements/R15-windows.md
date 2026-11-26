# R15. Windows

R15.1. AppKata runs on Windows 10 22H2 (fully updated), x64 only; Windows 11 isn't tested yet (R1.1). This section
collects what is specific to Windows. The sections it refers to still apply.

R15.2. **Elevation.** AppKata runs without administrator rights (what a headless VM can't show of
it is [G#59](https://github.com/MojoKata/AppKata/issues/59)). It starts every installer and
uninstaller through the shell (`ShellExecuteEx`), as Explorer does, and waits for its exit code:
an installer whose manifest needs administrator rights then gets the UAC prompt, and with the
Mark of the Web (R15.11.1) SmartScreen checks it. When AppKata itself asks for administrator rights
(R15.4, R15.7, R15.8), it uses the `runas` verb; for a downloaded installer, on the script of
R15.7.5 and not on the download. Declining the prompt cancels the action.
AppKata never starts a per-machine installer through `CreateProcess`, where it would fail (error
740), or for a silent `.msi`, fail without asking.

R15.3. **Choosing a file.** Portable files come first (R4.2): a `.zip` with a program inside, a
portable `.exe`, then `.msi`, a `.exe` installer and `.msix`. When a release has both a portable
file and an installer, the install dialog asks, with the portable file **Recommended** (R4.9.1).

R15.4. **Who an app is for.** Every app installed on Windows is for **Just me** or for
**Everyone on this computer**.

R15.4.1. It is a per-app setting, like the portable options (R4.3.1.6). Its starting value is
**Install apps for** in Settings (R11.1.4; default Just me). The install dialog (R4.9.2) shows it
when the file supports both. **Install options…** can change it later: AppKata reinstalls the
installed version in the new place, then removes the old copy. Trusts don't recommend it
(R10.3.1), because it describes this computer, not the app.

R15.4.2. What each means:

| | Just me | Everyone |
|---|---|---|
| Portable apps | `%LOCALAPPDATA%\Programs\<app>\` | `C:\Programs\<app>\` (R15.4.3) |
| Start-menu shortcut | The user's Start menu | The all-users Start menu; UAC at install and uninstall only |
| Installers | The per-user arguments (R15.7.2) | The per-machine arguments, elevated |
| `.msix` | Always | Not offered |
| Command links (R15.6) | The user's | Still only the installing user's; others use the Start menu |

Both folders are settings (R11.1.4).

R15.4.3. **Protecting `C:\Programs`.** By default every user may change what is created at the
root of the system drive, so another account could replace a program that others then run.
AppKata prevents this without a UAC prompt, because the owner of a folder may set its
permissions:

1. When AppKata creates `C:\Programs`, it turns off inherited permissions and grants:
   Administrators and SYSTEM full control; Users read, run, and create folders (this folder
   only); CREATOR OWNER full control of subfolders.
2. Each app folder grants the installing user, Administrators and SYSTEM full control, and
   Users read and run.
3. Before installing or updating an app for everyone, AppKata checks both folders' owner and
   permissions. A folder owned by the user or by Administrators whose permissions were loosened
   is set right again. A folder owned by another account is refused: the install stops with an
   error naming the folder, and installs nothing.

R15.4.4. Another user's AppKata sees an app installed for everyone as **Installed outside
AppKata** (R4.5), through its all-users Start-menu shortcut.

R15.5. **Shortcuts and the stable name** (R4.3.1.1, R4.3.1.2).

- `current` is a directory junction to the current version's folder; junctions need no extra
  rights. A portable `.exe` is placed in its own version folder, so every portable app on
  Windows has a `current`.
- The Start-menu shortcut is a `.lnk` directly in the Start menu's `Programs` folder (Windows
  11 shows only one level of folders), named after the app. It points at the program inside
  `current`, with the program's own icon and its folder as the working directory. It is made at
  install and doesn't change on updates. It sets no AppUserModelID: one the app doesn't use
  itself would break pinning and grouping on the taskbar.
- An app that updates itself (R4.10.2) has an `app` folder and no junction; its shortcut points
  into that folder.

R15.6. **Command links** (R4.3.1.3) are `<app>.cmd` files: a first line `@rem made by AppKata`, then
`@"<install folder>\<app>\current\<Program>.exe" %*`. The default command links folder is
`%LOCALAPPDATA%\AppKata\bin`.

- When AppKata writes the first one, it adds the folder to the user's PATH (`HKCU\Environment`,
  then a `WM_SETTINGCHANGE` broadcast; terminals opened afterwards see it). When it removes the
  last one, it removes the folder from the PATH.
- AppKata never replaces a `.cmd` it didn't write (one without that first line).
- A `.cmd` has two known limits next to a small launcher `.exe`: Ctrl+C in a console app asks
  "Terminate batch job (Y/N)?", and `cmd.exe` can expand a `%` in the arguments. Neither matters
  much for the desktop apps AppKata mostly installs, and a `.cmd` needs no program of AppKata's own.

R15.7. **Installers** (R4.3.3).

R15.7.1. The installer type comes from probing (R4.2.1): markers in the file's first megabyte, in
ASCII or UTF-16 (Inno Setup 6.3 and later keep only `InnoSetupLdrWindow` and a jrsoftware.org
link), and the release's other files: `latest.yml` marks electron-builder's NSIS, and a
`RELEASES` file or `-full.nupkg` packages mark Squirrel. An app installed by Squirrel is marked
as updating itself (R4.10) unless the user unticks it.

R15.7.2. **Arguments for each scope** (R15.4). Where the installer can't choose, the dialog's
**Install for** row says what it does ("This installer installs for everyone") instead of
offering a choice:

| Installer | Silent | Just me | Everyone |
|---|---|---|---|
| MSI | `msiexec /i … /qn /norestart` | `ALLUSERS=2 MSIINSTALLPERUSER=1` | `ALLUSERS=1`, elevated |
| Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` | `/CURRENTUSER` | `/ALLUSERS`, elevated |
| NSIS by electron-builder | `/S` | `/currentuser` | `/allusers`, elevated |
| Other NSIS, WiX Burn, InstallShield | `/S`, `/quiet /norestart`, `/s` | The installer decides | The installer decides |
| Squirrel | `--silent` | Always | Not offered |
| `.msix` | `Add-AppxPackage` | Always | Not offered |

An Inno Setup installer accepts `/CURRENTUSER` only when it was built to allow it. AppKata
learns the real scope from where the app's Uninstall entry appears (R15.8.1) and records that. An
installer that turns out to need administrator rights is started again, elevated (R15.2).

R15.7.3. **Exit codes.**

| Code | Meaning | AppKata |
|---|---|---|
| 0 | Done | Installed |
| 3010, 1641 | Done; Windows must restart | Installed; a toast says "Restart Windows to finish installing <App>" |
| 1602, 1223 | Cancelled (1223: the UAC prompt was declined) | Cancelled; nothing recorded |
| 1618 | Another installation is running | "Another installation is running. Try again when it's finished." |
| Other | Failed | The error, with the installer's output in the App log |

R15.7.4. **`.msix`** installs with `Add-AppxPackage` for the current user, with no UAC prompt. A
package whose signer Windows doesn't trust can't be installed, and AppKata says so. The
package's full name is recorded for uninstalling.

R15.7.5. **An installer AppKata elevates** (the "elevated" cells of R15.7.2, and the Visual C++
run-time, R15.18.3) is never started from the downloads folder, which the user's other programs
can change (R4.4). AppKata asks Windows to elevate Windows PowerShell with a script, so the UAC
prompt names Windows PowerShell and not the installer. That PowerShell is the one in the system
folder Windows itself names, never in a folder the environment names. The script:

1. Makes a new folder in Windows' own `Temp` folder that only Administrators and SYSTEM can
   change, and copies the download there. It opens the download once, following no link put at
   its path, takes it only when it is a file on a disk of the length AppKata checked, and copies
   no more than that length.
2. Compares the copy's SHA-256 with the one AppKata took of the download. When they differ, or
   what it opened was no such file, it starts nothing, and the install fails with R4.4's message.
   A download that can't be opened as a file (it is gone, a folder is at its path, or Windows
   refuses to open it) isn't known to have changed: nothing is started, and the install fails with
   "Windows couldn't make the administrators' copy of the installer or start it; nothing was
   installed".
3. Starts the copy through the shell (R15.2), an `.msi` with Windows' own `msiexec`, waits, and
   hands back its exit code (R15.7.3). Then it removes the folder.

An installer that AppKata starts without administrator rights and that asks Windows for them
itself (R15.2; "The installer decides" in R15.7.2) is started from the downloads folder: the UAC
prompt is then Windows' own for that file, and names its publisher.

R15.8. **Uninstalling installer apps** (R4.9.6).

R15.8.1. AppKata reads the Uninstall registry keys (HKCU, and HKLM in its 64-bit and 32-bit
views) before and after running an installer. The entry that is new or changed is recorded with
the install (R4.1): its key, `DisplayName`, `DisplayVersion`, `QuietUninstallString`,
`UninstallString`, and for MSI the product code. Its hive gives the real scope (R15.4). If no
entry appears, the install still succeeds, with a note that AppKata can't uninstall it.

R15.8.2. Uninstalling runs `QuietUninstallString`, else `UninstallString` with the silent
argument for its installer type, else `msiexec /x {product code} /qn`. It is elevated when the
entry is under HKLM. The uninstall succeeds when the entry is gone; AppKata waits up to a
minute for that, since NSIS uninstallers finish from a copy of themselves. `.msix` packages are removed
with `Remove-AppxPackage`.

R15.8.3. After each update AppKata reads `DisplayVersion` again. If it doesn't match the release,
the App Detail panel says "Windows reports version <X>".

R15.9. **Files in use.** Windows can't replace or delete a running program's files. Before the
Installing phase of a portable app's update, switching to or removing a kept version, or
uninstalling a portable app, AppKata checks for processes running from the app's folder. If there
are any, it shows "Close <App> to continue" with **Try again** and **Cancel**. AppKata never
stops the app itself. Installers handle this themselves.

R15.10. **AppKata's own setup** (R1.6; its signing certificate is [G#60](https://github.com/MojoKata/AppKata/issues/60)) is built with Inno Setup, `PrivilegesRequired=lowest`, with
overrides allowed:

- Just me by default, into `%LOCALAPPDATA%\Programs\AppKata`; or Everyone, into `Program Files`.
- It refuses a Windows older than Windows 10 22H2 (`MinVersion=10.0.19045`, R1.1). It doesn't
  check the updates installed.
- It adds the Start-menu shortcut (with AppKata's AppUserModelID, R15.14) and the `appkata://`
  handler.
- Its uninstaller removes AppKata, offers to remove `%LOCALAPPDATA%\AppKata`, and leaves the
  apps AppKata installed in place, saying so.
- Updates: R2.11.5.

R15.11. **Authenticode** (R4.4). AppKata checks `.exe`, `.msi` and `.msix` downloads with
Windows' own check (`Get-AuthenticodeSignature`, which uses `WinVerifyTrust`).

- A valid signature makes the chip **Verified · <signer>**.
- A signature that doesn't match the file (it changed after signing) blocks the install, like a
  failed checksum.
- An unsigned file, or one signed with a certificate Windows doesn't trust (a self-signed one,
  common for small FOSS projects), is judged by its checksum alone.

R15.11.1. **Mark of the Web.** **Mark downloads as from the internet** is a per-app setting, off by
default, in **Install options…** (R4.9.5) on Windows. Trusts don't recommend it (R10.3.1).

- When it's on, AppKata gives each download the mark a browser would (a `Zone.Identifier` stream
  with `ZoneId=3` and the download's URL). It copies the mark to every file it unpacks from an
  archive, as Explorer does. It starts installers, and opens the app, with `ShellExecuteEx`, so
  that SmartScreen checks them. If the user chooses not to run a file at SmartScreen's warning,
  the install is cancelled.
- When it's off, downloads carry no mark, and AppKata's own checks (R4.4, R15.11) are the only
  ones.
- Changing it applies from the next install or update, and is recorded in the Audit (R13.3).

R15.12. **Foreign installs** (R4.5) on Windows are found in:

- The Uninstall registry (HKCU, and HKLM 64-bit and 32-bit), which also covers winget installs.
- Store and `.msix` apps (`Get-AppxPackage`).
- Scoop (`~\scoop\apps`) and Chocolatey (`%ProgramData%\chocolatey\lib`).
- Start-menu shortcuts, the user's and all users'.

Entries AppKata recorded itself (R15.8.1) aren't foreign.

R15.13. **The window** (R5.3). The header bar also has **Minimize** and **Maximize** (**Restore**
when maximized) before the close button, in Windows' usual order and shapes. The window behaves
like any other Windows window:

- Dragging it to a screen edge snaps it (Aero Snap). Hovering over Maximize shows Windows 11's
  Snap Layouts, because the button answers `WM_NCHITTEST` as `HTMAXBUTTON`.
- Its edges resize it, and it keeps its size when moved between monitors with different scaling.
- Double-clicking the header bar maximizes or restores it, and Alt+Space opens the system menu.

Closing still leaves AppKata in the tray (R1.7.1).

R15.14. **Registering with Windows.** All of this is under HKCU and needs no UAC prompt.

- **Start in the tray at login** (R1.7.4): an `AppKata` value under
  `Software\Microsoft\Windows\CurrentVersion\Run` that runs `"…\appkata.exe" --tray`. Settings
  shows the value's real state, because Task Manager can also turn it off.
- **Open appkata:// links** (R11.3): `Software\Classes\appkata`, with `URL Protocol` and
  `shell\open\command` set to `"…\appkata.exe" "%1"`. The setup registers it (R15.10); the
  setting does it for other builds.
- **Notifications** (R9.3): AppKata sets its AppUserModelID, `AppKata.AppKata`, at startup, the
  same as on its Start-menu shortcut, so its toasts are shown as AppKata's. Clicking an update
  toast, including one in the Action Center, opens the Apps view.

R15.15. **git and gpg** (R1.4). When git is missing, AppKata suggests `winget install Git.Git`.
AppKata looks for `gpg` on the PATH, then in Git for Windows' `usr\bin` (found from
`git --exec-path`).

R15.16. **Files and processes.**

- App folder and file names avoid the names Windows reserves (`CON`, `PRN`, `AUX`, `NUL`,
  `COM1`–`COM9`, `LPT1`–`LPT9`, with any extension), and trailing dots and spaces, by adding `_`.
- Names are compared without case, so two apps can't get the same folder.
- Paths longer than 260 characters use the `\\?\` prefix, so deep archives and Trust clones work
  without Windows' long-path setting.
- An app AppKata opens is started detached (`DETACHED_PROCESS`), so it keeps running when
  AppKata quits.

R15.17. **TLS certificates** are checked by Windows itself (`truststore`). Python's own check sees
only the root certificates already in Windows' store, while Windows fetches missing roots when
it needs them, so downloads from some hosts (GitHub's file host among them) would fail.

R15.18. **The Visual C++ run-time.** Some apps need Microsoft's Visual C++ run-time
(`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`). Mostly these are portable `.zip`
files, such as Rust and C++ command-line tools; installers usually bring the run-time
themselves. One package covers every app built with Visual Studio 2015 to 2022: the
**Microsoft Visual C++ 2015–2022 Redistributable**, x64. Any copy at least as new as the app's
works, so the latest serves all of them. The older run-times (2005–2013) aren't handled.

R15.18.1. **Detecting it.** After unpacking a portable app, AppKata reads the import table of each
`.exe` and `.dll` in it. When one imports a run-time DLL that isn't in the app's own folder, the
app needs the run-time, and AppKata records that with the install. Trusts don't declare it in
AppKata.md: the app's own files decide.

R15.18.2. **Showing it.** An app that needs it has an **MSVCRT** chip (tooltip "Microsoft Visual
C++ Run-time") on its Apps row and in the App Detail panel. The chip is in the warning colour
when the run-time is missing from this computer, and clicking it then offers to install it
(R15.18.3). AppKata finds an installed copy from the registry
(`HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64`, `Installed` and `Version`), or
from `vcruntime140.dll` in `System32`.

R15.18.3. **Installing it.** When an app that needs the run-time is installed and the run-time is
missing, AppKata offers **Install the Visual C++ run-time**. It downloads Microsoft's
`vc_redist.x64.exe` (`https://aka.ms/vs/17/release/vc_redist.x64.exe`), checks its Authenticode
signature (R15.11; the signer must be Microsoft Corporation), and runs it with
`/install /quiet /norestart`, elevated as R15.7.5 says, from a copy held to the file whose
signature was read; exit code 1638 (a newer copy is already installed) counts
as done. Installing it is recorded in the Audit (R13.3). The run-time installs only for everyone, so this one step
asks for administrator rights even for an app that is Just me (R15.4). The dialog says why. Exit
codes are read as for other installers (R15.7.3). This normally happens once per computer.

R15.18.4. **Never removed.** Other software shares the run-time, so AppKata doesn't track it as an
app, never uninstalls it, and doesn't copy its DLLs into app folders.
