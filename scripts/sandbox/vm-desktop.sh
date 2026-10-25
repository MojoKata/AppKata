#!/bin/bash
# Part of scripts/test-desktop-vm.sh. Runs as "kata" inside the real Cinnamon session of a Linux Mint
# 22.3 or LMDE 7 VM installed from its ISO (started by the session's autostart, so it has the
# session's DISPLAY, D-Bus and portals): reports the stock system as installed, starts the AppImage as
# a user would, runs the launcher tests as this user with the sandbox set up as AppKata's setup
# would, and the field test. Everything goes to the serial console between =====VMTEST markers; a
# "VMSHOT name" line has the host take a screenshot of the session.
exec > /dev/ttyS0 2>&1
echo "=====VMTEST BEGIN====="
. /etc/os-release
echo "$PRETTY_NAME, kernel $(uname -r), session ${XDG_SESSION_TYPE:-?} on ${XDG_CURRENT_DESKTOP:-?}, DISPLAY=${DISPLAY:-}"
echo "-- the stock system, as installed"
for p in bubblewrap xdg-dbus-proxy flatpak fuse3 libxcb-cursor0 libgssapi-krb5-2 python3-gi xdg-desktop-portal \
         xdg-desktop-portal-xapp xdg-desktop-portal-gtk gnome-keyring policykit-1-gnome mate-polkit firefox x11-utils; do
    v=$(dpkg-query -W -f='${Version}' "$p" 2>/dev/null) && echo "  $p $v" || echo "  $p: not installed"
done
echo "  kernel.apparmor_restrict_unprivileged_userns=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo absent)"
echo "VMSHOT 01-session"
sleep 3
mkdir -p ~/vmtest && cd ~/vmtest || exit 1
curl -sSf http://10.0.2.2:8000/src.tgz | tar -xz
curl -sSf http://10.0.2.2:8000/py.tgz | tar -xz
curl -sSf -o AppKata.AppImage http://10.0.2.2:8000/AppKata.AppImage && chmod +x AppKata.AppImage
PY=$PWD/python/bin/python3
echo "-- the sandbox as AppKata finds it, before any setup"
PYTHONPATH=src $PY -c 'from appkata_core import sandbox as s; st = s.support_status(); print("  support:", st["status"], "| tools:", st.get("tools"), "| missing:", st.get("missing"))'

echo "-- AppKata started as a user starts it: the AppImage, through FUSE"
./AppKata.AppImage > appimage.log 2>&1 &
sleep 25
py=$(pgrep -n -f -- "-s -m appkata")
if [ -n "$py" ]; then
    echo "  running; platform plugin: $(grep -o 'libQt6XcbQpa\|libQt6WaylandClient' /proc/$py/maps | sort -u | tr '\n' ' ')"
    echo "  windows: $(command -v xwininfo >/dev/null && xwininfo -root -tree | grep -ci appkata || echo 'no xwininfo')"
else
    echo "  NOT running: $(tail -5 appimage.log | tr '\n' ' ')"
fi
echo "VMSHOT 02-appkata-first-start"
sleep 3
pkill -f -- "-s -m appkata"; sleep 2

echo "-- the launcher tests, as this user, with the sandbox set up as AppKata's setup would"
others=$(PYTHONPATH=src $PY -c 'from appkata_core import sandbox; print(" ".join(sandbox.other_bwrap_profiles()))')
if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ] && [ -z "$others" ]; then
    PYTHONPATH=src $PY -c 'from appkata_core import sandbox; print(sandbox.profile_text(), end="")' | sudo tee /etc/apparmor.d/appkata-sandbox >/dev/null \
        && sudo apparmor_parser -r /etc/apparmor.d/appkata-sandbox && echo "  AppArmor profile loaded"
else
    echo "  no setup needed (restriction: $(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo absent); other bwrap profiles: ${others:-none})"
fi
sudo sh scripts/sandbox/register-test-handler.sh >/dev/null && echo "  test handler registered"
PYTHONPATH=src APPKATA_PYTHON=$PY APPKATA_BOOTED=1 $PY -m pytest -q -rfEs --tb=short -p no:cacheprovider tests/test_sandbox_run.py \
    tests/test_sandbox_exposure.py tests/test_sandbox_one_fact.py tests/test_sandbox_user_shaped.py tests/test_booted.py 2>&1

echo "-- the field test, non-interactive"
APPKATA_PYTHON=$PY bash scripts/sandbox/field-test.sh --non-interactive 2>&1 | sed -n '/^== checks ==/,$p'   # every check (its environment is above)
echo "VMSHOT 03-after"
sleep 3
echo "=====VMTEST END====="
sleep 5
sudo poweroff
