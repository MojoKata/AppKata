#!/bin/sh
# Install the latest Windows build in the shared Windows VM and check it (docs/build.md § Windows):
# a per-user install with no UAC prompt, the appkata:// handler, the Start-menu shortcut, an
# uninstall; then (with --shots) the screenshot tour into screenshots/windows/{dark,light}.
# --tests runs the unit tests with Python on Windows; --e2e installs and uninstalls real apps from
# GitHub through AppKata's own code (scripts/windows_e2e.py; it leaves Git for Windows installed).
#   scripts/test-windows-vm.sh [--tests] [--e2e] [--shots] [--tour-only A01-apps,C01-catalog]
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/packaging/versions.env"          # PY_SERIES, PYSIDE (requirement 1.2)
[ ! -f "$HERE/local.env" ] || . "$HERE/local.env"     # this machine's settings (coworker/README.md)
[ -z "${VM_DIR:-}" ] || export VM_DIR
# The VM can be shared with the machine's other projects (coworker/vm): AppKata claims it, runs
# holding its lock (another project's run is waited for), and reaches it as its vm.env says.
WINDOWS_VM=${WINDOWS_VM:-win10}
"$HERE/coworker/vm/claim.sh" "$WINDOWS_VM" appkata >/dev/null
[ -n "${COWORKER_VM_LOCKED:-}" ] || exec "$HERE/coworker/vm/lock.sh" "$WINDOWS_VM" appkata -- sh "$0" "$@"
eval "$("$HERE/coworker/vm/env.sh" "$WINDOWS_VM")"    # VM_CONTAINER, VM_SSH_*
R="$VM_SSH_USER@$VM_SSH_HOST"
SHOTS=0; ONLY=""; TESTS=0; E2E=0
while [ $# -gt 0 ]; do
    case "$1" in
        --shots) SHOTS=1 ;;
        --tests) TESTS=1 ;;
        --e2e) E2E=1 ;;
        --tour-only) ONLY=$2; shift ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
    shift
done
SETUP=$(ls -t "$HERE"/releases/AppKata-*-setup.exe | head -1)
S=$(basename "$SETUP")
OPTS="-q -i $VM_SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=$VM_KNOWN_HOSTS -o BatchMode=yes"
SSH="ssh $OPTS -p $VM_SSH_PORT $R"
SCP="scp $OPTS -P $VM_SSH_PORT"
D=C:/Users/Public/appkata-test
UNINST='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E3B9C51-6A2D-4F7E-B1C4-3D5A7E9F0B12}_is1'
APP='$env:LOCALAPPDATA\Programs\AppKata'
run() { $SSH "$1" 2>&1 | tr -d '\r' | grep -v '^$' || true; }
limited() {   # limited <powershell> [seconds]: run it in the console session, not elevated (as a normal user)
    { echo '& {'; printf '%s\n' "$1"; echo "} *> $D/limited-out.txt"; echo "New-Item $D/limited-done.txt | Out-Null"; } \
        > "$HERE/build/limited.ps1"
    $SCP "$HERE/build/limited.ps1" "$R:$D/limited.ps1"
    run "Remove-Item $D/limited-out.txt, $D/limited-done.txt -ErrorAction SilentlyContinue
         schtasks /create /tn AppKataLimited /tr 'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $D/limited.ps1' /sc once /st 23:59 /ru $VM_SSH_USER /it /rl LIMITED /f | Out-Null
         schtasks /run /tn AppKataLimited | Out-Null
         for (\$i = 0; \$i -lt ${2:-300} -and -not (Test-Path $D/limited-done.txt); \$i++) { Start-Sleep 1 }
         schtasks /delete /tn AppKataLimited /f | Out-Null"
}
expect() {   # expect <output> <text>: fail unless the output contains the text
    echo "$1" | grep -q -- "$2" || { echo "FAIL: expected \"$2\""; exit 1; }
}

if [ -n "$VM_CONTAINER" ] && [ "$(docker inspect -f '{{.State.Running}}' "$VM_CONTAINER" 2>/dev/null)" != "true" ]; then
    echo "== starting the VM"
    docker start "$VM_CONTAINER" >/dev/null
fi
for i in $(seq 1 60); do $SSH "echo up" >/dev/null 2>&1 && break; sleep 5; done

PY=C:/Users/Public/appkata-py/python/python.exe
if [ "$TESTS" = 1 ] || [ "$E2E" = 1 ]; then
    # Python for Windows from python-build-standalone (GitHub), checked against its SHA256SUMS
    if ! $SSH "Test-Path $PY" | grep -q True; then
        echo "== Python for the tests"
        C="$HERE/build/winpy"; mkdir -p "$C"
        TAG=$(curl -sSIL -o /dev/null -w '%{url_effective}' https://github.com/astral-sh/python-build-standalone/releases/latest | sed 's#.*/tag/##')
        NAME=$(curl -sSL "https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/$TAG" |
               grep -o "cpython-$(echo "$PY_SERIES" | sed 's/\./\\./')\.[0-9]*+[0-9]*-x86_64-pc-windows-msvc-install_only\.tar\.gz" | head -1)
        curl -sSL -o "$C/py.tar.gz" "https://github.com/astral-sh/python-build-standalone/releases/download/$TAG/$NAME"
        curl -sSL "https://github.com/astral-sh/python-build-standalone/releases/download/$TAG/SHA256SUMS" |
            grep " $NAME\$" | awk '{print $1"  py.tar.gz"}' | (cd "$C" && sha256sum -c --quiet)
        run "New-Item -ItemType Directory -Force $D | Out-Null"
        $SCP "$C/py.tar.gz" "$R:$D/py.tar.gz"
        run "New-Item -ItemType Directory -Force C:/Users/Public/appkata-py | Out-Null; tar -xzf $D/py.tar.gz -C C:/Users/Public/appkata-py
             & $PY -m pip install -q pytest truststore 2>&1 | Select-String -NotMatch 'WARNING|PATH'"
    fi
    echo "== copy the sources"
    # what the tests read: the sources, the tests, the scripts and documents they check, from git's
    # list of files (only five paths went before, and every test reading another one failed there)
    (cd "$HERE" && rm -f build/src-tests.zip && git ls-files -co --exclude-standard src tests scripts docs packaging README.md pyproject.toml |
        grep -v -e '/__pycache__/' -e '\.egg-info/' | zip -q build/src-tests.zip -@)
    $SCP "$HERE/build/src-tests.zip" "$R:$D/src.zip"
    run "Remove-Item -Recurse -Force $D/src -ErrorAction SilentlyContinue; Expand-Archive $D/src.zip $D/src"
fi
if [ "$E2E" = 1 ]; then
    echo "== installing real apps (scripts/windows_e2e.py)"
    OUT=$(run "cd $D/src; & $PY scripts/windows_e2e.py")
    echo "$OUT"
    expect "$OUT" "PASS"
fi
if [ "$TESTS" = 1 ]; then
    echo "== unit tests on Windows"
    OUT=$(run "cd $D/src; \$env:Path = 'C:/Program Files/Git/cmd;' + \$env:Path; & $PY -m pytest -q -p no:cacheprovider 2>&1 | Select -Last 15")
    echo "$OUT"
    expect "$OUT" " passed"
    if echo "$OUT" | grep -q " failed\| error"; then echo "FAIL: unit tests"; exit 1; fi
fi

echo "== copy $S"
run "New-Item -ItemType Directory -Force $D | Out-Null"
$SCP "$SETUP" "$R:$D/"

echo "== install for the current user (no UAC prompt)"
# The VM's SSH session is elevated: run Setup in the console session with a limited token,
# as a normal user would, so a per-user install that needs no administrator rights is proven.
limited "\$p = Start-Process -Wait -PassThru $D/$S -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER'
         'setup exit: ' + \$p.ExitCode"
OUT=$(run "Get-Content $D/limited-out.txt
     'exe: ' + (Test-Path \"$APP\\appkata.exe\")
     'qml: ' + (Test-Path \"$APP\\_internal\\appkata\\qml\\Main.qml\")
     \$u = Get-ItemProperty '$UNINST' -ErrorAction SilentlyContinue
     'uninstall entry: ' + [bool]\$u + ' ' + \$u.DisplayVersion + ' ' + \$u.InstallLocation
     'machine entry: ' + (Test-Path ('$UNINST' -replace 'HKCU','HKLM'))
     'link handler: ' + (Get-ItemProperty 'HKCU:\Software\Classes\appkata\shell\open\command').'(default)'
     'shortcut: ' + (Test-Path \"\$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\AppKata.lnk\")")
echo "$OUT"
expect "$OUT" "setup exit: 0"
expect "$OUT" "exe: True"
expect "$OUT" "qml: True"
expect "$OUT" "uninstall entry: True"
expect "$OUT" "machine entry: False"
expect "$OUT" "appkata.exe\" \"%1\""
expect "$OUT" "shortcut: True"

echo "== it starts"
# a windowed exe has no stdout: check it runs and exits cleanly
OUT=$(run "\$p = Start-Process -Wait -PassThru \"$APP\\appkata.exe\" -ArgumentList '--version'; 'version exit: ' + \$p.ExitCode")
echo "$OUT"
expect "$OUT" "version exit: 0"

if [ "$SHOTS" = 1 ]; then
    # ------------------------------------------------------------------ screenshots
    # The demo data (scripts/demo_data.py) holds absolute Linux paths; a copy is rewritten for the VM.
    echo "== screenshots"
    TD="$HERE/build/tour-data"
    test -f "$TD/appkata.db" || { echo "no demo data: see docs/build.md (scripts/demo_data.py)"; exit 1; }
    # stage sets the screens' times by this machine's clock and the tour shows them by the VM's: the
    # two must agree (review 3, R3-30: Windows read the VM's clock as Pacific time, 7 hours fast).
    # Set it from this machine's, for this run only: the VM's own settings are left as they are
    run "Set-Date ([DateTimeOffset]::FromUnixTimeSeconds($(date +%s)).LocalDateTime) | Out-Null"
    VMNOW=$(run "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()")
    SKEW=$(( VMNOW - $(date +%s) ))
    echo "VM clock: ${SKEW#-} s $([ "$SKEW" -lt 0 ] && echo behind || echo ahead)"
    [ "${SKEW#-}" -le 60 ] || { echo "FAIL: the VM's clock is ${SKEW#-} s off this machine's"; exit 1; }
    # the minimum age and the sync times, as of now (R3-24); the Audit's days in the VM's time zone,
    # which the tour shows them in
    python3 "$HERE/scripts/demo_data.py" stage "$TD" --utc-offset "$(run "(Get-Date).ToString('zzz')")"
    python3 "$HERE/scripts/demo_data.py" check "$TD"  # no failed sync, and what screenshots/README.md says each screen shows
    W="$HERE/build/windows-tour"
    rm -rf "$W"; mkdir -p "$W"; cp -a "$TD" "$W/tour-data"; rm -rf "$W/tour-data/logs"
    python3 - "$W/tour-data" "$TD" "$D/tour-data" <<'PY'
import os, sqlite3, sys
copy, linux, win = sys.argv[1:]
db = sqlite3.connect(os.path.join(copy, "appkata.db"))
for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({t})") if r[2].upper() in ("TEXT", "")]
    if t == "audit":
        db.execute("DROP TRIGGER IF EXISTS audit_no_update")    # the copy only; triggers are recreated on open
    for c in cols:
        try:
            db.execute(f"UPDATE {t} SET {c}=replace({c}, ?, ?) WHERE {c} LIKE ?", (linux, win, f"%{linux}%"))
        except sqlite3.DatabaseError as e:
            print(f"{t}.{c}: {e}")
db.commit()
p = os.path.join(copy, "gui.json")
text = open(p).read().replace(linux, win)
open(p, "w").write(text)
PY
    (cd "$W" && rm -f tour-data.zip && python3 -c "import shutil; shutil.make_archive('tour-data', 'zip', '.', 'tour-data')")
    run "Remove-Item -Recurse -Force $D/tour-data, C:/shots/appkata -ErrorAction SilentlyContinue"
    $SCP "$W/tour-data.zip" "$R:$D/"
    run "Expand-Archive -Force $D/tour-data.zip $D"
    ARGS=""; [ -n "$ONLY" ] && ARGS=",'--tour-only','$ONLY'"
    # the tour saves DIR/dark and DIR/light itself. It runs in the signed-in console session, as a
    # user would: the SSH session (session 0) has no real display, and dialogs land off-centre there.
    # The screen is 1920 x 1080 while it runs, the design point (requirement 5.2.1), and the tour's
    # window takes what the taskbar leaves, as maximized. The screens show a neutral account's
    # folders, C:\Users\you, as the mockups do, not the VM's account: the tour gets that profile,
    # made for the run and removed after (a shared VM is left as it was found, coworker/vm).
    $SCP "$HERE/scripts/windows-display.ps1" "$R:$D/windows-display.ps1"
    YOU='C:\Users\you'
    run "New-Item -ItemType Directory -Force '$YOU\AppData\Local', '$YOU\AppData\Roaming' | Out-Null
         icacls '$YOU' /grant '${VM_SSH_USER}:(OI)(CI)M' /T /Q | Out-Null"
    limited ". $D/windows-display.ps1
         'display: {0}' -f (Set-Display 1920 1080)
         Move-PointerAway
         \$exe = \"$APP\\appkata.exe\"
         \$env:APPKATA_DATA = '$D/tour-data'
         \$env:USERPROFILE = '$YOU'; \$env:LOCALAPPDATA = '$YOU\AppData\Local'; \$env:APPDATA = '$YOU\AppData\Roaming'
         \$p = Start-Process -Wait -PassThru \$exe -ArgumentList '--tour','C:\\shots\\appkata'$ARGS
         'tour: exit {0}, {1} screens' -f \$p.ExitCode, (Get-ChildItem -Recurse -Filter *.png C:\\shots\\appkata -ErrorAction SilentlyContinue).Count
         'display reset: {0}' -f (Reset-Display)" 600
    OUT=$(run "Get-Content $D/limited-out.txt")
    echo "$OUT"
    # the tour checks each screen's layout (src/appkata/layout.py) and lists what runs past its box
    run "if (Test-Path C:/shots/appkata/layout.txt) { Get-Content C:/shots/appkata/layout.txt }"
    run "Remove-Item -Recurse -Force '$YOU' -ErrorAction SilentlyContinue"
    mkdir -p "$HERE/screenshots/windows"
    [ -n "$ONLY" ] || rm -rf "$HERE/screenshots/windows/dark" "$HERE/screenshots/windows/light"
    rm -rf "$W/shots"; mkdir -p "$W/shots"
    $SCP -r "$R:C:/shots/appkata/dark" "$R:C:/shots/appkata/light" "$W/shots/"
    for t in dark light; do
        mkdir -p "$HERE/screenshots/windows/$t"
        cp "$W/shots/$t"/*.png "$HERE/screenshots/windows/$t/"
    done
    echo "saved screenshots/windows/{dark,light}"
    SIZE=$(python3 -c "import struct, sys; d = open(sys.argv[1], 'rb').read(24); print('%dx%d' % struct.unpack('>II', d[16:24]))" \
           "$(ls "$HERE"/screenshots/windows/dark/*.png | head -1)")
    echo "screens: $SIZE"
    TOUR=$OUT                              # judged after the uninstall, so a failing tour still cleans up
    # ------------------------------------------------------------------ end of screenshots
fi

echo "== uninstall"
OUT=$(run "\$u = Get-ItemProperty '$UNINST'
     \$exe = (\$u.UninstallString -replace '\"','')
     \$p = Start-Process -Wait -PassThru \$exe -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'
     for (\$i = 0; \$i -lt 60 -and (Test-Path \"$APP\\appkata.exe\"); \$i++) { Start-Sleep 1 }
     'uninstall exit: ' + \$p.ExitCode
     'exe gone: ' + -not (Test-Path \"$APP\\appkata.exe\")
     'entry gone: ' + -not (Test-Path '$UNINST')
     'link handler gone: ' + -not (Test-Path 'HKCU:\Software\Classes\appkata')
     'shortcut gone: ' + -not (Test-Path \"\$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\AppKata.lnk\")")
echo "$OUT"
expect "$OUT" "uninstall exit: 0"
expect "$OUT" "exe gone: True"
expect "$OUT" "entry gone: True"
expect "$OUT" "link handler gone: True"
expect "$OUT" "shortcut gone: True"
[ -z "${TOUR:-}" ] || { expect "$TOUR" "display: 0"; expect "$TOUR" "tour: exit 0"; expect "$SIZE" "1920x1040"; }
echo "PASS"
