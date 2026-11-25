# R16. Package channels (Linux)

AppKata should be one place to find, install and review apps, and still get along with the
distribution's own updates and app stores (GNOME Software, KDE Discover, Mint's Software Manager).
This section adds Flatpak remotes and the distribution's repositories as ways to install an app.
Containers test it (`scripts/test-channels.sh`). Installing an older Flatpak commit from the Versions
list (R16.5.7) is a gap, [G#57](https://github.com/MojoKata/AppKata/issues/57), and so is checking three facts on real systems,
[G#58](https://github.com/MojoKata/AppKata/issues/58).

R16.1. **Channels.**

R16.1.1. An app is still its git project URL (R2.1); what Trusts review doesn't change. A **channel**
is a way to install it:

| Channel | Identified by | Built by | Signed by |
|---|---|---|---|
| **Release** (R2.4, R4.2) | A file in the project's release | The project | The project, sometimes (R4.4) |
| **Flatpak** | A remote (`flathub`) and an app ID | Flathub's build servers, from a manifest kept by the project (verified) or by someone else | The remote's key |
| **Package** | A package name in the distribution's repositories: apt on Debian, Ubuntu and Mint; dnf on Fedora, RHEL, AlmaLinux and Rocky Linux | The distribution's packagers, often with patches | The distribution's keys |

An app may have all three. Channels exist on Linux only.

R16.1.2. A channel that comes from a repository AppKata didn't add (a PPA, a vendor's apt
repository, a Flatpak remote other than Flathub) is shown with that repository's name. AppKata
never adds repositories itself, except Flathub (R16.3.4).

R16.1.3. **Linking a channel to an app.** The first that applies:

1. The user's own link, set in Source settings (R2.6.7: **Flatpak** and **Package** fields) or
   when adding a Source from Explore (R16.2.4).
2. A Trust's `Flatpak`, `Debian package` or `Fedora package` line (R10.3.1), with your own
   `AppKata.md` first, then the highest Score, then name. `Debian package` is used on Debian,
   Ubuntu and Mint; `Fedora package` on Fedora, RHEL, AlmaLinux and Rocky Linux.
3. **AppStream** (R16.2.2): a component whose `vcs-browser`, `homepage` or `bugtracker` URL is a
   forge project URL that normalizes (R2.3) to the app's, or whose ID equals the `<id>` in the
   project's own metainfo (R3.2).

A name match alone never links a channel (it can still find a foreign install, R4.5).

R16.1.4. **Checking a link.** AppKata checks every link it uses against what it can fetch:

| Channel | Checked against |
|---|---|
| Flatpak (Flathub) | The ID in the project's own metainfo; Flathub's **verified** flag (the project proved it owns the ID); the build manifest in `github.com/flathub/<id>`, whose sources should include the app's git URL |
| Debian package | The AppStream URLs; `Repository` in the package's `debian/upstream/metadata` |
| Fedora package | The AppStream URLs; `URL` and `Source0` in the package's spec on `src.fedoraproject.org` |

The result shows on the channel (R16.3.1, R16.6.1): **Matches the project**, **Unchecked** (nothing
to check against), or, in the warning colour, "<Trust> links org.example.App, but its build comes
from github.com/someone/fork". A channel that fails its check is never **Recommended**; it can
still be installed.

R16.1.5. **When the checks run.** Each check runs when its answer can change:

- **Flathub's verified flag:** every sync (R9.2), as a conditional request (`If-None-Match`), so an
  unchanged answer costs almost nothing. Losing verification shows at the next sync.
- **The build manifest:** only when the Flatpak's newest commit on the remote changes, that is,
  when Flathub publishes a new build; between builds the manifest that made it can't change. It is
  read as a raw file (`raw.githubusercontent.com`), not through GitHub's API, so it doesn't use up
  the API's rate limit (R2.4.1).
- **Distribution packaging metadata:** when the package's version in the repositories changes.

R16.2. **Finding apps.**

R16.2.1. Channels don't add apps to the Catalog (R10.5): the Catalog is still the Sources and the
Trusts' apps. An app in the Catalog shows the channels it has (R16.6.1).

R16.2.2. **AppStream catalog.** The distribution publishes AppStream data for its repositories.
AppKata reads it directly; `appstreamcli` isn't needed.

| Distribution | Where | Refreshed by |
|---|---|---|
| Debian, Ubuntu, Mint | `/var/lib/apt/lists/*_dep11_Components-<arch>.yml.gz`, and the icon tarballs next to it | `apt update` |
| Fedora, RHEL, AlmaLinux, Rocky Linux | `/usr/share/swcatalog/xml/` (older releases: `/usr/share/app-info/xmls/`) | Updates to the `appstream-data` package |

Only components that are apps are used: type `desktop-application` or `console-application`.
Left out:

- Every other type (`runtime`, `font`, `codec`, `inputmethod`, `firmware`, `driver`,
  `localization`, `addon`, `service`, `operating-system`).
- Parts of the desktop: components with `<compulsory_for_desktop>`.
- Ubuntu's transitional packages that install a Snap (`firefox`, `chromium-browser`,
  `thunderbird` on releases where they do): a package that depends on `snapd` and whose
  description says it's transitional.

Without a catalog (servers, minimal installs), the distribution's Explore item is disabled, with
the tooltip "No AppStream catalog on this computer".

R16.2.3. **Explore** (R7.7) gains two items after **ngit**: **Flathub** (Flathub's public search API)
and the distribution, named for it (**Ubuntu**, **Fedora**…; the local AppStream catalog, R16.2.2,
offline). A match shows its app ID or package name, summary, Flathub's **Verified** chip, and the
project URL found (R16.1.3), such as "github.com/laurent22/joplin".

R16.2.4. **Adding one as a Source.** An app is still a git project, so **Add source** needs the
project URL: it opens Add source (R7.2) with that URL and the channel link filled in. When no
project URL was found, the button is disabled ("No project link found") and **Enter git URL…**
opens Add source with only the channel link; the user types the project URL, and AppKata checks
the link against it (R16.1.4) before saving.

R16.3. **Installing.**

R16.3.1. **Channel cards.** The install dialog (R4.9) has one card per way to install the app here:
the release files (R4.2.1), then each linked channel. A channel card shows:

- **Flatpak**: "Flathub · <app ID>", a **Verified** or **Community** chip (R16.6.1), "Built by
  Flathub from <tag>" when its manifest says so, "Sandboxed · for you only; no admin password",
  and its download size.
- **Package**: "<Distribution> package · <name> <version>" and its repository ("universe"),
  "Installed for all users with apt (or dnf); needs your admin password", how far it is behind the
  project ("4 releases behind", R16.7.2), and its size.
- For either: who will update it (R16.5): "Ubuntu updates it automatically" or "Not updated
  automatically", and the result of the link check (R16.1.4).

R16.3.2. **Which card is Recommended.** A Trust's `Channel` line (R10.3.1; your own first, then
Score), "Recommended by <Trust>". Otherwise, in this order: a verified Flatpak, the release files
in the order of R4.2, a community Flatpak, the distribution's package. A channel that failed its
link check (R16.1.4) comes last.

R16.3.3. **When the dialog asks.** As in R4.9.1, when there is more than one card. The answer (the
channel, or the kind of file) is saved with the app (R4.9.3) and used for updates. Apps with only a
channel and no release files still open the dialog to show what will happen.

R16.3.4. **Installing a Flatpak.** Per user, with no elevation:

1. When the Flathub remote isn't configured for the user, AppKata asks once, "Add Flathub?", and
   runs `flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`.
2. `flatpak install --user --noninteractive flathub <app ID>`, with its progress shown as in R4.8.
3. The record (R4.1) holds the remote, the ref and the commit.

R16.3.5. **Installing a package.** Through the package backend (R16.8):

1. A dry run first gives the plan. A plan that only adds the package and its new dependencies
   installs straight away; the dialog's card already said how much it downloads.
2. A plan that removes or downgrades anything, or upgrades packages other than new dependencies,
   is shown in a confirmation listing those packages; **Install** is red and the default is
   **Cancel**. A plan that removes a package marked essential or protected, or a metapackage of
   the desktop (`ubuntu-desktop`, `task-gnome-desktop`, `@workstation-product`…), is refused.
3. The record holds the package name, the manager, the repository, and whether the package was
   already marked as a dependency (R16.4.3).

R16.3.6. **Verification** (R4.4). flatpak checks a Flatpak's commits against its remote's key, and
apt and dnf check packages against their repositories' keys. AppKata shows **Verified** only for
a copy that was checked so, with the tooltip "Signed by Flathub" or "Signed by Ubuntu" (the
remote's or the repository's own name, as R16.1.2 shows it; "Signed by its repository" when it
gives none):

- A Flatpak, when signature checking is on for the remote it came from. A remote added with
  `--no-gpg-verify`, and the one a bundle installed from a file leaves behind, have it off.
- A package, when a repository whose key the package manager checks offers the installed version.
  A version no repository offers (one installed from a file, or one its repository has since
  replaced) and a package of a repository that is trusted without a key (`[trusted=yes]`) were
  checked against nothing AppKata can tell.

Every other copy shows **Unverified**, with where it is from in the tooltip, and its channel is
named **Package** where no repository's name is known (R16.6.1). AppKata asks flatpak and the
package manager each time it installs, adopts (R16.4.2) or updates the copy; the chip is their
answer, kept in the install record (R4.1).

R16.4. **Tracking.**

R16.4.1. **Still installed?** Each sync checks every channel install (`flatpak info`, `dpkg-query`,
`rpm -q`). One removed outside AppKata leaves the Apps view, and the Audit records "Removed outside
AppKata" (R13; actor **System**).

R16.4.2. **Adopting.** A foreign install (R4.5) that a channel link (R16.1.3) matches exactly (the
Flatpak app ID, or the package name) is adoptable: the disabled **Installed outside AppKata**
button (R4.5.3) becomes **Adopt**, with the tooltip "Track this copy with AppKata, without
reinstalling". Adopting records it as if AppKata had installed it, adds it to the Apps view, and
is recorded in the Audit. A Flatpak installed for all users (`--system`) can be adopted too; changing
it then needs the administrator password, which flatpak asks for itself. Matches by name only stay
foreign.

R16.4.3. **Uninstalling** (R4.7):

- **Flatpak:** `flatpak uninstall --user --noninteractive <app ID>`. The app's data in
  `~/.var/app/<app ID>` is kept, like other user data.
- **Package:** a dry run first. When it would remove anything but the package itself, the
  confirmation lists what else goes and the user must confirm; the refusals of R16.3.5 apply. This
  applies to `.deb` and `.rpm` files installed from releases (R4.3.3) too. Packages left unneeded are
  not removed (no autoremove); that is the system's business. A package that was installed as a
  dependency of something else, or that other installed packages need, can't be uninstalled from
  AppKata: the button is disabled with "Other software on this computer needs it".

R16.5. **Updates.**

R16.5.1. **Who updates it.** Each channel install is in one of three states, shown as a chip on its
Apps row and in the App Detail panel:

| State | When | AppKata |
|---|---|---|
| **Updated by the system** | The system updates it automatically (R16.5.2) | Shows new versions ("1.20.0 is out") but has no Update button; **Update all** skips it, as for an app that updates itself (R4.10) |
| **Not updated automatically**, in the warning colour | Nothing updates it automatically | Offers its updates like any other app |
| **AppKata updates it** | The user chose so in Install options (R16.5.3) | Offers its updates like any other app |

R16.5.2. **Detecting automatic updates.** AppKata reads the settings of the updaters it knows:

| Updater | Updates | Checked |
|---|---|---|
| unattended-upgrades (Debian, Ubuntu, Mint) | Packages from its allowed origins: by default **security updates only** | `APT::Periodic::Unattended-Upgrade` from `apt-config dump`, the `apt-daily-upgrade.timer`, and whether the package's repository is among `Unattended-Upgrade::Allowed-Origins` / `Origins-Pattern` |
| dnf-automatic (Fedora, RHEL family) | Packages | Its timer is enabled and `apply_updates = yes` (and `upgrade_type`) in its configuration |
| GNOME Software | Flatpaks automatically; packages only download and wait for **Restart & Update** | `org.gnome.software` `download-updates` |
| KDE Discover | Flatpaks and packages, when unattended updates are on | Its unattended-updates setting |
| Mint's Update Manager | Packages and Flatpaks, when its automation is on | Its automation timers and settings |

An updater AppKata doesn't know (a cron job, Ansible) isn't detected; R16.5.4 catches its updates
afterwards. Only security updates being automatic counts as **Not updated automatically**,
since app releases don't arrive that way.

R16.5.3. **Choosing.** By default AppKata goes with what it detects, to stay out of the system's
way. **Install options…** (R4.9.5) has **Updates**: **Let the system update it** or **AppKata
updates it**. Choosing AppKata while the system also updates it says so ("GNOME Software also
updates this app automatically; AppKata can't turn that off"): like an app's own updater (R4.10.3),
AppKata can step back but can't stop another updater.

R16.5.4. **Updates made elsewhere.** When a sync finds a channel install at a version AppKata didn't
install, it records it in the Audit (actor **System**) and, where the history says who, the App
Detail panel shows "Updated by GNOME Software on 3 Oct". The history comes from
`/var/log/apt/history.log` and `/var/log/unattended-upgrades/`, `dnf history`, and
`flatpak history`. A change made by an automatic updater to an app marked **Not updated automatically**
moves it to **Updated by the system**; a change made by a person (`apt`, `dnf` or `flatpak` run by
hand) doesn't.

R16.5.5. **Finding and installing updates.**

| Channel | New versions | Update |
|---|---|---|
| Flatpak | `flatpak remote-ls --updates --user` | `flatpak update --user --noninteractive <app ID>` |
| apt | The repositories' lists as they are (`apt list --upgradable`); refreshed when AppKata updates something, through the backend | `apt-get install --only-upgrade <package>`, after a dry run (R16.3.5) |
| dnf | `dnf check-update <package>`, which needs no administrator rights | `dnf upgrade <package>`, after a dry run |

R16.5.6. **Pinning** (R9.5). A Flatpak is pinned with `flatpak mask --user <app ID>`, which also stops
GNOME Software and Discover from updating it; unpinning removes the mask. Packages can't be pinned
from AppKata (it would take `apt-mark hold` or `dnf versionlock`, which change the whole system):
**Pin** is disabled with that explanation. A package already held that way shows **Held by the
system** and gets no Update button.

R16.5.7. **Versions and minimum age.** For a Flatpak, the Versions list (R5.7.5.1) comes from
`flatpak remote-info --log`, an older version installs with `flatpak update --commit=<commit>` and
pins it, and minimum age (R9.5.2) uses the commit's date. For a package, the list shows only what
the repositories offer, older versions can't be installed, and minimum age doesn't apply: the
distribution already decides when a version is ready.

R16.6. **Publisher and permissions.**

R16.6.1. The App Detail panel shows each channel the app has, with who publishes it:

- **Flathub · verified**: published by the project itself.
- **Flathub · community**: packaged by someone else.
- **Ubuntu (universe)**, **Fedora**, or the repository's name (R16.1.2).
- The link check (R16.1.4).

These describe the channel, not the app: they never change the app's Trust or Rating (R10.6).

R16.6.2. A Flatpak whose program is downloaded from elsewhere at install time (an extra-data
Flatpak, which wraps someone else's binary) has a chip "Downloads its program from <host>".

R16.6.3. **Flatpak permissions** come from the app's metadata (`flatpak remote-info --show-metadata`,
its `finish-args`) and are shown in plain words: Network, Home folder, Whole file system, Devices,
Display (X11), and named session services. An update that asks for more than the installed version
shows "Asks for more: Home folder" on its row in the warning colour; **Update all** skips it, and
updating it asks first. A reviewer's Trust was given for what the app could do before.

R16.7. **Versions across channels.**

R16.7.1. A channel's version is mapped to the project's version, to choose the review (10.3.5) and to
compare with the releases:

- **Flatpak:** the version of the newest `<release>` in the installed commit's metainfo, as
  `flatpak info` shows it.
- **Debian package:** without the epoch (`1:`), the Debian revision (from the last `-`), and
  repack suffixes (`+dfsg…`, `+ds…`, `~…`).
- **rpm:** its `%{VERSION}`.

R16.7.2. The App Detail panel shows both when they differ: "Ubuntu 1.14.0-1 · project 1.18.2 (4
releases behind)", counting the project's releases newer than the mapped version.

R16.8. **The package backend.** apt and dnf are driven in two ways; reading never needs
administrator rights.

R16.8.1. **PackageKit**, when its service is running (as it is on desktop installs of Ubuntu,
Debian, Fedora, Mint and the RHEL family). AppKata talks to it over the system D-Bus with a small
D-Bus client of its own, in pure Python, so no new dependency. (PySide6's QtDBus can't send the
unsigned 64-bit flags PackageKit's methods take.) PackageKit is what GNOME Software and Discover use, so:

- Installs queue behind theirs rather than fighting over the package manager's lock.
- polkit asks for the administrator password and keeps it for a few minutes, so **Update all**
  asks once.
- Progress, cancelling and dry runs (the *simulate* flag) come from PackageKit.

R16.8.2. **The command line**, when PackageKit isn't running (servers, minimal installs), through
`pkexec` (R1.3):

- **apt:** `apt-get` with `DEBIAN_FRONTEND=noninteractive`,
  `-o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold` (keep the user's
  configuration files), and `-o APT::Status-Fd` for progress; dry runs with `apt-get -s`, which
  needs no administrator rights.
- **dnf:** `dnf -y`; dry runs with `--assumeno`.
- `pkexec` asks for the password once per action.

R16.8.3. **Busy package manager.** When another program holds the package manager's lock
(unattended-upgrades, a store), the install waits as "Waiting for unattended-upgrades" (the lock
holder's name) for up to 10 minutes, then fails with that reason. **Cancel** works while waiting.

R16.8.4. Reading uses the command line and files: `dpkg-query`, `rpm -q`, `apt list`,
`dnf check-update` and `dnf repoquery`, the AppStream catalog (R16.2.2), and `flatpak` (which never
needs administrator rights for `--user`).

R16.9. **The Audit** (R13) records channel installs, adoptions (R16.4.2), uninstalls, updates, the
**Updates** choice, and what changed outside AppKata (R16.4.1, R16.5.4), with the actor **System**.

R16.10. **Inside a sandbox.** There is no Flatpak of AppKata (R1.6). If AppKata is nonetheless run inside
a Flatpak sandbox (`/.flatpak-info` exists), it can't see the host's packages or Flatpaks, so
channels are off and their Explore items and channel cards are hidden.

R16.11. **Not supported:** openSUSE (zypper), installing Snaps (Snaps are still found as foreign
installs, R4.5), adding vendor repositories, browsing every package of the distribution, and reviews
of a distribution's own revision of a version (10.3.2 reviews the project's versions).
