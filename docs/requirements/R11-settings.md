# R11. Settings

R11.1. **Settings** (from ⋮) is a scrolling dialog. Each setting is a row: its name and a short
hint on the left, its control on the right. Every control (switches, fields, folder buttons,
selects, list buttons) ends on the same right edge. Changes apply immediately; the dialog has only a
**Close** button. The groups, in order:

R11.1.1. **General**: the theme (Match system, Dark, Light; the same choice as in ⋮), **Start in
the tray at login** (R1.7.4; an autostart entry that runs `appkata --tray`; on Windows, R15.14), and **Open
appkata:// links** (R11.3).

R11.1.2. **Reviews**: the path to the user's `AppKata.md` (a text field and an icon-only folder button, tooltip "Browse…"), and the
default auto-commit and auto-push choices (R8.3; push requires commit).

R11.1.3. **Updates**:

- Check for updates: Off, Every hour, Every 6 hours, Every day.
- Notify me about updates.
- Include pre-releases, for apps without their own setting.
- Minimum age in days, for every app (R9.5.2). This is the only place it is set.

R11.1.4. **Portable apps** (R4.3.1): the install folder (with an icon-only folder button, tooltip "Browse…"), Add to the app menu,
Stable name for the current version, Command links, the command links folder, and **Keep older
versions** (per app; default 2). These are the defaults copied into each newly installed app
(R4.3.1.6).

The group's hint says when its settings apply: "New installs take these settings. An app already
installed stays in its folder and keeps the options it was installed with (its Install options
change them); the command links folder and Keep older versions apply to it at its next update."
(R4.3.1: an installed app keeps its folder; R4.3.1.3, R4.3.1.5.)

On Windows the group also has **Install apps for** (Just me, Everyone; R15.4), and two install
folders in place of one: **For me** (default `%LOCALAPPDATA%\Programs`) and **For everyone**
(default `C:\Programs`). The command links folder defaults to `%LOCALAPPDATA%\AppKata\bin`
(R15.6).

R11.1.4.1. **List settings** (tokens, relays) look the same: each item has a red, icon-only
trash button (tooltip "Remove") on the right; the add row ends with an icon-only "+" button
(tooltip "Add token", "Add relay"), enabled once the fields are valid. These buttons line up on
the right edge of the dialog.

R11.1.5. **Sandbox** (Linux; R17.15): system support with **Set up…** and **Repair…**, the warnings
for the session (R17.9), the default template for new apps by kind, following the reviewers'
suggestions, the review badge, the built-in templates and the sandbox home folders.

R11.1.6. **Accounts and tokens**: one row per host with a token, showing only its last four
characters and a trash button; then a host field, a hidden token field and a "+" button. The help
text explains that tokens raise rate limits (GitHub allows 60 requests an hour without one),
are only sent to their own host, and are never exported.

R11.1.7. **Nostr relays** (R1.5): the relay list, each with a trash button, and a field and "+"
button to add one (`wss://…`).

R11.1.8. **Data**: where AppKata keeps its files (R1.8), each with an icon-only folder button
(tooltip "Open folder"):

- **Database**: the SQLite file.
- **App log**: the log folder (R14.3), and an icon-only external-link button (tooltip "Show")
  that opens the log (R14.5).
- **Import and export** (R11.2): **Import…** (download icon) and **Export…** (floppy-disk icon).

R11.2. **Import and export.** Sources (with their settings), pins, Trusts (with
their Authorities and Scores) and settings are exported to a JSON file. Tokens and the review file path
are not exported. Importing adds what isn't already there and leaves existing Sources and
Trusts as they are. An imported Trust is accepted only if the commit that last changed its
`AppKata.md` is signed by one of its exported Authorities. A plain text file of URLs (one per
line, `#` for comments) can also be imported as Sources. Import and export are recorded in the
Audit (R13).

R11.3. **Deep links.** `appkata://add/<url-encoded source URL>` opens the Sources perspective and
the Add Source dialog with the URL filled in. On Linux, **Open appkata:// links** registers
AppKata as the desktop's handler for `appkata:` links; on Windows, see R15.14.
