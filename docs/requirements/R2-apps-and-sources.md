# R2. Apps and Sources

R2.1. An **app** is identified by a git project URL. An app reaches AppKata in one of two ways
(2.9):

- From a **Source**: a project the user has decided to trust themselves.
- From a **Trust**: a reviewer's claim (10) that the user trusts to provide such information.

A Source usually represents one app.

R2.2. A Source URL can be:

- A forge project URL, such as `https://github.com/owner/repo`.
- A direct link to a project's releases page (2.5).
- An ngit repository, as `nostr://<npub>/<identifier>` or an `naddr`.

R2.3. **Normalizing URLs.** Before Source URLs are stored or compared, they are normalized:

1. Lowercase the scheme and host.
2. Strip a trailing `/` and `.git`.
3. Map `git@host:owner/repo` to `https://host/owner/repo`.

URLs that are the same after this are the same app.

R2.4. **Finding releases.** AppKata decides how to read a Source's releases as follows.

R2.4.1. Known hosts:

| Host | Releases |
|---|---|
| github.com | `api.github.com/repos/{o}/{r}/releases`. When the API's rate limit is used up (60 requests an hour without a token), github.com's own pages instead: the releases Atom feed, less the bare tags it also lists (one not on the releases page whose own page says it was tagged, not released), each release's assets page (names, sizes, SHA-256 digests) and a shallow, blob-less clone for the file list |
| gitlab.com | `/api/v4/projects/{id}/releases`, including subgroups. Assets are read from `assets.links` and from `/uploads/` links in the release description. |
| codeberg.org | `/api/v1/repos/{o}/{r}/releases` |
| git.sr.ht | The `refs/rss.xml` feed and the files attached to each ref |

R2.4.2. Other hosts are probed in this order:

1. `/api/v1/version` (Gitea or Forgejo).
2. `/api/v4/projects?per_page=1` (GitLab; `/api/v4/version` needs a token).
3. `/api/v3/meta` (GitHub Enterprise).
4. The page's `<meta name="generator">` tag.

The forge type found is stored with the Source.

R2.4.3. **ngit Sources.**

1. AppKata resolves the repository announcement (NIP-34, kind 30617).
2. If one of its `web` or `clone` URLs is on a supported forge, releases come from that
   forge.
3. Otherwise, AppKata uses the release events Zapstore publishes (NIP-82 software
   applications, 2.4.3.1), or an AppKata manifest (2.7).
4. If neither exists, the Source is **track only** and versions come from tags.

R2.4.3.1. **Zapstore events.** AppKata reads the event format defined by Zapstore (NIP-82):

| Kind | Event | Used for |
|---|---|---|
| 32267 | Software application | Name, summary, icon, images, platforms. Identified by its `d` tag, the app ID. |
| 30063 | Software release | One version of the app, pointing to its assets |
| 3063 | Software asset | One file: `url` (often a Blossom server), `x` (SHA-256), `version`, `f` platform tags such as `linux-x86_64`, `windows-aarch64`, `darwin-arm64`, and its MIME type and size |

- The legacy kind 1063 (NIP-94 file metadata) is also read, as an asset.
- AppKata finds these events on the repository's relays and on the user's relays (11.1.4).
- Only events signed by one of the repository's maintainers count.
- The asset's `x` hash is a checksum for verification (4.4).

R2.4.4. The following hosts have no reliable way to get from a project URL to release files:

- Bitbucket, Gogs, Launchpad, Pagure, Azure DevOps, AWS CodeCommit and Radicle.
- cgit, gitweb and plain git servers.
- Any page not identified by 2.4.2.

They need a direct releases link (2.5), a manifest (2.7), the generic HTML source (2.6.3),
or track only (2.6.1).

R2.5. **Direct releases link.** A Source may be added with a releases page URL instead of the
project URL, for example `https://host/owner/repo/releases`. The Source then also records the
project URL, which is used for the README and images.

R2.6. **Source settings.** These are optional and set per Source:

R2.6.1. **Track only.** AppKata reports new versions but does not install them.

R2.6.2. **Release selection:**

- Include prereleases. Draft releases are never used.
- A release-title filter regex.
- A version-extraction regex, with the match group to use.
- Use the release date as the version.
- Fall back to older releases when the newest has no suitable asset.

R2.6.3. **Generic HTML source.** For a page that isn't a forge:

1. Collect the page's links and filter them with a regex.
2. Optionally follow a chain of intermediate-link regexes to the download.
3. Optionally extract the version from the page.

When no version string can be found, the version is a pseudo-version: the asset's ETag, or a
hash of its link.

R2.6.4. **Asset filter.** A regex for each OS and architecture that overrides automatic asset
selection (4.2). The dialog edits the filter for the current platform and keeps the others.

R2.6.5. **Forge type override**, used when detection (2.4.2) gets it wrong.

R2.6.6. **Pinned** (9.5.1). Minimum age is a global setting only (9.5.2).

R2.6.7. **Source settings dialog.** Opened from a Source's ⋯ menu (7.1.3), or from Add source
before the Source is saved (7.2). It holds, as label-and-hint rows like Settings (11.1):

- **Forge**: Detect automatically (showing what was detected), or "Recommended (GitLab)" when a
  Trust recommends one; GitHub, GitHub Enterprise, GitLab, Forgejo, Gitea.
- Track only and Include pre-releases are yours alone. The Forge and Download filter can come from
  a Trust's AppKata.md (10.3.1): the Forge then shows "Recommended (GitLab)", and the Download
  filter's placeholder and preview use the recommended filter. Leaving them unset keeps later
  recommendations applying.
- **Track only** (2.6.1), a switch.
- **Include pre-releases**: Default (Settings' value, as On or Off), Yes, No.
- **Download filter for <OS> <arch>** (2.6.4): a regex field and a live preview of the file it
  picks from the latest release ("AppKata's choice" when empty), or why nothing matches; an
  invalid regex disables **Save**.
- On Linux, **Flatpak** (an app ID) and **Package** (a package name) (16.1.3), with placeholders
  showing the link AppKata found and where from ("org.zettlr.Zettlr · from mara-dev / foss-picks"),
  and the link check's result (16.1.4).
- **Cancel** and **Save**. Saving records the change in the Audit and syncs the Source again.

The other release-selection settings (2.6.2) and generic HTML Sources (2.6.3) aren't built yet.

R2.7. **AppKata manifest.** A project may include an optional `.appkata.toml` in its
repository root. It may declare:

- The app's name.
- Its icon and hero image paths.
- Asset patterns for each OS and architecture.
- The install type, and silent-install arguments.

When present, its values take priority over heuristics. Source settings (2.6) take priority
over the manifest.

R2.9. **Origins.** Every app records where it comes from.

R2.9.1. An app's origin is its Source, one or more Trusts that list it (10.5), or both. Matching
uses normalized URLs (2.3).

R2.9.2. A Trust's apps are never copied into Sources. Installing, updating and uninstalling an
app work the same whatever its origin.

R2.9.3. Apps show their origin (5.7.3, 6.1, 12.4):

- A Source origin uses the branch icon and the word "Source".
- A Trust origin uses the Trust's avatar and name, or a count ("2 trusts").

R2.9.4. A Source that is also listed by Trusts is flagged on its row with the Trusts it is part
of (7.1.1).

R2.9.5. Wherever a Trust is named as an origin, it links to that Trust. Clicking it opens the
Sources perspective with the Trust selected and its Trust Detail panel open (7.6.5). The
**Source** pill opens the Sources perspective scrolled to that Source's row, highlighted for a
few seconds.

R2.10. **Errors.** Each Source records its last error, which is shown on its row (7.1.3):

| Error | Shown as |
|---|---|
| `NoReleases` | "No releases found" |
| `NoMatchingAsset` | "No download for Linux x86_64" (for the current platform) |
| `NoVersion` | "Couldn't read a version" |
| `RateLimited` | "Rate limited until 14:32" (the reset time) |
| `Renamed` | "Moved to …", with an **Update URL** button |
| `Unreachable` | "Couldn't reach the host" |

R2.11. **AppKata itself.** AppKata updates itself like any other app.

R2.11.1. Its own repository (`github.com/MojoKata/AppKata`, kept in one place in the code:
`APPKATA_REPO`) is a **built-in Source**. It is always present, its row shows
a "Built in" chip, and **Remove source** is disabled for it.

R2.11.2. AppKata shows in the Apps perspective, with its running version as the installed
version. It has no Uninstall or Open button; the App Detail panel explains why.

R2.11.3. **Run as an AppImage**, AppKata adopts its own file on first start: it records it as the
current version (marked as adopted, so it is never deleted by version retention, 4.3.1.5).
Updates install into the install folder (4.3.1) like any portable app. After an update AppKata
shows "AppKata X installed. Restart AppKata to use it." and a **Restart AppKata** button in its
App Detail panel, which starts the new version and quits.

R2.11.3.1. **First start of a downloaded AppImage.** When the AppImage runs from outside the install
folder (4.3.1), usually from `~/Downloads`, and AppKata hasn't installed itself yet, it first shows
"Install AppKata?" with the version and where it will go, then:

- **Install** (the default):
  1. Copies itself to `<install folder>/appkata/AppKata-<version>-x86_64.AppImage`, with the
     stable-name link `AppKata.AppImage` (4.3.1.2), and records that copy as the installed version.
  2. Writes `appkata.desktop` in `~/.local/share/applications/` and its icon in
     `~/.local/share/icons/hicolor/` (scalable and 256 px), pointing at the stable link. The entry's
     name matches the window's desktop file name, so the taskbar shows AppKata's icon.
  3. Points the `appkata://` handler (11.3) and the autostart entry (1.7.4), when on, at the stable
     link, so updates never break them.
  4. Starts the installed copy and quits. With **Delete the downloaded file** (checked) it deletes
     the file it was started from.
- **Run from here**: the AppImage runs where it is, adopted as before, without a menu entry; the
  question isn't asked again. **Install AppKata…** in ⋮ asks it later.

The step is recorded in the Audit. `appkata --install-self` does the same without asking (for
scripts and tests). An AppImage already in the install folder is never asked about. AppKata isn't
uninstalled from itself (2.11.2): removing `<install folder>/appkata/`, the desktop entry and the
icon removes it, and the data folder (1.8) stays until deleted.

R2.11.4. **Run from source (development, 1.2) or from another build**, AppKata only notifies: the
update shows as usual, and **Update** opens the project's releases page instead of installing.

R2.11.5. **Installed with its Windows setup** (15.10), AppKata adopts its installation on first
start, from its own Uninstall registry entry. It downloads and verifies the new
`AppKata-<version>-setup.exe` like any update, then shows the same **Restart AppKata** button.
Restarting runs the setup silently, for the same scope (15.4), and starts the new version when it
finishes.

R2.11.6. **Track only** (2.6.1) on AppKata's own Source turns this off on every platform: AppKata
then only notifies, as in 2.11.4.
