#!/bin/sh
# Run the AppImage in a Linux Mint 22.3 container: --version, the screenshot tour on the demo data
# (scripts/demo_data.py), and
# --install-self from /tmp (requirement 2.11.3.1): the copy, its stable link, the desktop entry
# and icons, and that the installed copy starts.
# Then what it takes from the host (requirement 1.6; review 3, R3-31, R3-32): the libraries it needs
# against those 1.6 names (scripts/appimage_host_libs.py), and AppKata started on X11 and on Wayland
# in each 1.1 platform's desktop package set (scripts/appimage_desktop.sh): the tour runs offscreen and
# never loads the platform plugin a desktop session loads. The desktop images are built once
# (appkata-desktop-*, a few GB each).
# Screenshots go to build/appimage-test/<image>/.
#   scripts/test-appimage.sh [DEMO_DATA_DIR]      APPIMAGE_STEPS="mint hostlibs desktops" picks steps
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/appkata_core/__init__.py")
IMG="AppKata-$VERSION-x86_64.AppImage"
DATA=$(cd "${1:-$HERE/build/tour-data}" && pwd)
[ -f "$HERE/releases/$IMG" ] || { echo "build it first: scripts/build-appimage.sh" >&2; exit 1; }
[ -f "$DATA/appkata.db" ] || { echo "no demo data in $DATA (scripts/demo_data.py build|sync|finish)" >&2; exit 1; }
STEPS=${APPIMAGE_STEPS:-mint hostlibs desktops}
fail=0
for image in $(case " $STEPS " in *" mint "*) echo linuxmintd/mint22.3-amd64;; esac); do
    name=$(echo "$image" | sed 's#.*/##; s#-amd64##')
    out="$HERE/build/appimage-test/$name"
    rm -rf "$out"; mkdir -p "$out"
    echo "== $image"
    if docker run --rm -e QT_QPA_PLATFORM=offscreen -e APPKATA_TOUR_THEMES=dark \
        -v "$HERE/releases:/r:ro" -v "$DATA:/data:ro" -v "$out:/out" "$image" sh -c "
            set -e
            grep PRETTY_NAME /etc/os-release
            /r/$IMG --appimage-extract-and-run --version
            cp -r /data /tmp/d
            APPKATA_DATA=/tmp/d XDG_DATA_HOME=/tmp/d/xdg /r/$IMG --appimage-extract-and-run --tour /out \
                --tour-only C01-catalog,A02-apps-detail,S02-trust-detail 2>&1 | grep -v '^qt.qpa' || true
            test -f /out/dark/C01-catalog.png && test -f /out/dark/S02-trust-detail.png
            cp /r/$IMG /tmp/$IMG
            export HOME=/tmp/home XDG_DATA_HOME=/tmp/home/.local/share APPKATA_DATA=/tmp/home/data
            mkdir -p \$HOME
            stable=\$(/tmp/$IMG --appimage-extract-and-run --install-self | tail -1)
            test \"\$stable\" = /tmp/home/bin/apps/appkata/AppKata.AppImage
            test -L \"\$stable\" && test -x /tmp/home/bin/apps/appkata/AppKata-$VERSION-x86_64.AppImage
            grep -q \"Exec=\\\"\$stable\\\" %U\" \$XDG_DATA_HOME/applications/appkata.desktop
            grep -q StartupWMClass=appkata \$XDG_DATA_HOME/applications/appkata.desktop
            test -s \$XDG_DATA_HOME/icons/hicolor/scalable/apps/appkata.svg
            test -s \$XDG_DATA_HOME/icons/hicolor/256x256/apps/appkata.png
            \"\$stable\" --appimage-extract-and-run --version
            echo install-self ok
            chown -R $(id -u):$(id -g) /out"
    then echo "   ok: $(ls "$out/dark" | tr '\n' ' ')"
    else echo "   FAILED"; fail=1
    fi
done

# Each 1.1 distro's desktop, as its installer lays it down (recommends included), with the package
# list taken before the test's own tools (Xvfb, xwininfo, a Wayland compositor) go in.
# name | base image | how to install the desktop | the tools | how to list the packages
DESKTOPS="ubuntu22.04|ubuntu:22.04|apt ubuntu-desktop-minimal|xvfb x11-utils weston|dpkg
ubuntu24.04|ubuntu:24.04|apt ubuntu-desktop-minimal|xvfb x11-utils weston|dpkg
mint22.3|linuxmintd/mint22.3-amd64|apt mint-meta-cinnamon|xvfb x11-utils weston|dpkg
lmde7|linuxmintd/lmde7-amd64|apt mint-meta-cinnamon|xvfb x11-utils weston|dpkg"
# Desktops where AppKata doesn't start yet, as name:finding: reported, not failed. One that starts
# now fails the run, so the list shrinks
STILL_FAILING=""
desktop_image() {      # desktop_image <name>: build appkata-desktop-<name> once
    line=$(echo "$DESKTOPS" | grep "^$1|")
    base=$(echo "$line" | cut -d'|' -f2) how=$(echo "$line" | cut -d'|' -f3) tools=$(echo "$line" | cut -d'|' -f4)
    docker image inspect "appkata-desktop-$1" >/dev/null 2>&1 && return 0
    echo "== building appkata-desktop-$1 (once)"
    case $how in
        apt*) install="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ${how#apt } >/dev/null"
              list="dpkg-query -W -f '\${Package}\\n' > /desktop-packages.txt"
              more="DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $tools >/dev/null" ;;
    esac
    printf 'FROM %s\nRUN %s\nRUN %s\nRUN %s\n' "$base" "$install" "$list" "$more" | docker build -q -t "appkata-desktop-$1" - >/dev/null
}

if case " $STEPS " in *" hostlibs "*) true;; *) false;; esac; then
    echo "== what the AppImage takes from the host (scripts/appimage_host_libs.py)"
    run="$HERE/build/appimage-test/hostlibs" appdir="$HERE/build/appimage-test/appdir"
    rm -rf "$run" "$appdir"; mkdir -p "$run" "$appdir"
    (cd "$appdir" && "$HERE/releases/$IMG" --appimage-extract >/dev/null)
    desktop_image mint22.3
    docker run --rm -v "$HERE/releases:/r:ro" -v "$DATA:/data:ro" -v "$HERE/scripts/appimage_probe.sh:/probe.sh:ro" \
        -v "$run:/out" appkata-desktop-mint22.3 sh -c "sh /probe.sh /r/$IMG; chown -R $(id -u):$(id -g) /out"
    sed -n 's/^failed: /   a plugin the probe could not load: /p' "$run/probe.log"
    python3 "$HERE/scripts/appimage_host_libs.py" "$appdir/squashfs-root" "$run" || fail=1
fi

if case " $STEPS " in *" desktops "*) true;; *) false;; esac; then
    for name in $(echo "$DESKTOPS" | cut -d'|' -f1); do
        desktop_image "$name"
        echo "== $name desktop"
        docker run --rm -v "$HERE/releases:/r:ro" -v "$HERE/scripts/appimage_desktop.sh:/desktop.sh:ro" \
            "appkata-desktop-$name" sh /desktop.sh "/r/$IMG" | sed 's/^/   /' | tee "$HERE/build/appimage-test/desktop-$name.txt"
        listed=$(echo " $STILL_FAILING " | grep -o " $name:[^ ]*" || true)
        if grep -q FAILED "$HERE/build/appimage-test/desktop-$name.txt"; then
            if [ -n "$listed" ]; then echo "   listed: ${listed#*:}"; else fail=1; fi
        elif [ -n "$listed" ]; then
            echo "   starts now: take $name off STILL_FAILING"; fail=1
        fi
    done
fi
exit $fail
