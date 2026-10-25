#!/bin/sh
# Registers a default handler for https/http links and text/plain files on a test host, the way a
# desktop has firefox.desktop and xed.desktop registered. Run as root before the launcher tests
# (scripts/test-sandbox.sh launcher, scripts/sandbox/vm-launcher.sh). The handler records where it
# ran: tests/test_sandbox_run.py checks that a sandboxed `gio open` reaches the OpenURI portal and
# never this program inside the sandbox (requirement 17.4, round three R3-1).
set -eu
cat > /usr/share/applications/appkata-test-handler.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=AppKata test handler
Exec=/usr/local/bin/appkata-test-handler %u
MimeType=x-scheme-handler/https;x-scheme-handler/http;text/plain;
EOF
printf '#!/bin/sh\necho "ran inside: $*" >> "$HOME/appkata-test-handler-ran"\n' > /usr/local/bin/appkata-test-handler
chmod 755 /usr/local/bin/appkata-test-handler
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications
else        # no desktop-file-utils: write the cache GLib reads by hand
    c=/usr/share/applications/mimeinfo.cache
    [ -f "$c" ] || echo "[MIME Cache]" > "$c"
    for m in x-scheme-handler/https x-scheme-handler/http text/plain; do
        if grep -q "^$m=" "$c"; then sed -i "s|^$m=|$m=appkata-test-handler.desktop;|" "$c"
        else echo "$m=appkata-test-handler.desktop;" >> "$c"; fi
    done
fi
# A stand-in browser where the test host has none: xdg-open's generic road (no known desktop) runs
# the first of x-www-browser, firefox, ... it finds on PATH, and /usr is in view inside the sandbox.
# tests/test_sandbox_run.py checks that a Strict app's xdg-open never reaches it (round five, R5-4),
# and shows the road the shim covers with it. It is x-www-browser, the first name tried, which Mint's
# Firefox doesn't provide: beside a real browser the road reaches the stand-in, never the real one,
# which would start inside the sandbox and keep the test waiting (review 3, R3-35).
if ! command -v x-www-browser >/dev/null 2>&1; then
    printf '#!/bin/sh\necho "browser ran inside: $*" >> "$HOME/appkata-test-browser-ran"\n' > /usr/bin/x-www-browser
    chmod 755 /usr/bin/x-www-browser
fi
