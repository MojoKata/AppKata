# R10. Trust and the AppKata.md file

R10.1. **The Trust table.** The load-bearing content of an `AppKata.md` file is the first
GitHub-flavoured Markdown table whose header row is `App | Source | Tags | Trust | Rating`.
Header matching ignores case and surrounding spaces. A title and introduction may come before
the table.

R10.1.1. **App**: the name of the application. Names must be unique within a file.

R10.1.2. **Source**: the git URL for the app. Rows are matched to Sources by normalized URL
(R2.3).

R10.1.3. **Tags**: a comma-separated list of tags (R10.4).

R10.1.4. **Trust**: how trustworthy the reviewer considers the app.

- `0`–`5`, or `⭐`, `★` or `☆` repeated up to 5 times. `☆` counts as empty.
- **0** tells the reviewer's audience to avoid the app (R10.6.1).
- An empty cell means no opinion.

R10.1.5. **Rating**: the reviewer's subjective rating, `0`–`5` stars, written the same way as
Trust. 0 is just a low rating. An empty cell means no opinion.

R10.2. **Parse warnings.** Invalid rows are skipped and reported as parse warnings on the
Trust (R7.6.3, R7.6.5). This includes:

- A duplicate App name.
- A bad tag.
- A Trust or Rating value that isn't 0–5.
- A version review without a version (`## <App>[]`), or two for the same version.
- A `::Details` or `::Settings` sub-section whose heading names no review in the section.
- A platform on a Trust, Rating or Tags line.
- The newest review's Trust, Rating or Tags differing from the table row (R10.3.3).

R10.3. **Review sections.** Below the table, each `# <App>` heading starts that app's section. The
heading text must exactly match the App column. A row without a section is valid. A section
without a row is ignored, with a parse warning.

A section holds the review of the app as a whole and, optionally, reviews of particular versions
(R10.3.2). Only these headings have a meaning; any other heading is part of the review text around
it:

| Heading | Holds |
|---|---|
| `# <App>` | The **app review**: text about the app, for no particular version |
| `## <App>::Settings` | The app review's settings (R10.3.1) |
| `## <App>[<version>]` | A **version review**: text about that version (10.3.2) |
| `### <App>[<version>]::Details` | What the reviewer had installed when writing it (R10.3.4) |
| `### <App>[<version>]::Settings` | What changes from that version on (R10.3.3) |

The file is already `AppKata.md`, so the headings don't repeat "AppKata". A reviewer writes the app
review first, then its settings, then version reviews oldest first; AppKata writes them in that
order, but reading them doesn't depend on it.

```
| App | Source | Tags | Trust | Rating |
|---|---|---|---|---|
| Zettlr | https://github.com/Zettlr/Zettlr | foss, donation, portable, signed | 5 | 4 |

# Zettlr

A Markdown editor for long-form writing, with citations.

## Zettlr::Settings

- Trust: 4
- Rating: 4
- Tags: foss, donation, portable
- Download filter (linux): `x86_64\.AppImage$`
- Auto update (linux): no
- Auto update (windows): yes

## Zettlr[3.5.1]

Release files are now signed, and the Linux AppImage updates itself.

### Zettlr[3.5.1]::Details

- Date: 2026-09-14
- Platform: linux x86_64
- Channel: GitHub release
- File: Zettlr-3.5.1-x86_64.AppImage
- SHA-256: 3c1f…9e07

### Zettlr[3.5.1]::Settings

- Trust: 5
- Tags: foss, donation, portable, signed
- Auto update (linux): yes
```

Here Zettlr 3.5.1 and later have Trust 5, Rating 4 (carried forward) and update themselves on
Linux too; versions before 3.5.1 have Trust 4.

R10.3.1. **Settings.** A `## <App>::Settings` sub-section (and a version's `### <App>[<version>]::Settings`)
is a list of `- <Option>: <value>` lines: the review's Trust, Rating and Tags (R10.3.3), the app's
recommended install options, the Source settings that describe the app (forge and download filter,
R2.6), and its package channels (R16.1.3). Track only and Include pre-releases are personal
preferences, so they aren't part of it. A line may name a platform, `- <Option> (<platform>): <value>`,
which overrides the line without one on that platform.

| Option | Value | Meaning |
|---|---|---|
| Trust | 0–5, as in the table | The review's Trust (R10.3.3) |
| Rating | 0–5, as in the table | The review's Rating |
| Tags | comma-separated tags | The review's tags, as a whole list |
| App menu | yes / no | Add a launcher (R4.3.1.1) |
| Command link | yes / no | A command in the command links folder (R4.3.1.3) |
| Stable name link | yes / no | The stable-name link (R4.3.1.2) |
| Forge | `github`, `github enterprise`, `gitlab`, `forgejo` (or `codeberg`), `gitea` | The forge type override (R2.6.5) |
| Download filter | a regex, in backticks | The download filter (R2.6.4) |
| Auto update | yes / no (`Auto updates` is read too) | The app updates itself (R4.10) |
| Flatpak | an app ID, optionally after a remote: `org.zettlr.Zettlr`, `flathub org.zettlr.Zettlr` | The app's Flatpak (R16.1.3); the remote defaults to `flathub` |
| Debian package | a package name | The app's package on Debian, Ubuntu and Mint (R16.1.3) |
| Fedora package | a package name | The app's package on Fedora, RHEL, AlmaLinux and Rocky Linux (R16.1.3) |
| Channel | `release`, `flatpak` or `package` | The way to install the app the reviewer recommends (R16.3.2) |
| Sandbox | a template name (`standard`, `offline-editor`, `online-app`, `messenger`, `media-player`, `developer`, `cli-tool`, `strict`) or `off` | The suggested sandbox template (R17.3) |
| Sandbox folders | paths, comma-separated; `+`/`-` prefixes add to / remove from the template's set; `:ro` marks read-only | Folder grants (R17.2, R17.3) |
| Sandbox network | yes / no | Whether the app may use the network (R17.2) |
| Sandbox sound | `play`, `record`, comma-separated; `+`/`-` prefixes add to / remove from the template's | Sound (R17.8) |
| Sandbox devices | `camera`, `x11`, the same way | Devices (R17.2.1, R17.9) |
| Sandbox services | `notifications`, `keep-awake`, `tray`, `media-keys`, `passwords`, `password-service`, the same way | Desktop-services capabilities (R17.5.1); a review can't grant the last two (R17.3.1) |
| Sandbox app folder | yes / no | The writable app folder (R17.7.1) |

Trust, Rating and Tags take no platform; a platform on them is ignored, with a parse warning.
The `Sandbox*` lines are Linux-only; on other platforms they're ignored.

- A **Download filter** is written in backticks so Markdown leaves its `\`, `*` and `_` alone. A
  value that isn't a valid regex, or an unknown forge, is ignored.
- **Recommended Source settings** apply to an app on this platform unless you set your own in
  Source settings (R2.6.7), with the same Trust order as the other options (R4.3.1.6): yours, then
  the highest Score, then name. They also apply to apps that only Trusts list. A recommended
  Download filter that matches no file here is ignored; your own isn't.
- **Platforms** are `linux`, and `win` or `windows`, without case; a line may also name `mac` or
  `macos`. Such a line never applies on Linux or Windows, but AppKata keeps it: rewriting the file
  writes it back, as `macos`, with the other platforms' lines. AppKata writes `linux`, `windows` and
  `macos`.
- **Which line applies:** within one Settings sub-section, the line for this platform if there is
  one, else the line without a platform. Across reviews, see R10.3.3. With no line at all,
  AppKata's own default applies (Settings, R11.1).
- Unknown options and unknown platforms are ignored.
- **The review dialog** (R8.4.7) writes this computer's options: App menu, Command link, Stable
  name link and Forge as lines without a platform, and **Auto update** (when you chose it) and the
  **Download filter** (this platform's, from Source settings) as this platform's lines, e.g.
  `- Download filter (linux): \`x86_64\.AppImage$\``, since their right value depends on the
  platform. It keeps the file's other lines, and drops this platform's lines for the options it
  writes without a platform, so the new values apply here too.

Options are matched without case; unknown ones are ignored. For people who trust the file, the
install options are a recommendation: they become the starting values when they install that app
(R4.3.1.6), and the install dialog says who recommended them ("Options recommended by mara-dev /
foss-picks"). Settings sub-sections aren't part of the review text shown in the App Detail panel.

R10.3.2. **Version reviews.** A `## <App>[<version>]` sub-section says "I reviewed this version". It
holds for that version and every later one, until a later version review says otherwise.

- The version is the project's own version, as its releases name it (`1.2.3`), without a leading
  `v`. A package's version (`1.2.3-4`, `1:1.2.3-1ubuntu2`) isn't used; the Details say which
  package it was (R10.3.4), and package versions are mapped to the project's version (16.7).
- The text is optional. A heading with only a Settings sub-section changes the verdict from that
  version on, for example to warn against a release the reviewer never installed:
  `## xz[5.6.0]` with `- Trust: 0`, then `## xz[5.6.2]` with `- Trust: 4`.
- There are no version ranges: a sequence of version reviews describes them.

R10.3.3. **Values over versions.** Each review (the app review, then the version reviews in version
order) has a Trust, Rating, Tags and options:

1. A review's value for an option is its own line, after resolving its platform lines (R10.3.1),
   else the value carried from the review before it. A version review sets only what changes.
2. The app review's own lines are those in `## <App>::Settings`. When it has no Trust, Rating or
   Tags line, it takes them from the earliest version review that has one, else from the table
   row.
3. **The table row is the newest review's Trust, Rating and Tags.** If the newest review's Settings
   give different values, the table row wins, with a parse warning: what people read in the table
   is what AppKata uses for the newest versions.
4. AppKata, when it writes a review (8.5), always writes Trust, Rating and Tags into that
   review's Settings and updates the table row when it's the newest, so the fallbacks in 2 matter
   only for hand-written files.

R10.3.4. **Details.** A `### <App>[<version>]::Details` sub-section is a list of facts about what the
reviewer had installed. Every line is optional; unknown lines are kept and shown as written.

| Line | Example |
|---|---|
| Date | `2026-09-14`, the day the review was written |
| Platform | `linux x86_64`, `windows x64` |
| Channel | `GitHub release`, `Flathub org.zettlr.Zettlr (verified)`, `Debian package 3.5.1-1`, `Fedora package 3.5.1-2.fc41` |
| File | The release file installed |
| SHA-256 | Its digest |
| Commit | The Flatpak commit installed |

Details never change scores. When the reviewer's SHA-256 or Flatpak commit equals the one about to
be installed, or the one installed, the App Detail panel says "Same file as <Trust> reviewed".

R10.3.5. **Which review applies to a version.** For a version *v*, a Trust's review is its newest
version review whose version is *v* or older, else its app review. Versions are compared as in R9.4;
a version that isn't semver-like is placed by its release's date when the release is known, and
otherwise matches only a version review of exactly that version. An installed version that can't be
placed gets the newest review.

R10.4. **Tags** describe characteristics of the app that the reviewer wants to surface.

R10.4.1. A tag starts with a letter, followed by letters and digits. Tags are case-insensitive
and are stored and shown in lowercase.

R10.4.2. Predefined tags:

| Tag | Meaning |
|---|---|
| `foss` | Free and open source |
| `donation` | The author accepts donations |
| `freemium` | Free, with paid features |
| `saas` | An account is required to use the app |
| `spyware` | Collects data about the user without consent |
| `malware` | Harmful or malicious |
| `ads` | Shows advertising |
| `tracking` | Telemetry or analytics, including opt-out ones |
| `nonfreenet` | Relies on a non-free network service |
| `nonfreedep` | Depends on non-free libraries or components |
| `nonfreeassets` | Artwork, sound or data under a non-free license |
| `upstreamnonfree` | The upstream source contains non-free parts that are stripped out |
| `knownvuln` | Has a known, unfixed security vulnerability |
| `unmaintained` | No upstream activity for a long time |
| `archived` | The upstream repository is archived or read-only |
| `nsfw` | Adult content |
| `reproducible` | Reproducible builds have been verified |
| `signed` | Release binaries are signed or have checksums |
| `offline` | Works fully without a network |
| `portable` | Runs without installation |

R10.4.3. **Warning tags** are `spyware`, `malware`, `ads`, `tracking` and `knownvuln`. They are
shown in the warning colour wherever tags appear.

R10.5. **The Catalog's apps.** The Catalog lists every Source, plus every app listed in the
`AppKata.md` of an enabled Trust whose latest change is verified (R10.7). An app that is a
Source and is also listed by Trusts, or is listed by several Trusts, appears once, with all its
origins (R2.9).

R10.5.1. The user's own `AppKata.md` (R8.1) is always treated as an enabled Trust. Its rows
count toward R10.6, without signature checks.

R10.5.2. Trusts are added only by the user. There is no default or starter Trust, and AppKata
works with Sources alone and no Trusts.

R10.6. **Combined score** for an app, across the enabled Trusts that list it:

R10.6.1. **Veto.** If any enabled Trust gives the app a Trust of 0, the app is **vetoed**.

R10.6.2. Otherwise, its Trust is the average of the Trust values given, and its Rating is the
average of the Rating values given, both weighted by each Trust's Score (R7.6.8): a 5-star
Trust's review counts five times as much as a 1-star Trust's. Score doesn't affect the veto. Both are shown to one decimal place, with the number of
reviewers.

R10.6.3. An app that no Trust reviews is **Unreviewed**. It has no score, and it is not
vetoed.

R10.6.4. **AppKata itself** (R2.11) always has a combined Trust of 5: you're running it. Its Trusts'
Trust values, including a 0, don't change that; its Rating is combined as usual.

R10.6.5. **Scores for a version.** Each Trust's Trust, Rating and tags are those of its review for a
version (10.3.5), and are combined as above for that version:

- **Catalog** tiles and the App Detail panel of an app that isn't installed: the latest release,
  the one **Install** would install. Vetoed apps (R12.6) are those vetoed for it.
- **Apps** rows and the App Detail panel of an installed app: the installed version. When it's
  vetoed, the row has a red **Avoid** pill and the panel a red banner, "A trusted reviewer says to
  avoid the version you have (5.6.1)", with the reviewer, the version their review starts at, and
  **Update to 5.6.2** when a newer release isn't vetoed. A sync that newly vetoes an installed
  version shows a system notification, "A trusted reviewer says to avoid xz 5.6.1".
- An **update** to a vetoed version shows "Avoid" next to it and is left out of **Update all**.
- The **Versions** list (R5.7.5.1): each version's combined Trust, and avoided versions dimmed.
- Each review row in the App Detail panel (R5.7.6) says which version the review is of ("reviewed
  2.0.1"), and its earlier reviews are under a collapsed "Earlier reviews (2)".

R10.7. **Signed changes.** Every commit that changed `AppKata.md` since the last verified
commit must be signed by an enabled Authority of the Trust. Accepted signature types:

- **GPG**, verified against the Authority's public key.
- **SSH**, verified with an `allowed_signers` file that AppKata builds from the Authorities.
- **Nostr**, for ngit Trusts, where the repository state event is signed by a maintainer's
  npub.

X.509 is not supported. Signatures are verified locally; the forge's "Verified" badge is not
used. SSH signatures are checked by AppKata itself (Ed25519, RSA, ECDSA P-256), because
`ssh-keygen -Y` needs OpenSSH 8.2+ and some supported systems ship older ones.

R10.7.1. When a Trust is added (R7.6.2), the commit that last changed `AppKata.md` must be
signed. Its signing keys become the first Authorities, trusted on first use after the user
confirms them.

R10.7.2. **Rewritten history.** If the last verified commit is no longer an ancestor of the
branch, for example after a force-push, the change is treated as unsigned.

R10.8. **Unsigned changes and unknown signers.**

- A change that is unsigned, or signed by a disabled or removed Authority, is **not applied**.
  AppKata keeps using the last verified version, and the Trust row shows a warning.
- A change signed by a key that isn't an Authority is also not applied. The key appears in
  the Trust Detail panel as a pending new signer (R7.6.6). Choosing **Trust signer** adds it as
  an Authority and applies the change.
- Disabling an Authority doesn't affect commits verified before it was disabled.

R10.9. **Authority identities.**

- **Nostr keys**: the kind-0 profile gives the name, avatar and NIP-05.
- **GPG and SSH keys**: the key's user ID or the commit author gives the name and email; the
  avatar comes from the forge account that owns the key where the forge exposes it, otherwise
  an identicon generated from the fingerprint.
