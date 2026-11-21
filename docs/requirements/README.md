# AppKata: requirements

AppKata is a cross-platform (Linux, macOS, Windows 10+) FOSS app store built on Git and ngit
(Nostr Git). Each app is a git project. Its releases are found from the project's forge,
AppKata installs and updates them, and reviewers publish trust and ratings in signed
`AppKata.md` files.

These files say what AppKata is and does. Why a part of it is built the way it is, where that
takes more than a sentence, is in the design documents beside them, such as [`../app-sandboxing.md`](../app-sandboxing.md). Mockups live in
[`../../screenshots`](../../screenshots/README.md), and
[`../requirements-trace.md`](../requirements-trace.md) maps the sentences of R17 to the tests that
show them.

**How the requirements are organised.** Each section below has a file of its own, R1 to R17. A
section's items are numbered within it: `R17.4` is item 4 of the app sandboxing section, and
`R17.6.2` item 2 under it. A reference names an item by its id, and the doc check
(`tests/test_doccheck.py`) fails on an id that names nothing.

1. **Lasting ids.** Section ids (R1, R2, …) and their items (`R17.4`, `R17.6.2`) are never
   renumbered or reused: a new section or item takes the next free number, and one that is
   removed leaves its number unused.
2. **Splitting a section.** A section file that grows past 500 lines becomes a folder,
   `RN-name/README.md`, that keeps the section's introduction and a table of its first-level
   items, each in a file of its own named by its id (`R17-app-sandboxing/R17.4-the-launcher.md`
   holds R17.4). References do not change.
3. **A statement, not a changelog.** The requirements say what AppKata is and does, in the
   present tense, and carry no dates, versions or status of their own; git holds their
   history, and the repository's README says where the build stands.
4. **Questions, gaps and other issues** are GitHub issues, cited by number and linked to the
   issue: `[Q#n]` a question that waits on a decision (labelled `question`), `[G#n]` a gap, a
   part not yet specified or built, and `[#n]` any other issue.

# 1. Platform and architecture

[R1](R1-platform-and-architecture.md): the platforms AppKata runs on, Python and PySide6, one
desktop-user process, git and Nostr, how AppKata is distributed, the tray, local data and one
AppKata at a time.

# 2. Apps and Sources

[R2](R2-apps-and-sources.md): what an app and a Source are, normalizing URLs, the forges and
their releases, Source settings, origins, and AppKata as its own built-in Source.

# 3. App metadata

[R3](R3-app-metadata.md): an app's icon, name, description, README and images.

# 4. Installing, updating and uninstalling

[R4](R4-installing-updating-and-uninstalling.md): choosing the file, the install layout, system
packages, verification, foreign installs, progress, the install dialog, apps that update
themselves, and uninstalling.

# 5. Main window

[R5](R5-main-window.md): the header bar, the perspectives, the ⋮ menu, the look, the App Detail
panel and confirmations.

# 6. Apps perspective

[R6](R6-apps-perspective.md): the list of installed apps and their states.

# 7. Sources perspective

[R7](R7-sources-perspective.md): Sources, Trusts and Authorities, their dialogs, and Explore.

# 8. Writing reviews

[R8](R8-writing-reviews.md): the review dialog, the Trust and Rating pickers, and signing on
save.

# 9. Sync and updates

[R9](R9-sync-and-updates.md): what Sync refreshes, background checks, versions, pinning and the
minimum age.

# 10. Trust and the AppKata.md file

[R10](R10-trust-and-the-appkata-md-file.md): the `AppKata.md` format, version reviews, tags,
combining Trusts, signatures and Authorities.

# 11. Settings

[R11](R11-settings.md): the Settings dialog, its groups, and `appkata://` links.

# 12. Catalog perspective

[R12](R12-catalog-perspective.md): the Catalog's tiles, search, filters and sort.

# 13. Audit

[R13](R13-audit.md): the record of what the user and AppKata did.

# 14. App log

[R14](R14-app-log.md): AppKata's own log files and how to read them.

# 15. Windows

[R15](R15-windows.md): what is specific to Windows: elevation, who an app is for, shortcuts,
command links, installers, files in use, signatures and the Visual C++ run-time.

# 16. Package channels (Linux)

[R16](R16-package-channels.md): Flatpak and the distribution's packages as channels for an app,
linking and checking them, who updates an app, and the package backend.

# 17. App sandboxing (Linux)

[R17](R17-app-sandboxing/README.md): levels, grants and templates, the launcher, the filtered
session bus, app identity, display and sound, AppArmor setup, and the limits.
