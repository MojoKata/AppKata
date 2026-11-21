# R12. Catalog perspective

R12.1. The Catalog should look like a cool, modern app store for browsing the available apps
(10.5).

R12.2. **Title row.**

- "Catalog" with the app count.
- A **search box** that matches name, summary, tags and Source URL.
- **Tag filter chips**: the most-used tags, plus **More…**, which opens a popup of every tag
  ("All tags · 10"). A tag chosen there replaces "More…" as the chip's label while it filters.
  Clicking a tag chip on a tile, in a tile's tags popup or on a review filters the Catalog by
  that tag.
- A **sort** select: Trust, Rating, Recently updated (newest release first), Name. The default is Trust (highest
  first), then name. Every sort falls back to name for ties. Unreviewed apps sort after
  reviewed ones when sorting by Trust or Rating.

R12.3. **Tiles.** Apps are tiles that flow left to right and wrap. Tiles are responsive: a tile is
designed at 300 × 210 px and scales with its width, keeping that aspect ratio, between 280 px and
2× that size.

R12.4. **Tile contents.**

- The icon (56 px).
- The name and latest version.
- The origin (2.9.3): the branch icon for a Source, and the avatars of the Trusts that list
  the app.
- The summary (3.4.1), up to three lines.
- At the bottom: the combined Trust (shield) and Rating (stars) with the reviewer count, or
  "Unreviewed"; the app's tag chips (12.4.1); and a state mark: **Installed**, **Update**, or
  **Installed outside AppKata**.

R12.4.1. **Tags on a tile.**

- Tags are shown in the order the Trusts list them, for as many as fit on the footer line
  beside the Trust badge.
- If they don't all fit, the tile drops tags from the end until there is room for a small
  **›** button at the end of the line.
- Hovering the button, or focusing it with the keyboard, shows a popup listing all of the
  app's tags with the count ("5 tags"). Warning tags (10.4.3) keep their warning colour. The
  popup closes when the pointer leaves it or focus moves away.

R12.5. Clicking a tile opens the App Detail panel (5.6). The selected tile is outlined in the
accent colour.

R12.6. **Vetoed apps** (10.6.1) are not shown unless they match the current search text.
Clearing a search hides them again.

R12.6.1. When shown, a vetoed tile is dimmed and has a red **Avoid** badge with a warning icon.
The App Detail panel shows a red banner: "A trusted reviewer says to avoid this app".

R12.6.2. If the search also matches vetoed apps, a line at the end of the results says
"N apps hidden by trusted reviewers are shown because they match your search."

R12.7. **Empty state.** With no Sources and no Trusts, the Catalog shows "Add a source or a
trust to fill your catalog", with **Add source** and **Add trust** buttons.
