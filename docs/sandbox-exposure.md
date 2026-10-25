# What a sandboxed app can see

Everything of the host a sandboxed app can see: each mount, environment variable, device, socket,
identifier and network reach a generated launcher gives it, when, and which sentence of the
requirements says so. Review 3 built this as harness 3, the exposure inventory. Review 2's F18
showed the class: the launcher binds `/sys` (MAC addresses, USB serials) and nothing written said
so. Every earlier test asked whether one thing the tester thought of was hidden. None listed what
is in view.

`tests/test_sandbox_exposure.py` keeps this table true from both sides:

- **Tier 1, everywhere.** It runs each template's launcher with a stand-in `bwrap` that records its
  words, and compares the mounts, variables and devices those words give with the rows here.
- **Tier 2, real bwrap.** In the `launcher` harnesses (Mint 22.1, 21.3, Ubuntu 25.04, and the
  24.04 and 26.04 VMs), `scripts/sandbox/exposure.py` runs inside each template's launcher. It
  lists what is actually in view: the mount table, the environment, `/dev`, sockets, the machine's
  identifiers, the network interfaces and abstract sockets, and other processes. It then compares
  that with the rows that apply to the run.

Either fails on:

- something seen that no row lists, or that a row lists for other conditions;
- a row whose conditions hold, on a host that has the thing, but which isn't seen;
- a "Stated in" whose phrase isn't in that requirement;
- open findings that differ from the test's list.

The field test (`scripts/sandbox/field-test.sh`) runs the same probe on a real desktop and reports
anything unlisted.

**When** is a set of condition words joined by "and":

- `always`;
- `bus`: Standard, which gets the filtered bus;
- `network`, `sound`, `camera`, `folder-ro` and `folder-rw`: the grant;
- `cli`: a CLI tool run from a folder it may share, 17.3.3;
- `write_app`;
- `appimage`;
- `wayland`: a Wayland session;
- `x11`: the X server's socket is given. That is an X11 session, or a Wayland session with the X11
  grant.

A row is expected only where the host has the thing: a `-try` bind's source, a variable set at
launch, a GPU, an identifier.

**Stated in** is either a requirement and a phrase from it, `no host data` (something private to
the sandbox), or `open:` and the finding that keeps it unstated.

## The inventory

| Seen inside | When | Stated in |
|---|---|---|
| `mount / tmpfs`, `mount /tmp tmpfs`, `mount /dev tmpfs` | always | no host data |
| `dev /dev/null`, `dev /dev/zero`, `dev /dev/full`, `dev /dev/random`, `dev /dev/urandom`, `dev /dev/pts/ptmx` | always | no host data |
| `mount /proc proc` | always | 17.4 "uses --unshare-all" |
| `mount /usr ro`, `mount /etc ro` | always | 17.4 "binds /usr and /etc read-only" |
| `mount /usr/share/applications tmpfs`, `mount /usr/local/share/applications tmpfs` | always | 17.4 "hidden under an empty tmpfs" |
| `mount ~ rw` | always | 17.4 "mounts a private home" |
| `mount $appdir ro` | not write_app | 17.4 "binds the app's current version folder read-only" |
| `mount $appdir rw` | write_app | 17.7.1 "binds the version folder read-write" |
| `mount ~/.themes ro`, `mount ~/.icons ro`, `mount ~/.fonts ro`, `mount ~/.config/fontconfig ro`, `mount ~/.local/share/fonts ro`, `mount ~/.local/share/icons ro`, `mount ~/.local/share/themes ro` | always | 17.4 "so apps look native" |
| `mount /.flatpak-info ro` | always | 17.6 "bound read-only at /.flatpak-info" |
| `mount /run/appkata ro` | always | 17.4 "its xdg-open is AppKata's" |
| `env HOME`, `env PATH`, `env XDG_RUNTIME_DIR` | always | 17.4 "clears the environment to an allow-list" |
| `env LANG`, `env LANGUAGE`, `env LC_ALL`, `env LC_CTYPE`, `env LC_MESSAGES`, `env LC_NUMERIC`, `env LC_TIME`, `env TERM`, `env USER`, `env LOGNAME`, `env XDG_SESSION_TYPE`, `env XDG_CURRENT_DESKTOP`, `env DESKTOP_SESSION`, `env GTK_THEME`, `env QT_QPA_PLATFORMTHEME`, `env QT_STYLE_OVERRIDE`, `env XCURSOR_THEME`, `env XCURSOR_SIZE`, `env GDK_SCALE`, `env GDK_DPI_SCALE`, `env QT_SCALE_FACTOR`, `env LC_MONETARY`, `env LC_PAPER`, `env LC_MEASUREMENT`, `env LC_ADDRESS`, `env LC_TELEPHONE`, `env LC_NAME`, `env LC_COLLATE`, `env LC_IDENTIFICATION`, `env TZ`, `env QT_SCREEN_SCALE_FACTORS`, `env QT_AUTO_SCREEN_SCALE_FACTOR`, `env QT_ENABLE_HIGHDPI_SCALING`, `env GTK_IM_MODULE`, `env QT_IM_MODULE`, `env XMODIFIERS`, `env SDL_IM_MODULE` | always | 17.4 "clears the environment to an allow-list" |
| `env http_proxy`, `env https_proxy`, `env ftp_proxy`, `env all_proxy`, `env no_proxy`, `env HTTP_PROXY`, `env HTTPS_PROXY`, `env FTP_PROXY`, `env ALL_PROXY`, `env NO_PROXY` | network | 17.4 "passing the proxy settings only to an app with the network grant" |
| `env GDK_DEBUG` | always | 17.4 "sets GDK_DEBUG=no-portals" |
| `dev /dev/tty` | always | 17.4 "the terminal-injection seccomp filter" |
| `dev /dev/dri/*` | always | 17.2 "Display, sound, GPU" |
| `mount /var/cache/fontconfig ro` | always | 17.4 "binds the font cache (/var/cache/fontconfig) read-only" |
| `mount /sys/block ro`, `mount /sys/bus ro`, `mount /sys/class ro`, `mount /sys/dev ro`, `mount /sys/devices ro` | always | 17.4 "the parts of /sys GPU drivers read to identify the GPU" |
| `id mac-address`, `id usb-serial`, `id block-serial`, `id dmi` | always | 17.17 "through /sys the network cards' MAC addresses, USB serial numbers and the hardware model" |
| `id machine-id`, `id boot-id`, `id hostname` | always | 17.17 "the machine-id, the boot id and the host name" |
| `mount $rt/bus rw`, `socket $rt/bus` | bus | 17.5 "the launcher starts one xdg-dbus-proxy" |
| `env DBUS_SESSION_BUS_ADDRESS` | always | 17.4 "points DBUS_SESSION_BUS_ADDRESS at a bus the sandbox doesn't have" |
| `mount $rt/doc rw` | bus | 17.4 "binds the document portal's view of this app's documents" |
| `net host interfaces` | network | 17.17 "a granted folder or network is the app's" |
| `net abstract sockets`, `net abstract session bus` | network | 17.9 "The same holds for every abstract-namespace socket on the host" |
| `mount /run/systemd/resolve ro`, `socket /run/systemd/resolve/io.systemd.Resolve`, `socket /run/systemd/resolve/io.systemd.Resolve.Monitor`, `mount /run/NetworkManager/resolv.conf ro` | network | 17.4 "binds where /etc/resolv.conf really lives when that is in /run" |
| `mount $rt/pipewire-0 ro`, `mount $rt/pulse/native ro`, `socket $rt/pipewire-0`, `socket $rt/pulse/native` | sound | 17.8 "Audio reaches the app through the session manager" |
| `dev /dev/video*`, `dev /dev/media*` | camera | 17.8 "binds the V4L2 devices" |
| `mount <folder> ro` | folder-ro | 17.2.1 "a folder (any path, read-only or read-write)" |
| `mount <folder> rw` | folder-rw | 17.2.1 "a folder (any path, read-only or read-write)" |
| `mount <cwd> rw` | cli | 17.3.3 "binds the directory the tool is run in (rw)" |
| `mount $img ro` | appimage | 17.7.1 "An AppImage's own .AppImage stays read-only whatever the grant" |
| `env APPDIR`, `env APPIMAGE`, `env ARGV0` | appimage | 17.7 "APPDIR/APPIMAGE/ARGV0 are set" |
| `mount $rt/$WAYLAND_DISPLAY ro`, `socket $rt/$WAYLAND_DISPLAY`, `env WAYLAND_DISPLAY` | wayland | 17.9 "The Wayland socket is bound on a Wayland session" |
| `mount /tmp/.X11-unix ro`, `socket /tmp/.X11-unix/X*`, `env DISPLAY`, `mount $XAUTHORITY ro`, `env XAUTHORITY` | x11 | 17.9 "else the X11 socket (with XAUTHORITY)" |

Not listed, so a failure wherever it is seen: another process of the host (each sandbox has its
own process namespace), and every variable, folder and socket not named above (`SSH_AUTH_SOCK`,
the real session bus, `~/.ssh`).
