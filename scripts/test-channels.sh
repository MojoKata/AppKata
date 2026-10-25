#!/bin/sh
# Package channels end to end (requirement 16) in containers, one per package manager: installs,
# updates, refusals, adopting and uninstalling through apt (command line, and PackageKit in one
# run), and a local Flatpak remote. Needs Docker; flatpak needs --privileged inside Docker
# (bubblewrap makes namespaces). No test needs Flathub. The dnf runs (Fedora, Rocky) retired with
# RPM support (requirement 1.1; docs/testing.md) and come back with it.
# Usage: scripts/test-channels.sh [ubuntu|ubuntu-pk|mint ...]   (default: all)
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
RUNS=${*:-ubuntu ubuntu-pk mint}
fail=0

apt_setup='export DEBIAN_FRONTEND=noninteractive; apt-get update -qq >/dev/null && apt-get install -y -qq python3 flatpak dpkg-dev apt-utils util-linux >/dev/null'

for run in $RUNS; do
    case $run in
        ubuntu)    image=ubuntu:24.04; setup=$apt_setup; args="--manager apt --pkg hello" ;;
        ubuntu-pk) image=ubuntu:24.04
                   setup="$apt_setup && apt-get install -y -qq packagekit dbus >/dev/null && mkdir -p /run/dbus && dbus-daemon --system --fork && (/usr/libexec/packagekitd >/tmp/pk.log 2>&1 &) && sleep 2"
                   args="--manager apt --pkg hello --packagekit --no-local --no-flatpak" ;;
        mint)      image=linuxmintd/mint22.3-amd64; setup=$apt_setup; args="--manager apt --pkg hello --no-flatpak" ;;
        *) echo "unknown run: $run" >&2; exit 2 ;;
    esac
    echo "== $run ($image)"
    if docker run --rm --privileged -v "$HERE:/src:ro" "$image" sh -c "
            set -e
            $setup
            python3 /src/scripts/channels_e2e.py $args"
    then echo "   ok"
    else echo "   FAILED"; fail=1
    fi
done
exit $fail
