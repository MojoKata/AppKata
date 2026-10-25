#!/bin/bash
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
# Real apps on Wayland only (sway, no XWayland): unpacked AppImages in the Standard profile with the
# Wayland socket, sound and the filtered bus; screenshots taken outside with grim.
. /x/session.sh; . /x/lib.sh
mkdir -p /tmp/out
for app in appkata:AppKata.AppImage obsidian:obsidian.AppImage; do
  name=${app%%:*} img=${app#*:} dir=$HOME/bin/apps/$name/1
  [ -x $dir/extracted/AppRun ] || { mkdir -p $dir && cp /x/$img $dir/ && (cd $dir && ./$img --appimage-extract >/dev/null && mv squashfs-root extracted); }
  case $name in
    appkata) extra=(--setenv QT_QPA_PLATFORM wayland) args=() ;;
    obsidian) extra=() args=(--ozone-platform=wayland --enable-features=UseOzonePlatform,WaylandWindowDecorations) ;;
  esac
  SBX_DISPLAY=wayland SBX_SOUND=1 SBX_BUS=talk SBX_NET=1 SBX_BINDS="--ro-bind $dir $dir ${extra[*]}" \
    sbx $name $dir/extracted/AppRun "${args[@]}" > /tmp/out/$name-wayland.log 2>&1 & pid=$!
  sleep 15
  grim /tmp/out/$name-wayland.png 2>/dev/null
  if kill -0 $pid 2>/dev/null; then say WORKS "$name on Wayland only, sandboxed" "running after 15 s"; else wait $pid; say FAILS "$name on Wayland only" "exit $?"; fi
  pkill -f "$dir/extracted" 2>/dev/null; sleep 1
  grep -iE "error|fatal|wayland" /tmp/out/$name-wayland.log | grep -v "Failed to connect to the bus" | head -3 | sed 's/^/    /'
done
