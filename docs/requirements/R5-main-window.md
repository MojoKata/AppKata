# R5. Main window

R5.1. The main window has four perspectives, chosen from a segmented switcher in the header
bar:

- **Apps**: the default when any app is installed. Shows the apps AppKata installed.
- **Catalog**: the default otherwise. Shows the apps available.
- **Sources**: manages Sources and Trusts.
- **Audit**: the record of key operations (R13).

R5.2. The design goal is a visually delightful, simple interface: generous spacing, soft cards,
clear typography. Dark is the main design target, and both themes use the design tokens in
`Theme.qml`.

R5.2.1. **Design point.** The window is designed for a 1920 × 1080 screen, a 1080p laptop's, with
AppKata maximized on it: whatever that leaves the window, which is 1920 × 1040 beside Windows'
taskbar or Linux Mint's panel at 100% scaling. The screenshots and the tour's layout check are made
at that size, and smaller windows aren't tested.

R5.3. **Header bar.** The window draws its own header bar instead of a system title bar. Dragging
it moves the window, and double-clicking maximizes or restores. It holds:

- The app icon and name.
- The perspective switcher. The Apps segment shows a count badge when updates are available.
- A sync indicator (R9.2).
- The app menu (⋮).
- On Windows, **Minimize** and **Maximize** (**Restore** when maximized) before the close button
  (R15.13).
- A close button, which closes the window to the tray (R1.7.1).

R5.4. **App menu (⋮).** In this order:

1. **Sync** (R9.2), with the time of the last sync as subtext.
2. **Settings…** (R11).
3. The theme: Match system, Dark, Light.
4. **Show app log** (R14.5).
5. **About AppKata**.
   - **Install AppKata…**, after About, only for an AppImage running from outside the install
     folder that wasn't installed (R2.11.3.1).
6. **Close window**.
7. **Quit AppKata**, with its shortcut: Alt+Q, which works anywhere in the window.

R5.4.1. **About AppKata** opens a dialog with the app icon, name and version, a one-line
description, the license (GPL-3.0-or-later), the project link (R2.11.1), the platforms it runs on, what it's built with,
and **Check for updates** (which starts a sync, R9.2) and
**Close** buttons.

R5.5. Errors and confirmations of finished actions are shown in a short-lived message at the
bottom of the window.

R5.6. **App Detail panel.** Clicking an app in Apps or Catalog opens a closable App Detail
panel docked to the right. It is the same panel in both perspectives (R5.7).

R5.7. **Contents of the App Detail panel.** From top to bottom:

R5.7.1. A header row with the "APP DETAILS" label, the pencil button (R8.6), a ⋯ menu and the
close button. For installed apps, the ⋯ menu has **Pin** / **Unpin** (R9.5)
and **Open project page**.

R5.7.2. The hero image (R3.3), with the icon overlapping its lower-left corner.

R5.7.3. The name, the project host and path, and a **From** row listing the app's origins
(R2.9). The row shows a "Source" pill if the app is a Source, and one pill per Trust with that
Trust's avatar and name. Each pill links to its Source row or Trust (R2.9.5).

Then the chips that apply:

- Verification (R4.4).
- **Installed outside AppKata** (R4.5).
- Pinned.
- Track only.
- For a channel install (R16): the channel and its publisher ("Flathub · verified"), and who
  updates it (**Updated by the system**, **Not updated automatically**, R16.5.1).

R5.7.4. Action buttons, each an icon plus a word:

- Not installed: **Install**; **Adopt** for an adoptable foreign install (R16.4.2).
- Installed by AppKata: **Update** (only when an update is available, R9.4), **Uninstall**,
  and **Open**.
- While it installs: the phase in the Install or Update button, and **Cancel** (R4.8).

**Open** on a system package (R16.3) starts the app-menu entry the package installed, as the
desktop does (`gio launch`, else `gtk-launch`): the one named after the package when it has several,
never one the menu doesn't show (hidden, meant for other desktops by `OnlyShowIn` or `NotShowIn`, or
for a program that isn't installed, by `TryExec` or its `Exec`); when it installed none, the entry of a program it installed
(Ubuntu's `neovim` installs `nvim`, whose entry is `neovim-runtime`'s). A package's program is often
named otherwise (`libreoffice-writer` installs `lowriter`). A package with no such entry isn't
opened: AppKata says "<App> has no app-menu entry to open it with".

There is no "Add to sources" action for an app that comes from a Trust (R2.9.2).

R5.7.5. Version information:

- The installed version.
- The latest version and its date.
- Whether the update is held back (R9.4).

R5.7.5.1. **Versions**: a list of the app's releases, newest first. Prereleases are left out
unless prereleases are on (R11.1.2) or one is installed.

- It shows the newest available version, the installed version, and up to 5 versions older
  than the lower of the two.
- The installed version has a "▶" marker on its left, the row is tinted in the success
  colour, and it says "Installed".
- The newest available version has a "★" after it.
- Every other row has small icon-only buttons on the right, labelled by tooltips: **Install**
  (download icon; **Update**, in the accent colour, for the newest when an older one is
  installed). Installing a version older than the newest **pins** the app at that version
  (9.5), so the next sync doesn't upgrade it again; a note under the list says so.
- A version kept in the app's folder (R4.3.1.5) has a **Kept** chip; its install button's tooltip
  says it reinstalls without downloading, and a red trash button (tooltip "Remove this version")
  deletes it.
- When there are more versions, a link-style "Show next 5 older" item extends the list by 5.
- A version's files that the last sync didn't read are fetched when it's installed.

R5.7.6. **Reviews**: the combined Trust and Rating (R10.6), then one row for each Trust that
lists the app. Each row shows:

- The Trust's avatar stack and name. The name links to the Trust (R2.9.5).
- That Trust's Trust value, Rating and tags for the app.
- A disclosure arrow that expands the review section (R10.3) as rendered Markdown.

The first review with a section starts expanded. The user's own review, when there is one,
comes first and is labelled "Your review".

R5.7.7. **Release notes** for the latest version, collapsed after 6 lines.

R5.7.8. The **README** (R3.4).

R5.7.9. The panel scrolls (with a scroll bar) whenever its content is taller than the
window, so long lists of origins, versions and reviews stay reachable.

R5.8. **Confirmations.** Every removal asks first, in a short dialog with **Cancel** and a button
named for the action (red for removals). The ones that ask, with their screenshots:

| Action | Where | The dialog says |
|---|---|---|
| Uninstall (R4.7) | Apps row trash, App Detail | "<App> <version> will be removed. Your settings and documents in your home folder are kept." |
| Remove a kept version (4.3.1.5) | App Detail → Versions | "This kept version will be deleted…" |
| Remove source (R7.3) | Source ⋯ menu | Its own dialog: **Remove and uninstall** / **Remove only** |
| Remove trust (R7.5) | Trust Detail | Its reviews leave the Catalog; installed apps with no other origin are listed, with **Keep updating as my sources** |
| Remove an Authority | Trust Detail (red trash) | "Changes signed only by this key will no longer be accepted…" |
| Trust signer / Ignore (R10.8) | Trust Detail, new signer | What accepting, or ignoring, their changes means |
| Remove a token, a relay | Settings (R11.1.6, R11.1.7) | What AppKata does without it |
| Quit while installing (R1.7.3) | ⋮, tray, Alt+Q | The installs that will stop |
