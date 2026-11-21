# R7. Sources perspective

R7.1. **Sources list.** The main area of the Sources perspective is a vertical scrolling list
of Sources.

R7.1.1. Each row shows:

- The app's icon and name.
- The Source URL, in monospace.
- **Also in trusts**: when Trusts also list the app (R2.9.4), a pill with their avatars and
  "In 2 trusts". Hovering it lists the Trusts by name, each with **Open**. Clicking it opens the
  Trust when there is one, or keeps the list open when there are several (R2.9.5).
- The detected forge type.
- The latest version and its date, and the installed version if any.
- State chips: Installed, **Installed outside AppKata**, **Built in** (R2.11.1), Pinned, Track only.
- An error, if any (R2.10).
- A ⋯ menu.

R7.1.2. Apps that only Trusts list (R10.5) are not rows here, including installed ones
(R2.9.2).

R7.1.3. The row's ⋯ menu has:

- **Pin** or **Unpin**.
- **Source settings…** (R2.6).
- **Open project page**.
- **Remove source**.

R7.1.4. The title row holds, from left to right after the title: a **Filter** box, an
**Explore** button (R7.7) and the **+ Add source** button.

R7.2. **Adding a Source.** The **+ Add source** button opens a dialog:

1. Enter a URL (R2.2).
2. AppKata detects the forge type (R2.4) and shows a preview: icon, name, latest version and
   the asset it would choose.
3. The user can open **Source settings** to adjust them.
4. **Add** saves the Source.

If the app is foreign-installed (R4.5), the preview says so. If Trusts already list the app, the
preview says "Already listed by desk-collective / reviews". Adding it anyway is allowed and
makes it the user's own Source as well.

R7.3. **Removing a Source.**

R7.3.1. If AppKata installed the app, the confirmation offers **Remove and uninstall** and
**Remove only**.

R7.3.2. **Remove only** warns that the app will stay installed but will get no more updates.
This warning appears only when no enabled Trust lists the app. If one does, the dialog instead
says "Also listed by N trusts, so it stays in the Catalog." AppKata never updates an app that
isn't installed.

R7.4. **Pinning** (R9.5.1) is set from a Source's ⋯ menu (R7.1.3), and for any installed app from
the App Detail panel (R5.7.1). Minimum age is set only in Settings (R9.5.2, R11.1.3).

R7.5. **Removing a Trust.** If an installed app has no other origin, the confirmation warns
that the app will get no more updates. It lists them and offers **Keep updating as my sources**, which
adds them as Sources and then removes the Trust. This is the only case where AppKata turns a Trust's app into a Source,
and only when the user asks.

R7.6. **Trust panel.** A collapsible panel on the right side of the Sources perspective lists
the Trusts (R10). When it is collapsed, it becomes a narrow rail with a shield icon and a
warning dot if any Trust needs attention.

R7.6.1. A **Trust** is a git repository URL. It may be the repository root, or point to a
specific `AppKata.md` file.

R7.6.2. **Adding a Trust.** The **+ Add trust** button opens a dialog:

1. Enter a URL.
2. For a root URL, AppKata looks for `AppKata.md` in the root, then in `docs/`. The file must
   exist.
3. AppKata checks that the commits that last changed `AppKata.md` are signed (R10.7).
4. It shows each signing key: its type, its fingerprint, and the identity it maps to.
5. The user picks the Trust's **Score** (R7.6.8; default 3 stars).
6. The user confirms. The Trust and one **Authority** record per signing key are created.

R7.6.3. **Trust rows** form a vertical scrolling list. Each row shows:

- The Trust's name: the repo owner and name, or the file's title.
- Its Score (R7.6.8) as 1–5 stars in the accent colour.
- The number of apps it lists.
- When it was last synced.
- Partly overlapping avatars of its enabled Authorities. After four, a "+N" chip is shown
  instead of more avatars.
- A warning indicator when the Trust needs attention: an unsigned change, a commit by an
  unknown signer (R10.8), or parse warnings (R10.2).

R7.6.4. Hovering an avatar shows a popup with details of the signer:

- Name and avatar.
- Email, or NIP-05 for Nostr keys.
- Key type (GPG, SSH or Nostr) and fingerprint.
- When the key was first and last seen.
- Whether it is enabled.

The popup closes by itself about 3 seconds after the pointer leaves.

R7.6.5. **Trust Detail panel.** Clicking a Trust row opens a Trust Detail panel at the bottom
of the Trust panel. Its **X** button closes it. It shows:

- The URL and file path.
- Its **Score** (R7.6.8), with a 1–5 star picker. The user's own file shows a fixed 5 stars.
- The last verified commit.
- The number of apps listed.
- Parse warnings (R10.2).
- A scrolling list of Authorities, each with an avatar, name, key fingerprint, an enable
  switch and a remove button.
- A **Remove trust** button.

R7.6.6. A **new signer** (R10.8) appears in the Authority list as a pending Authority, marked
"New signer · not trusted", with **Trust signer** and **Ignore** buttons.

R7.6.7. **Order.** Wherever Trusts are listed (the Trust panel, the "In N trusts" popup on a
Source row, an app's reviews in the App Detail panel), they are sorted by Score,
highest first, then by name. The user's own file comes first.

R7.6.8. **Score.** Each Trust has a Score from 1 to 5 stars (no 0): how much its reviews count in
the combined score (R10.6.2). A new Trust starts at 3. The user's own `AppKata.md` is fixed at 5.
Changing a Score is recorded in the Audit (R13.3).

R7.7. **Explore.** The **Explore** button opens a dialog for finding projects to add as Sources.

R7.7.1. The first field is a segmented picker like the perspective switcher: **GitHub**,
**GitLab** (gitlab.com), **Codeberg**, **ngit**, and on Linux **Flathub** and the distribution
(R16.2.3). Changing it repeats the search there.

R7.7.2. A search box with a **Search** button. Searches use each service's public search:

| Service | Search |
|---|---|
| GitHub | `api.github.com/search/repositories`; when rate-limited, github.com's own search results (JSON) |
| GitLab | `gitlab.com/api/v4/projects?search=`, ordered by stars |
| Codeberg | `codeberg.org/api/v1/repos/search`, ordered by stars |
| ngit | Repository announcements (NIP-34, kind 30617) from the Nostr relays (R11.1.4), matched on name, description and identifier |

R7.7.3. Each match is a minimal summary: owner and name, description (one line), stars,
language, last activity, and **Archived** or **In your trusts** chips when they apply. Each has
two small icon-only buttons, labelled by tooltips so they don't outweigh the matches:

- **Project page** (open icon): opens it in the browser (tooltip "Open on gitworkshop.dev" for
  ngit).
- **Add source** (plus icon, in the accent colour): opens Add source (R7.2) with its URL. When
  the project is already a Source it shows a check, is disabled, and its tooltip says
  "Already a source". For ngit it is disabled until ngit Sources exist (R2.4.3), and its tooltip
  says so.

R7.7.4. Errors (no network, rate limits, unreachable relays) are shown in the results area.
