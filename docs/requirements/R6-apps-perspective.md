# R6. Apps perspective

R6.1. The Apps perspective is a vertical scrolling list of the apps AppKata installed (4.1).
Each row shows:

- The small icon (32 px).
- The name.
- The installed version. When an update is available: installed → new version.
- The origin (2.9.3): "Source", the Trust's name, or "Source · 2 trusts".
- For a channel install, its channel and update chip (16.5.1); for an avoided version, a red
  **Avoid** pill (10.6.5).
- Small icon-only buttons for **Update** and **Uninstall**.

R6.2. **Sort order.** Apps with an update available come first, and are marked with an accent
stripe, an "Update available" pill, and an accent Update button. Everything else follows,
sorted by name. Within the update group, apps are also sorted by name.

R6.3. **Held-back updates.** An update held back by pinning or minimum age (9.4) doesn't count
as available. It doesn't sort the app to the top, and its row shows a muted "Pinned" or
"Held · 3 days left" note instead of an Update button.

R6.4. **Title row.**

- "Apps" with "N installed · M updates".
- **Update all**, when updates are available.
- A filter box.

R6.5. Clicking a row opens the App Detail panel (5.6). The selected row is highlighted.

R6.6. On a row, Update and Uninstall are icon-only buttons with tooltips. In the detail panel
the same icons appear with the words "Update" and "Uninstall".

R6.7. **Empty state.** When nothing is installed, the view shows "No apps installed yet" and
a button that opens the Catalog.
