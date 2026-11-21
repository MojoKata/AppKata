# R17. App sandboxing (Linux)

AppKata installs apps from the projects' own releases, so it can't vouch for what's inside them;
Trusts and reviews lower the odds of a hostile app, they don't contain one. This section limits the
harm a **portable app or AppImage** can do to the rest of the computer once installed. The rationale,
the experiments behind each decision, and the mockups are in [`app-sandboxing.md`](../../app-sandboxing.md);
the human validation checklist and an explanation of the launcher and the proxy are in
[`local-proxy-test-plan.md`](../../local-proxy-test-plan.md) (`scripts/sandbox/field-test.sh`); the launcher's
exact text is the goldens in `tests/data/launchers/` (R17.4). Deferred
items are listed at R17.18.

Each first-level item has a file of its own.

| Id | Item |
|---|---|
| **R17.1** | [Scope](R17.1-scope.md) |
| **R17.2** | [Levels and grants](R17.2-levels-and-grants.md) |
| **R17.3** | [Templates](R17.3-templates.md) |
| **R17.4** | [The launcher](R17.4-the-launcher.md) |
| **R17.5** | [Filtered session bus](R17.5-filtered-session-bus.md) |
| **R17.6** | [App identity](R17.6-app-identity.md) |
| **R17.7** | [AppImage](R17.7-appimage.md) |
| **R17.8** | [Sound](R17.8-sound.md) |
| **R17.9** | [Display and the session warning](R17.9-display-and-the-session-warning.md) |
| **R17.10** | [AppArmor setup](R17.10-apparmor-setup.md) |
| **R17.11** | [Where permissions come from](R17.11-where-permissions-come-from.md) |
| **R17.12** | [Self-update](R17.12-self-update.md) |
| **R17.13** | [Enabling a sandbox after install](R17.13-enabling-a-sandbox-after-install.md) |
| **R17.14** | [Uninstalling](R17.14-uninstalling.md) |
| **R17.15** | [Settings → Sandbox](R17.15-settings-sandbox.md) |
| **R17.16** | [The Audit](R17.16-the-audit.md) |
| **R17.17** | [Limits](R17.17-limits.md) |
| **R17.18** | [Deferred to later releases](R17.18-deferred.md) |
