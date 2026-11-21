# A1. App sandboxing (Linux)

AppKata installs apps from the projects' own releases, so it can't vouch for what's inside them;
Trusts and reviews lower the odds of a hostile app, they don't contain one. A1 is how
AppKata limits the harm an app does to the user's computer once it's installed.

**Scope.** Linux only, and only the two portable kinds AppKata installs itself (R4.2.1):

- **AppImage** (`kind == "appimage"`)
- **Portable archives**: tarballs (`kind == "tarball"`), unpacked into versioned folders

Out of scope: `.deb`/`.rpm` (their scripts run as root at install time, so a run-time sandbox can't
undo what they did), Flatpak (already sandboxed; AppKata shows its permissions, R16.6.3), shell
installers (`.run`/`.sh`, not supported, and they stay unsupported), and Windows.

The requirements are [R17](../../requirements/R17-app-sandboxing/README.md); this is why each choice
was made, the evidence behind it and the mockups. Each first-level item has a file of its own.

| Id | Item |
|---|---|
| **A1.1** | [What a hostile app can do today](A1.1-what-a-hostile-app-can-do.md) |
| **A1.2** | [Approach](A1.2-approach.md) |
| **A1.3** | [Templates](A1.3-templates.md) |
| **A1.4** | [App categories (separate work)](A1.4-app-categories.md) |
| **A1.5** | [AppImage](A1.5-appimage.md) |
| **A1.6** | [Portable (tarballs)](A1.6-portable.md) |
| **A1.7** | [Screens](A1.7-screens.md) |
| **A1.8** | [Experiment](A1.8-experiment.md) |
| **A1.9** | [Limits](A1.9-limits.md) |
| **A1.10** | [UI text and its evidence](A1.10-ui-text.md) |
| **A1.11** | [Claims and their evidence](A1.11-claims.md) |
| **A1.12** | [Decisions](A1.12-decisions.md) |
