#!/bin/sh
# The app-sandboxing experiment (docs/app-sandboxing.md).
#   probe    a "hostile app" probe (a Mint 22.3 container): Neovim's AppImage runs
#            scripts/sandbox/probe.lua unsandboxed and under the Standard and Strict bwrap profiles,
#            and the real files are checked afterwards.
#   gui      GUI apps in the Standard profile on Xvfb (Mint 22.3): AppKata's Qt AppImage and
#            Obsidian's Electron AppImage, with screenshots.
#   session  round 2: a Mint 22.3 container with a headless Wayland session (sway and mutter),
#            PipeWire and the portals. Display, sound, portal and Wayland-app isolation tests.
#   apparmor round 2: a real Ubuntu 24.04 VM under KVM (its own 6.8 kernel) — whether bwrap runs
#            under the default unprivileged-userns restriction, and that an AppArmor profile fixes it.
#   launcher tests/test_sandbox_run.py in a Linux Mint 22.3 container, the current release (bwrap 0.9,
#            xdg-dbus-proxy, the document portal on FUSE): the launchers AppKata generates, actually
#            run, as an ordinary user; tests/test_sandbox_exposure.py, everything they show checked
#            against docs/sandbox-exposure.md (review 3, harness 3); tests/test_sandbox_one_fact.py's
#            support status against what each level's launcher does (harness 4); and
#            tests/test_sandbox_user_shaped.py's arguments as users give them, through the real
#            document portal (harness 6). Extra args go to pytest.
#   launcher-lmde7  the same tests in an LMDE 7 container, Mint's Debian edition (Debian 13: bwrap
#            0.12, portal 1.20, GLib 2.84).
#   launcher-vm  the same tests in a real Ubuntu 24.04 VM under KVM (AppArmor userns restriction with
#            AppKata's profile applied, systemd-resolved DNS). The cloud image is cached in build/.
#   launcher-vm26  the same tests in an Ubuntu 26.04 LTS VM, under the system's own bwrap profile
#            (bwrap-userns-restrict: AppKata installs none; Chromium/Electron get --no-sandbox, 17.10.2).
#   wayland  the generated launcher under headless sway and a real PipeWire (Mint 22.3): a GTK3
#            window, a tone played as a sandboxed client, recording.
#   filedialogs  which file dialog GTK3, GTK4 and Qt 6 apps show inside a generated launcher, with
#            xdg-desktop-portal and its gtk backend on the bus (Mint 22.3 container, Xvfb): the
#            app's own, as 17.6.3 says, and which proxy denial makes it so. filedialogs-lmde7: the same
#            on LMDE 7 (Qt 6.8, which reads /.flatpak-info, and GTK 4.18).
#   kwin     what KDE's kwin gives a sandboxed app (Mint 22.3's kwin 5.27 under --virtual): the
#            clipboard leaks (17.9). kwin-lmde7: the same with LMDE 7's kwin 6.3 (Plasma 6).
#   inputmethod  what IBus and Fcitx 5 give a sandboxed app through the filter (their portals, headless;
#            review 2 F15, review 3 R3-18).
#   consumers  real consumers of the desktop integration behind generated launchers (Mint 22.3 plus
#            Chromium and xdotool): a GLib notification with and without the capability, a GTK3 link
#            landing on the host, Chromium's file chooser.
# Which of these run when, and on what: docs/testing.md.
# Containers need seccomp, AppArmor and the masked /proc paths opened so bwrap can nest; apparmor
# needs /dev/kvm. Output goes to build/sandbox-test/.
# Usage: scripts/test-sandbox.sh [launcher|launcher-lmde7|launcher-vm|launcher-vm26|wayland|kwin|kwin-lmde7|inputmethod|filedialogs|filedialogs-lmde7|consumers|probe|gui|session|apparmor]   (default: probe then gui)
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
OPEN="--security-opt seccomp=unconfined --security-opt systempaths=unconfined --security-opt apparmor=unconfined"
# The launcher tiers run AppKata's code and the tests on the Python the release carries (requirement
# 1.2; review 3, R3-21: a system's older Python can't unpack a tarball the way AppKata does), fetched
# once into build/ and seen at /src/build/... in the containers; what a generated launcher runs on the
# host (the file-argument helper, the xdg-open shim) stays on each system's own python3 and its gi.
# The packages the Wayland session needs (installed into the container on each run; Mint's own
# servers aren't always reachable, so Ubuntu's archive supplies most of them).
SESS_PKGS="sway grim wtype wl-clipboard pipewire pipewire-pulse wireplumber pulseaudio-utils pipewire-bin \
xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-wlr xvfb xdotool xinput x11-apps imagemagick sox \
libnss3 libxcb-cursor0 libgtk-3-0t64 libgbm1 libasound2t64 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 \
libxcb-shape0 libxcb-render-util0 libxcb-image0 fuse3 mutter xwayland"

case "${1:-}" in launcher*)
    PYT=$(sh "$HERE/scripts/python-standalone.sh")
    CPY="/src${PYT#"$HERE"}" ;;
esac

if [ "${1:-}" = launcher ] || [ "${1:-}" = launcher-lmde7 ]; then
    # launcher: Linux Mint 22.3, the current release (bwrap 0.9.0, xdg-desktop-portal 1.20, GLib 2.80);
    # launcher-lmde7: LMDE 7, Mint's Debian edition (Debian 13: bwrap 0.12, portal 1.20, GLib 2.84).
    # xdg-desktop-portal brings xdg-document-portal (the file hand-over test mounts its FUSE view, hence
    # /dev/fuse and SYS_ADMIN below) and python3-gi makes the portal calls. dbus-x11, gnome-keyring and
    # firefox are what a stock install has that changes what a sandboxed app meets: D-Bus autolaunch
    # (R3-33), a secrets service the bus can start (R3-34), the real default browser (R3-35) -- found
    # by the desktop VMs (scripts/test-desktop-vm.sh), which no minimal image had shown. Autolaunch
    # needs a display it can reach, as a desktop has: Xvfb on :0, the DISPLAY the tests pass.
    if [ "$1" = launcher-lmde7 ]; then IMG=appkata-sandbox-lmde7 BASE=linuxmintd/lmde7-amd64
    else IMG=appkata-sandbox-mint22.3 BASE=linuxmintd/mint22.3-amd64; fi
    shift
    if ! docker image inspect "$IMG" >/dev/null 2>&1; then
        printf 'FROM %s\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-pytest dbus xdg-desktop-portal python3-gi fuse3 xdg-utils bubblewrap xdg-dbus-proxy libglib2.0-bin procps dbus-x11 gnome-keyring firefox xvfb >/dev/null && useradd -m kata\n' "$BASE" \
            | docker build -q -t "$IMG" - >/dev/null
    fi
    # a stand-in camera node, so the camera grant's binding can be checked; a registered handler for
    # links and text files, as a desktop has, so the sandbox's hiding of it can be checked (R3-1)
    # shellcheck disable=SC2086
    exec docker run --rm $OPEN --device /dev/fuse --cap-add SYS_ADMIN -v "$HERE:/src:ro" "$IMG" sh -c \
        '[ -e /dev/video0 ] || mknod -m 666 /dev/video0 c 81 0; sh /src/scripts/sandbox/register-test-handler.sh; mkdir -p /home/kata/tiny && mount -t tmpfs -o size=1m,mode=755 tmpfs /home/kata/tiny && chown kata:kata /home/kata/tiny; echo "bwrap $(bwrap --version), $(dpkg-query -W -f="\${Version}" xdg-desktop-portal) portal, GLib $(dpkg-query -W -f="\${Version}" libglib2.0-0t64)"; exec su kata -c "$0" -- sh "$@"' \
        'cd /tmp && { Xvfb :0 -screen 0 1280x800x24 >/dev/null 2>&1 & sleep 1; } && APPKATA_PYTHON='"$CPY"' APPKATA_SKIPS=launcher-'"${IMG#appkata-sandbox-}"' PYTHONPATH=/src/src exec '"$CPY"' -m pytest -q -p no:cacheprovider /src/tests/test_sandbox_run.py /src/tests/test_sandbox_exposure.py /src/tests/test_sandbox_one_fact.py /src/tests/test_sandbox_user_shaped.py /src/tests/test_platform_matrix.py "$@"' "$@"
fi

if [ "${1:-}" = wayland ]; then
    # The generated launcher under a real compositor and a real PipeWire (scripts/sandbox/wayland.py):
    # a GTK3 window on headless sway, a tone through PipeWire as a sandboxed client, recording
    # (round five, "Coverage after round five": the stand-ins with a real counterpart). Needs the
    # session image, Mint 22.3 with the session's packages, built here once (it was made by hand).
    if ! docker image inspect appkata-sandbox-session-mint22.3 >/dev/null 2>&1; then
        printf 'FROM linuxmintd/mint22.3-amd64\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq %s bubblewrap xdg-dbus-proxy python3-gi >/dev/null && useradd -m kata\n' "$SESS_PKGS" \
            | docker build -q -t appkata-sandbox-session-mint22.3 - >/dev/null
    fi
    # shellcheck disable=SC2086
    exec docker run --rm $OPEN --device /dev/fuse --cap-add SYS_ADMIN -v "$HERE:/src:ro" -v "$HERE/scripts/sandbox:/x:ro" appkata-sandbox-session-mint22.3 bash -c \
        'u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u && chmod 700 /run/user/$u; mkdir -m 1777 -p /tmp/.X11-unix; exec su kata -c ". /x/session.sh; exec python3 /x/wayland.py"'
fi

if [ "${1:-}" = kwin ] || [ "${1:-}" = kwin-lmde7 ]; then
    # What KDE's kwin gives a sandboxed app (scripts/sandbox/kwin.py; 17.9, round seven R7-1): the
    # clipboard-manager protocol to every client, so the clipboard leaks; capture and injection hidden.
    # kwin: Mint 22.3's kwin 5.27; kwin-lmde7: LMDE 7's kwin 6.3 (Plasma 6), which Ubuntu 25.04's tier
    # showed until it retired (round eight).
    if [ "$1" = kwin-lmde7 ]; then IMG=appkata-sandbox-kwin-lmde7 BASE=linuxmintd/lmde7-amd64
    else IMG=appkata-sandbox-kwin-mint22.3 BASE=linuxmintd/mint22.3-amd64; fi
    if ! docker image inspect "$IMG" >/dev/null 2>&1; then
        printf 'FROM %s\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dbus kwin-wayland wayland-utils wl-clipboard xwayland bubblewrap xdg-dbus-proxy python3 python3-gi libcap2-bin >/dev/null && useradd -m kata\n' "$BASE" \
            | docker build -q -t "$IMG" - >/dev/null
    fi
    # kwin_wayland carries cap_sys_nice; the container must be allowed it (or the file capability dropped)
    # shellcheck disable=SC2086
    exec docker run --rm $OPEN --cap-add SYS_ADMIN --cap-add SYS_NICE -v "$HERE:/src:ro" "$IMG" bash -c \
        'apt-get install -y -qq wl-clipboard >/dev/null 2>&1; setcap -r /usr/bin/kwin_wayland 2>/dev/null; u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u && chmod 700 /run/user/$u; mkdir -m 1777 -p /tmp/.X11-unix; exec su kata -c "export HOME=/home/kata XDG_RUNTIME_DIR=/run/user/$u XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=KDE DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus; dbus-daemon --session --address=\$DBUS_SESSION_BUS_ADDRESS --fork --nopidfile; kwin_wayland --virtual --no-lockscreen --no-global-shortcuts --socket wayland-7 >/tmp/kwin.log 2>&1 & for i in \$(seq 100); do [ -S /run/user/$u/wayland-7 ] && break; sleep 0.2; done; export WAYLAND_DISPLAY=wayland-7; cd /tmp && exec python3 /src/scripts/sandbox/kwin.py"'
fi

if [ "${1:-}" = inputmethod ]; then
    # What IBus and Fcitx 5 give a sandboxed app through AppKata's filter (scripts/sandbox/inputmethod.py;
    # review 2, F15; review 3, R3-18): the portals they provide for sandboxed apps, run headless.
    docker image inspect appkata-sandbox-mint22.3 >/dev/null 2>&1 || { echo "no appkata-sandbox-mint22.3 image; run scripts/test-sandbox.sh launcher first" >&2; exit 1; }
    if ! docker image inspect appkata-sandbox-im-mint22.3 >/dev/null 2>&1; then
        printf 'FROM appkata-sandbox-mint22.3\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ibus fcitx5 bubblewrap xdg-dbus-proxy libglib2.0-bin >/dev/null\n' \
            | docker build -q -t appkata-sandbox-im-mint22.3 - >/dev/null
    fi
    # shellcheck disable=SC2086
    exec docker run --rm $OPEN -v "$HERE:/src:ro" appkata-sandbox-im-mint22.3 bash -c \
        'u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u && chmod 700 /run/user/$u; exec su kata -c "export HOME=/home/kata XDG_RUNTIME_DIR=/run/user/$u DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus; dbus-daemon --session --address=\$DBUS_SESSION_BUS_ADDRESS --fork --nopidfile; ibus-daemon --daemonize --replace --panel=disable 2>/dev/null; fcitx5 -d --disable=wayland,xim,x11 >/dev/null 2>&1; sleep 3; cd /tmp && exec python3 /src/scripts/sandbox/inputmethod.py"'
fi

if [ "${1:-}" = filedialogs ] || [ "${1:-}" = filedialogs-lmde7 ]; then
    # Which file dialog GTK3, GTK4 and Qt 6 apps show inside a generated launcher, with the real
    # portal on the bus (scripts/sandbox/filedialogs.py; requirement 17.6.3, round four R4-5).
    # filedialogs: Mint 22.3 (Qt 6.4, GTK 4.14); filedialogs-lmde7: LMDE 7 (Qt 6.8, which reads
    # /.flatpak-info, and GTK 4.18), which Ubuntu 25.04's tier showed until it retired (round six).
    if [ "$1" = filedialogs-lmde7 ]; then IMG=appkata-sandbox-dialogs-lmde7 BASE=linuxmintd/lmde7-amd64
    else IMG=appkata-sandbox-dialogs-mint22.3 BASE=linuxmintd/mint22.3-amd64; fi
    EXTRA="bubblewrap xdg-dbus-proxy libglib2.0-bin"
    if ! docker image inspect "$IMG" >/dev/null 2>&1; then
        printf 'FROM %s\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dbus xdg-desktop-portal xdg-desktop-portal-gtk xvfb x11-utils python3-gi gir1.2-gtk-3.0 gir1.2-gtk-4.0 python3-pyqt6 qt6-xdgdesktopportal-platformtheme fuse3 %s >/dev/null && useradd -m kata\n' "$BASE" "$EXTRA" \
            | docker build -q -t "$IMG" - >/dev/null
    fi
    # shellcheck disable=SC2086
    exec docker run --rm $OPEN --device /dev/fuse --cap-add SYS_ADMIN -v "$HERE:/src:ro" "$IMG" sh -c \
        'sh /src/scripts/sandbox/register-test-handler.sh; u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u && chmod 700 /run/user/$u; exec su kata -c "exec python3 /src/scripts/sandbox/filedialogs.py"'
fi

if [ "${1:-}" = consumers ]; then
    # Real consumers behind generated launchers (scripts/sandbox/consumers.py): a GLib app's
    # notification with and without the capability, a GTK3 app's link opening on the host, and
    # Chromium's file chooser under three proxy variants (17.5.1, 17.6.3; round four).
    if ! docker image inspect appkata-sandbox-consumers-mint22.3 >/dev/null 2>&1; then
        printf 'FROM linuxmintd/mint22.3-amd64\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dbus xdg-desktop-portal xdg-desktop-portal-gtk xvfb x11-utils xdotool python3-gi gir1.2-gtk-3.0 gir1.2-gtk-4.0 python3-pyqt6 dunst chromium fuse3 >/dev/null && useradd -m kata\n' \
            | docker build -q -t appkata-sandbox-consumers-mint22.3 - >/dev/null
    fi
    # shellcheck disable=SC2086
    exec docker run --rm $OPEN --device /dev/fuse --cap-add SYS_ADMIN -v "$HERE:/src:ro" appkata-sandbox-consumers-mint22.3 sh -c \
        'sh /src/scripts/sandbox/register-test-handler.sh; u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u && chmod 700 /run/user/$u; exec su kata -c "exec python3 /src/scripts/sandbox/consumers.py"'
fi

if [ "${1:-}" = launcher-vm ] || [ "${1:-}" = launcher-vm26 ]; then
    # launcher-vm26: Ubuntu 26.04 LTS, where the system's own bwrap-userns-restrict profile confines
    # what bwrap runs and AppKata installs no profile of its own (17.10.2, review 2 F2)
    if [ "$1" = launcher-vm26 ]; then IMG=resolute.img; IMGURL=https://cloud-images.ubuntu.com/releases/26.04/release/ubuntu-26.04-server-cloudimg-amd64.img
    else IMG=noble.img; IMGURL=https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img; fi
    shift
    [ -e /dev/kvm ] || { echo "no /dev/kvm; launcher-vm needs KVM" >&2; exit 1; }
    VM=$HERE/build/sandbox-test/vm; mkdir -p "$VM"
    if ! docker image inspect appkata-qvm >/dev/null 2>&1; then
        printf 'FROM ubuntu:24.04\nRUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq qemu-system-x86 qemu-utils cloud-image-utils curl python3 >/dev/null\n' \
            | docker build -q -t appkata-qvm - >/dev/null
    fi
    git -C "$HERE" ls-files -co --exclude-standard src tests docs scripts/sandbox/register-test-handler.sh scripts/sandbox/field-test.sh scripts/sandbox/fieldtest.py scripts/sandbox/exposure.py | tar -C "$HERE" -czf "$VM/src.tgz" -T -
    cp "$HERE/scripts/sandbox/vm-launcher.sh" "$VM/"
    PYT=$(sh "$HERE/scripts/python-standalone.sh")          # the release's Python, beside the source
    tar -C "$(dirname "$(dirname "$(dirname "$PYT")")")" -czf "$VM/py.tgz" python
    docker run --rm --device /dev/kvm -v "$VM:/vm" -e PYTEST_ARGS="$*" -e IMG="$IMG" -e IMGURL="$IMGURL" appkata-qvm bash -c '
        set -e; cd /vm
        [ -f "$IMG" ] || curl -sSL -o "$IMG" "$IMGURL"
        echo "instance-id: iid-$$; local-hostname: vmtest" > meta-data
        { echo "#cloud-config"; echo "password: ubuntu"; echo "chpasswd: { expire: false }"
          echo "packages: [bubblewrap, xdg-dbus-proxy, dbus-daemon, python3-pytest, curl, xdg-desktop-portal, python3-gi, mesa-utils]"; echo "package_update: true"
          echo "write_files:"; echo "  - path: /root/vm-launcher.sh"; echo "    permissions: \"0755\""
          echo "    encoding: b64"; echo "    content: $(base64 -w0 vm-launcher.sh)"
          echo "runcmd: [[ env, \"PYTEST_ARGS=$PYTEST_ARGS\", bash, /root/vm-launcher.sh ]]"; } > user-data
        cloud-localds seed.iso user-data meta-data
        rm -f disk.qcow2; qemu-img create -f qcow2 -b "$IMG" -F qcow2 disk.qcow2 12G >/dev/null
        (python3 -m http.server 8000 --bind 0.0.0.0 >/dev/null 2>&1 &)
        timeout 900 qemu-system-x86_64 -enable-kvm -cpu host -m 2048 -smp 2 -nographic -serial mon:stdio -device virtio-gpu-pci \
          -drive file=disk.qcow2,if=virtio -drive file=seed.iso,if=virtio,format=raw \
          -netdev user,id=n0 -device virtio-net-pci,netdev=n0 > serial.log 2>&1 || true
        sed -n "/=====VMTEST BEGIN/,/=====VMTEST END/p" serial.log | tr -d "\r"'
    exit 0
fi

OUT=$HERE/build/sandbox-test
mkdir -p "$OUT/gui"
cp "$HERE"/scripts/sandbox/*.sh "$HERE"/scripts/sandbox/*.lua "$HERE"/scripts/sandbox/*.py "$OUT/" 2>/dev/null || true
[ -f "$OUT/nvim.appimage" ] || curl -sSL -o "$OUT/nvim.appimage" \
    https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.appimage
chmod +x "$OUT/nvim.appimage"

fetch_appimages() {       # AppKata's own build and Obsidian, into $OUT, for the gui/session modes
    VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/appkata_core/__init__.py")
    IMG="$HERE/releases/AppKata-$VERSION-x86_64.AppImage"
    [ -f "$IMG" ] || { echo "build it first: scripts/build-appimage.sh" >&2; exit 1; }
    cp "$IMG" "$OUT/AppKata.AppImage"
    if [ ! -f "$OUT/obsidian.AppImage" ]; then
        tag=$(curl -sSI https://github.com/obsidianmd/obsidian-releases/releases/latest | sed -n 's#^location: .*/tag/v\(.*\)\r$#\1#ip')
        curl -sSL -o "$OUT/obsidian.AppImage" "https://github.com/obsidianmd/obsidian-releases/releases/download/v$tag/Obsidian-$tag.AppImage"
        chmod +x "$OUT/obsidian.AppImage"
    fi
}

if [ "${1:-probe}" = probe ]; then
    for image in linuxmintd/mint22.3-amd64; do
        name=$(echo "$image" | sed 's#.*/##; s#-amd64##')
        echo "== $image"
        # shellcheck disable=SC2086
        docker run --rm $OPEN -v "$OUT:/x:ro" "$image" bash /x/probe.sh | tee "$OUT/probe-$name.txt"
    done
fi

if [ "${1:-gui}" = gui ]; then
    fetch_appimages
    # shellcheck disable=SC2086
    docker run --rm $OPEN -v "$OUT:/x:ro" -v "$OUT/gui:/out" linuxmintd/mint22.3-amd64 bash /x/gui.sh
    echo "screenshots and logs: $OUT/gui/"
fi


if [ "${1:-}" = session ]; then
    fetch_appimages
    # shellcheck disable=SC2086
    docker run --rm $OPEN --device /dev/fuse --cap-add SYS_ADMIN -v "$OUT:/x:ro" -v "$OUT/gui:/out" \
        linuxmintd/mint22.3-amd64 bash -c '
        set -e
        apt-get update -qq >/dev/null 2>&1 || true
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq '"$SESS_PKGS"' >/tmp/apt.log 2>&1 || { tail -5 /tmp/apt.log; exit 1; }
        id kata >/dev/null 2>&1 || useradd -m kata
        u=$(id -u kata); mkdir -p /run/user/$u && chown kata:kata /run/user/$u
        # one shell, so the sway/PipeWire/portal session (started by session.sh) persists across tests
        su kata -s /bin/bash -c "for t in display sound portals filechooser apps-wayland; do
            echo \"### \$t\"; bash /x/\$t.sh || echo \"(\$t exited \$?)\"; done"'
fi

if [ "${1:-}" = apparmor ]; then
    [ -e /dev/kvm ] || { echo "no /dev/kvm; the AppArmor test needs KVM" >&2; exit 1; }
    docker rm -f appkata-qvm >/dev/null 2>&1 || true
    docker run -d --name appkata-qvm --device /dev/kvm -v "$OUT:/x:ro" ubuntu:24.04 sleep infinity >/dev/null
    docker exec appkata-qvm sh -c 'apt-get update -qq >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive \
        apt-get install -y -qq qemu-system-x86 qemu-utils cloud-image-utils curl >/dev/null 2>&1'
    docker exec appkata-qvm sh -c 'cd /root && [ -f noble.img ] || curl -sSL -o noble.img \
        https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img'
    docker exec appkata-qvm sh -c '
        cd /root
        echo "instance-id: iid; local-hostname: vmtest" > meta-data
        { echo "#cloud-config"; echo "password: ubuntu"; echo "chpasswd: { expire: false }";
          echo "packages: [bubblewrap, apparmor-utils]"; echo "package_update: true";
          echo "write_files:"; echo "  - path: /root/vmtest.sh"; echo "    permissions: \"0755\"";
          echo "    encoding: b64"; echo "    content: $(base64 -w0 /x/vmtest.sh)";
          echo "runcmd: [[ bash, /root/vmtest.sh ]]"; } > user-data
        cloud-localds seed.iso user-data meta-data
        qemu-img create -f qcow2 -b noble.img -F qcow2 disk.qcow2 12G >/dev/null 2>&1
        timeout 480 qemu-system-x86_64 -enable-kvm -m 2048 -smp 2 -nographic -serial mon:stdio \
          -drive file=disk.qcow2,if=virtio -drive file=seed.iso,if=virtio,format=raw \
          -netdev user,id=n0 -device virtio-net-pci,netdev=n0 > serial.log 2>&1 || true
        sed -n "/VMTEST BEGIN/,/VMTEST END/p" serial.log'
    docker rm -f appkata-qvm >/dev/null 2>&1 || true
fi
