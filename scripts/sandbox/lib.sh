# Sourced after session.sh. sbx <name> <command...> runs a command in the Standard profile, varied by:
# Part of scripts/test-sandbox.sh "session" (docs/app-sandboxing.md round 2). Runs inside the Mint 22.1 Wayland container.
#   SBX_DISPLAY = wayland | x11 | none     the display socket bound in (only that socket)
#   SBX_SOUND   = 1                        the PipeWire and PulseAudio sockets
#   SBX_BUS     = none | talk | flatpak    no session bus; xdg-dbus-proxy --talk=portal.Desktop; the same proxy
#                                          run with a /.flatpak-info, so portals treat the app as sandboxed
#   SBX_NET     = 1                        network
#   SBX_BINDS   = "--bind a a ..."         extra arguments (grants)
# The app's home is ~/.local/share/appkata/sandboxes/<name>; /x (the test files) is visible read-only.
RT=$XDG_RUNTIME_DIR
sbx_proxy() {          # sbx_proxy <name>: start this app's bus proxy, print its socket path
  local name=$1 sock=$RT/appkata/bus-$1
  mkdir -p $RT/appkata && rm -f $sock
  if [ "${SBX_BUS:-none}" = flatpak ]; then
    # the portal reads /.flatpak-info from the root of the process on the other end of the bus (the
    # proxy), as Flatpak arranges it, and treats the caller as that app: permissions are asked and kept
    # per app, and files are handed over through the document portal
    mkdir -p $HOME/.local/share/appkata/info
    printf '[Application]\nname=io.appkata.Sandboxed.%s\n\n[Instance]\ninstance-id=%s\n' "$name" "$RANDOM" > $HOME/.local/share/appkata/info/$name
    bwrap --ro-bind / / --dev /dev --bind $RT $RT --ro-bind $HOME/.local/share/appkata/info/$name /.flatpak-info \
      --die-with-parent -- xdg-dbus-proxy "$DBUS_SESSION_BUS_ADDRESS" $sock --filter --talk=org.freedesktop.portal.Desktop \
      --talk=org.freedesktop.portal.Documents > /tmp/proxy-$name.log 2>&1 &
  else
    xdg-dbus-proxy "$DBUS_SESSION_BUS_ADDRESS" $sock --filter --talk=org.freedesktop.portal.Desktop > /tmp/proxy-$name.log 2>&1 &
  fi
  for i in $(seq 50); do [ -S $sock ] && break; sleep 0.1; done
  echo $sock
}
sbx() {
  local name=$1; shift
  local home=$HOME/.local/share/appkata/sandboxes/$name args=()
  mkdir -p $home
  args+=(--ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/bin /bin --symlink usr/sbin /sbin
    --ro-bind /etc /etc --ro-bind-try /var/cache/fontconfig /var/cache/fontconfig --ro-bind /x /x
    --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run --dir $RT --bind $home $HOME
    --unshare-all --die-with-parent --new-session --clearenv
    --setenv HOME $HOME --setenv PATH /usr/bin --setenv LANG C.UTF-8 --setenv XDG_RUNTIME_DIR $RT --chdir $HOME)
  case ${SBX_DISPLAY:-none} in
    wayland) args+=(--ro-bind $RT/$WAYLAND_DISPLAY $RT/$WAYLAND_DISPLAY --setenv WAYLAND_DISPLAY $WAYLAND_DISPLAY
                    --setenv XDG_SESSION_TYPE wayland --setenv XDG_CURRENT_DESKTOP sway) ;;
    x11) args+=(--ro-bind /tmp/.X11-unix/X99 /tmp/.X11-unix/X99 --setenv DISPLAY :99 --setenv XDG_SESSION_TYPE x11) ;;
  esac
  [ "${SBX_SOUND:-}" = 1 ] && args+=(--ro-bind $RT/pipewire-0 $RT/pipewire-0 --ro-bind $RT/pulse/native $RT/pulse/native)
  [ "${SBX_NET:-}" = 1 ] && args+=(--share-net --ro-bind /etc/resolv.conf /etc/resolv.conf)
  if [ "${SBX_BUS:-none}" != none ]; then
    local sock; sock=$(sbx_proxy $name)
    args+=(--bind $sock $RT/bus --setenv DBUS_SESSION_BUS_ADDRESS unix:path=$RT/bus)
    if [ "$SBX_BUS" = flatpak ]; then
      args+=(--ro-bind $HOME/.local/share/appkata/info/$name /.flatpak-info)
      [ -d $RT/doc ] && args+=(--bind $RT/doc $RT/doc)
    fi
  fi
  # shellcheck disable=SC2086
  bwrap "${args[@]}" ${SBX_BINDS:-} "$@"
}
say() { printf '  %-8s %-58s %s\n' "$1" "$2" "${3:-}"; }   # say LEAKED|BLOCKED|WORKS|FAILS <what> [detail]
