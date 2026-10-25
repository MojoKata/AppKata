#!/bin/bash
# mac-sign.sh: finish AppKata's macOS release on a Mac.
#
# The Linux build assembles AppKata.app (Intel + Apple silicon) but can't sign it. This
# script, run on any Mac with macOS 12 or newer (an Intel Mac is fine):
#   1. checks everything it needs before touching anything,
#   2. signs the app from the inside out with your Developer ID and the hardened runtime,
#   3. notarizes the app with Apple and staples the ticket to it,
#   4. builds AppKata-<version>.dmg, signs, notarizes and staples that too,
#   5. checks the result the way Gatekeeper will, and writes a .sha256.
#
# Usage (from the unpacked hand-off folder, next to AppKata.app):
#   ./mac-sign.sh --check                 checks only; changes nothing, needs no certificate
#   ./mac-sign.sh --profile appkata-notary
#   ./mac-sign.sh --no-notarize           sign and build the .dmg without contacting Apple
#
# Options:
#   --identity "Developer ID Application: Name (TEAMID)"   which certificate (if you have several)
#   --profile NAME     notarytool keychain profile (see SETUP below)
#   --out DIR          where to write the .dmg, .sha256 and log (default: next to this script)
#   --yes              don't stop to confirm before signing
#   -h, --help         this text
# Environment: SIGN_IDENTITY, NOTARY_PROFILE, or NOTARY_KEY + NOTARY_KEY_ID + NOTARY_ISSUER
# (an App Store Connect API key) instead of --profile; REQUIRE_ARCHS (default "x86_64 arm64").
#
# SETUP (once per Mac):
#   1. xcode-select --install                      (the Command Line Tools: codesign, notarytool)
#   2. Import your "Developer ID Application" certificate with its private key (a .p12) into
#      the login keychain: double-click it, or  security import cert.p12 -k login.keychain-db
#   3. xcrun notarytool store-credentials appkata-notary \
#          --apple-id you@example.com --team-id TEAMID     (asks for an app-specific password
#      from appleid.apple.com → Sign-In and Security → App-Specific Passwords)
#
# Everything this script prints is also saved to mac-sign-<date>.log. If something fails,
# the message says what to do; send the log along if you need help.
#
# Written for the bash 3.2 that ships with macOS.
set -Eeuo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
APP="$HERE/AppKata.app"
ENT="$HERE/entitlements.plist"
IDENTITY="${SIGN_IDENTITY:-}"
PROFILE="${NOTARY_PROFILE:-}"
REQUIRE_ARCHS="${REQUIRE_ARCHS:-x86_64 arm64}"
NOTARIZE=1
CHECK_ONLY=0
ASSUME_YES=0
OUT_DIR="$HERE"
MIN_MACOS=12

usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
    case "$1" in
        --identity) [ $# -ge 2 ] || usage 2; IDENTITY="$2"; shift 2 ;;
        --profile) [ $# -ge 2 ] || usage 2; PROFILE="$2"; shift 2 ;;
        --out) [ $# -ge 2 ] || usage 2; OUT_DIR="$2"; shift 2 ;;
        --no-notarize) NOTARIZE=0; shift ;;
        --check) CHECK_ONLY=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1  (try --help)" >&2; exit 2 ;;
    esac
done

# ---------------------------------------------------------------- output, logging, errors
if [ -t 1 ]; then B=$'\033[1m'; R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; N=$'\033[0m'; else B= R= G= Y= N=; fi
STEP=0
step() { STEP=$((STEP + 1)); printf '\n%s[%d] %s%s\n' "$B" "$STEP" "$*" "$N"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
# fail "what went wrong" "what to do" ["more detail"]
HANDLED=
fail() {
    HANDLED=1
    printf '\n%s✗ %s%s\n' "$R" "$1" "$N" >&2
    [ -n "${3:-}" ] && printf '%s\n' "$3" | sed 's/^/    /' >&2
    [ -n "${2:-}" ] && printf '\n  %sWhat to do:%s %s\n' "$B" "$N" "$2" >&2
    [ -n "${LOG:-}" ] && printf '\n  Full log: %s\n' "$LOG" >&2
    exit 1
}
# Anything that fails without going through fail() is reported on exit, with where it happened.
ERR_AT=
trap 'ERR_AT="line $LINENO: $BASH_COMMAND"' ERR
WORK=
on_exit() {
    rc=$?
    [ -n "$WORK" ] && rm -rf "$WORK"
    if [ "$rc" -ne 0 ] && [ -z "$HANDLED" ]; then
        printf '\n%s✗ Unexpected failure%s%s\n' "$R" "$N" "${ERR_AT:+ at $ERR_AT}" >&2
        printf '\n  %sWhat to do:%s Nothing was published. Fix the cause shown above, if any, and run the script again; it starts over safely. If the cause is unclear, send the log to the developers.\n' "$B" "$N" >&2
        [ -n "${LOG:-}" ] && printf '\n  Full log: %s\n' "$LOG" >&2
    fi
}
trap on_exit EXIT

mkdir -p "$OUT_DIR" 2>/dev/null || { echo "Can't create the output folder: $OUT_DIR" >&2; exit 1; }
OUT_DIR=$(cd "$OUT_DIR" && pwd)
[ -w "$OUT_DIR" ] || { echo "The output folder isn't writable: $OUT_DIR" >&2; exit 1; }
LOG="$OUT_DIR/mac-sign-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
WORK=$(mktemp -d "${TMPDIR:-/tmp}/appkata-sign.XXXXXX")

printf '%sAppKata macOS signing%s  ·  %s  ·  log: %s\n' "$B" "$N" "$(date)" "$LOG"

# ---------------------------------------------------------------- 1. this Mac
step "Checking this Mac"
[ "$(uname -s)" = Darwin ] || fail "This isn't a Mac." "Copy the hand-off tarball to a Mac and run the script there."
OSV=$(sw_vers -productVersion)
[ "${OSV%%.*}" -ge "$MIN_MACOS" ] 2>/dev/null ||
    fail "macOS $OSV is too old; notarization needs macOS $MIN_MACOS or newer." "Run this on a Mac with macOS $MIN_MACOS+."
ok "macOS $OSV on $(uname -m)"
xcode-select -p >/dev/null 2>&1 ||
    fail "The Xcode Command Line Tools aren't installed." "Run:  xcode-select --install   then run this script again."
PLISTBUDDY=${PLISTBUDDY:-/usr/libexec/PlistBuddy}
for t in codesign security xattr lipo file hdiutil ditto shasum plutil spctl "$PLISTBUDDY"; do
    command -v "$t" >/dev/null 2>&1 || [ -x "$t" ] ||
        fail "A required tool is missing: $t" "Reinstall the Command Line Tools:  sudo rm -rf /Library/Developer/CommandLineTools && xcode-select --install"
done
if [ "$NOTARIZE" = 1 ] || [ "$CHECK_ONLY" = 1 ]; then
    for t in notarytool stapler; do
        xcrun --find "$t" >/dev/null 2>&1 ||
            fail "xcrun can't find $t." "Update the Command Line Tools (Software Update, or xcode-select --install). notarytool needs Xcode 13 tools or newer."
    done
fi
ok "Command Line Tools at $(xcode-select -p)"

# ---------------------------------------------------------------- 2. the hand-off folder
step "Checking the hand-off folder"
[ -d "$APP" ] || fail "AppKata.app isn't next to this script ($HERE)." \
    "Unpack the whole tarball and run the script from inside the folder it creates:  tar -xzf AppKata-*-macos-unsigned.tar.gz && cd AppKata-*-macos"
[ -f "$ENT" ] || fail "entitlements.plist isn't next to this script." "Unpack the tarball again; don't copy files out of it one by one."
plutil -lint -s "$ENT" || fail "entitlements.plist isn't a valid property list." "Unpack the tarball again."
# the tarball's own checksum, if it's next to the folder
for sum in "$HERE"/../AppKata-*-macos-unsigned.tar.gz.sha256; do
    [ -f "$sum" ] || continue
    (cd "$(dirname "$sum")" && shasum -a 256 -c "$(basename "$sum")" >/dev/null 2>&1) ||
        fail "The tarball doesn't match its checksum ($(basename "$sum"))." "Copy the .tar.gz to this Mac again; the copy is damaged or incomplete."
    ok "Tarball checksum matches"
done
PL="$APP/Contents/Info.plist"
[ -f "$PL" ] || fail "AppKata.app has no Contents/Info.plist." "The build is incomplete; ask for a new hand-off tarball."
plutil -lint -s "$PL" || fail "AppKata.app's Info.plist isn't valid." "Ask for a new hand-off tarball."
plist() { "$PLISTBUDDY" -c "Print :$1" "$PL" 2>/dev/null; }
VERSION=$(plist CFBundleShortVersionString) || fail "Info.plist has no CFBundleShortVersionString." "Ask for a new hand-off tarball."
BUNDLE_ID=$(plist CFBundleIdentifier) || fail "Info.plist has no CFBundleIdentifier." "Ask for a new hand-off tarball."
EXE_NAME=$(plist CFBundleExecutable) || fail "Info.plist has no CFBundleExecutable." "Ask for a new hand-off tarball."
MAIN_EXE="$APP/Contents/MacOS/$EXE_NAME"
[ -f "$MAIN_EXE" ] && [ -x "$MAIN_EXE" ] || fail "The main executable is missing or not executable: Contents/MacOS/$EXE_NAME" \
    "Unpack with tar (not Archive Utility from a re-zipped copy), which keeps the executable bits."
file -b "$MAIN_EXE" | grep -q '^Mach-O' || fail "Contents/MacOS/$EXE_NAME isn't a Mach-O binary." \
    "Notarization requires a compiled launcher, not a script. This is a build problem; ask for a new hand-off tarball."
ok "AppKata $VERSION ($BUNDLE_ID)"

# Broken symlinks mean the copy lost them (scp -r, some zip tools, shared folders).
BROKEN=$(find "$APP" -type l ! -exec test -e {} \; -print)
[ -z "$BROKEN" ] || fail "Some symlinks inside AppKata.app are broken." \
    "Copy the .tar.gz file itself to this Mac (not the unpacked folder), then unpack it here with tar." "$BROKEN"
# codesign treats everything in Contents/MacOS as code: data files there break signing
: > "$WORK/macho"; : > "$WORK/exes"; : > "$WORK/notcode"
find "$APP" -type f \( -perm -u+x -o -name '*.so' -o -name '*.dylib' -o -path '*/Contents/MacOS/*' \) -print > "$WORK/candidates"
while IFS= read -r f; do
    kind=$(file -b "$f")
    case "$kind" in
        Mach-O*) echo "$f" >> "$WORK/macho"; case "$kind" in *executable*) echo "$f" >> "$WORK/exes" ;; esac ;;
        *) case "$f" in */Contents/MacOS/*) echo "${f#$APP/}" >> "$WORK/notcode" ;; esac ;;
    esac
done < "$WORK/candidates"
if [ -s "$WORK/notcode" ]; then fail "Contents/MacOS contains files that aren't code; codesign rejects that." \
    "This is a build problem (those files belong in Contents/Resources); ask for a new hand-off tarball." "$(cat "$WORK/notcode")"; fi
[ -s "$WORK/macho" ] || fail "No compiled code found in AppKata.app." "Ask for a new hand-off tarball."
NMACHO=$(wc -l < "$WORK/macho" | tr -d ' ')
ok "$NMACHO binaries found ($(wc -l < "$WORK/exes" | tr -d ' ') executables), no broken symlinks"

# Every binary must carry both architectures: signing can't add a missing one.
: > "$WORK/missing"
while IFS= read -r f; do
    archs=" $(lipo -archs "$f" 2>/dev/null || true) "
    for a in $REQUIRE_ARCHS; do
        case "$archs" in *" $a "*) ;; *) echo "${f#$APP/}: has$archs needs $a" >> "$WORK/missing" ;; esac
    done
done < "$WORK/macho"
if [ -s "$WORK/missing" ]; then fail "Some binaries don't contain every required architecture ($REQUIRE_ARCHS)." \
    "This is a build problem; ask for a new hand-off tarball and mention this list." "$(head -20 "$WORK/missing")"; fi
ok "Every binary contains: $REQUIRE_ARCHS"
if find "$APP" -name '*.pyc' -newer "$PL" | grep -q .; then
    warn "Python bytecode files are newer than the build. Has the app been run from this folder?"
    info "Running it before signing is fine, but any file Python writes after signing breaks the signature."
fi

# Space: the app is copied for the .dmg and zipped for notarization
NEED_KB=$(( $(du -sk "$APP" | cut -f1) * 3 ))
FREE_KB=$(df -k "$OUT_DIR" | awk 'NR == 2 { print $4 }')
[ "$FREE_KB" -gt "$NEED_KB" ] || fail "Not enough free disk space: need about $((NEED_KB / 1024)) MB, have $((FREE_KB / 1024)) MB." "Free some space, or pass --out to a disk with more room."
ok "Enough free space ($((FREE_KB / 1024)) MB)"

# ---------------------------------------------------------------- 3. certificate
step "Checking the signing certificate"
VALID=$(security find-identity -v -p codesigning 2>/dev/null | sed -n 's/^ *[0-9][0-9]*) [0-9A-F]\{40\} "\(Developer ID Application: .*\)"$/\1/p' | sort -u)
ALL=$(security find-identity -p codesigning 2>/dev/null | sed -n 's/^ *[0-9][0-9]*) [0-9A-F]\{40\} "\(Developer ID Application: .*\)".*$/\1/p' | sort -u)
if [ -z "$IDENTITY" ]; then
    n=$(printf '%s\n' "$VALID" | grep -c . || true)
    if [ "$n" = 0 ]; then
        if [ -n "$ALL" ]; then
            fail "A Developer ID Application certificate is in the keychain, but macOS says it isn't valid." \
                "Usually the Apple intermediate certificate is missing: download 'Developer ID - G2' from https://www.apple.com/certificateauthority/ and double-click it. Also check the certificate hasn't expired (Keychain Access → My Certificates)." "$ALL"
        fi
        if [ "$CHECK_ONLY" = 1 ]; then
            warn "No Developer ID Application certificate yet (needed before signing; see SETUP in --help)."
        else
            fail "No Developer ID Application certificate with a private key was found." \
                "Import the .p12 file (certificate + private key) into the login keychain; see SETUP in  ./mac-sign.sh --help. An 'Apple Development' or 'Mac App Distribution' certificate won't do."
        fi
    elif [ "$n" -gt 1 ]; then
        fail "Several Developer ID Application certificates were found." "Choose one:  ./mac-sign.sh --identity \"Developer ID Application: …\"" "$VALID"
    else
        IDENTITY="$VALID"
    fi
else
    printf '%s\n' "$VALID" | grep -qxF "$IDENTITY" ||
        fail "The certificate \"$IDENTITY\" isn't a valid signing identity in the keychain." "Use one of these exactly as shown, or import the right .p12:" "${VALID:-(none)}"
fi
if [ -n "$IDENTITY" ]; then
    TEAM=$(printf '%s' "$IDENTITY" | sed -n 's/.*(\([A-Z0-9]\{10\}\))$/\1/p')
    ok "Certificate: $IDENTITY"
    # A trial signature catches a locked keychain, a missing private key and an unreachable
    # timestamp server now rather than halfway through.
    info "Trial signature (macOS may ask to allow codesign to use the key: enter your login password and click Always Allow)…"
    cp /usr/bin/true "$WORK/trial"
    out=$(codesign --force --timestamp --options runtime --sign "$IDENTITY" "$WORK/trial" 2>&1) ||
        fail "The trial signature failed." \
            "If it mentions the timestamp service, check the internet connection (timestamp.apple.com). If it says errSecInternalComponent or 'unable to build chain', unlock the login keychain (security unlock-keychain login.keychain-db) and install the 'Developer ID - G2' intermediate certificate." "$out"
    ok "Trial signature with a secure timestamp works"
fi

# ---------------------------------------------------------------- 4. notarization credentials
NOTARY_AUTH=()
if [ "$NOTARIZE" = 1 ]; then
    step "Checking the notarization credentials"
    if [ -n "$PROFILE" ]; then
        NOTARY_AUTH=(--keychain-profile "$PROFILE")
    elif [ -n "${NOTARY_KEY:-}" ] || [ -n "${NOTARY_KEY_ID:-}" ] || [ -n "${NOTARY_ISSUER:-}" ]; then
        [ -f "${NOTARY_KEY:-/nonexistent}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER:-}" ] ||
            fail "The API key settings are incomplete." "Set all three: NOTARY_KEY (path to the AuthKey_….p8 file), NOTARY_KEY_ID and NOTARY_ISSUER."
        NOTARY_AUTH=(--key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER")
    elif [ "$CHECK_ONLY" = 1 ]; then
        warn "No notarization credentials given (pass --profile NAME to check them too)."
    else
        fail "No notarization credentials were given." \
            "Create a keychain profile once (SETUP step 3 in --help), then run:  ./mac-sign.sh --profile appkata-notary   (or use --no-notarize for a local test build)."
    fi
    if [ ${#NOTARY_AUTH[@]} -gt 0 ]; then
        out=$(xcrun notarytool history "${NOTARY_AUTH[@]}" 2>&1) ||
            fail "Apple's notary service rejected the credentials or couldn't be reached." \
                "Check the internet connection. For a profile, re-create it with  xcrun notarytool store-credentials $PROFILE … ; an app-specific password stops working if you change your Apple ID password. Also accept any new agreements at developer.apple.com." "$(printf '%s\n' "$out" | tail -5)"
        ok "Notary credentials work"
    fi
fi

if [ "$CHECK_ONLY" = 1 ]; then
    printf '\n%sAll checks passed.%s Nothing was changed.\n' "$G" "$N"
    if [ -z "$IDENTITY" ]; then info "Still needed before signing: a Developer ID Application certificate."; fi
    exit 0
fi

# ---------------------------------------------------------------- confirm
printf '\n%sReady.%s This will:\n' "$B" "$N"
info "• sign AppKata.app ($NMACHO binaries) as: $IDENTITY"
if [ "$NOTARIZE" = 1 ]; then
    info "• upload the app, then the .dmg, to Apple's notary service (usually 1–10 minutes each) and staple the tickets"
else
    info "• NOT notarize (--no-notarize): the .dmg will only open on this Mac or with right-click → Open"
fi
info "• write $OUT_DIR/AppKata-$VERSION.dmg and its .sha256"
if [ "$ASSUME_YES" = 0 ]; then
    if [ -t 0 ]; then
        printf '\n  Continue? [y/N] '; read -r answer
        case "$answer" in y|Y|yes|YES) ;; *) echo "  Stopped. Nothing was changed."; exit 0 ;; esac
    else
        fail "Not running in a terminal, so I can't ask for confirmation." "Run it in Terminal, or add --yes."
    fi
fi

# ---------------------------------------------------------------- 5. sign
step "Signing AppKata.app"
xattr -cr "$APP"
sign() { codesign --force --timestamp --options runtime --sign "$IDENTITY" "$@"; }
depth_sort() { awk -F/ '{ print NF "\t" $0 }' | sort -rn -k1,1 | cut -f2-; }
sign_one() {    # path [entitlements…]
    local f="$1"; shift
    out=$(sign "$@" "$f" 2>&1) || fail "Signing failed for ${f#$APP/}" \
        "If the message mentions the timestamp service, check the connection and run again. Otherwise send the log to the developers." "$out"
}
# libraries and plug-ins first, deepest first (entitlements don't apply to libraries)
grep -vxF -f "$WORK/exes" "$WORK/macho" | depth_sort > "$WORK/libs" || true
i=0; total=$(wc -l < "$WORK/libs" | tr -d ' ')
while IFS= read -r f; do
    sign_one "$f"; i=$((i + 1))
    if [ $((i % 50)) = 0 ]; then info "$i / $total libraries…"; fi
done < "$WORK/libs"
ok "Signed $total libraries"
# framework bundles, deepest first, now that their binaries are signed
find "$APP" -type d -name '*.framework' | depth_sort > "$WORK/frameworks" || true
while IFS= read -r fw; do sign_one "$fw"; done < "$WORK/frameworks"
ok "Signed $(wc -l < "$WORK/frameworks" | tr -d ' ') framework(s)"
# helper executables (the Python interpreter etc.), with the entitlements
{ grep -vxF "$MAIN_EXE" "$WORK/exes" || true; } | depth_sort > "$WORK/helpers"
while IFS= read -r f; do sign_one "$f" --entitlements "$ENT"; done < "$WORK/helpers"
# the app itself, which signs the main executable
sign_one "$APP" --entitlements "$ENT"
ok "Signed the app"

# what notarization will insist on: valid signatures, hardened runtime, timestamps, one team
out=$(codesign --verify --deep --strict --verbose=2 "$APP" 2>&1) ||
    fail "The signed app doesn't verify." "Send the log to the developers." "$out"
: > "$WORK/badsig"
while IFS= read -r f; do
    d=$(codesign -dvv "$f" 2>&1 || true)
    printf '%s' "$d" | grep -q 'Timestamp=' || echo "${f#$APP/}: no secure timestamp" >> "$WORK/badsig"
    if [ -n "${TEAM:-}" ]; then printf '%s' "$d" | grep -q "TeamIdentifier=$TEAM" || echo "${f#$APP/}: not signed by team $TEAM" >> "$WORK/badsig"; fi
done < "$WORK/macho"
while IFS= read -r f; do
    codesign -dvv "$f" 2>&1 | grep -q 'flags=.*runtime' || echo "${f#$APP/}: no hardened runtime" >> "$WORK/badsig"
done < "$WORK/exes"
if [ -s "$WORK/badsig" ]; then fail "Some binaries aren't signed the way notarization requires." "Run the script again; if it repeats, send the log." "$(head -20 "$WORK/badsig")"; fi
ok "Signatures verify: hardened runtime, secure timestamps${TEAM:+, team $TEAM}"

# ---------------------------------------------------------------- 6. notarize
notarize() {    # file label
    local log="$WORK/notary-$2.log" id status
    info "Uploading $(basename "$1") ($(du -h "$1" | cut -f1 | tr -d ' ')) to Apple and waiting for the result…"
    xcrun notarytool submit "$1" "${NOTARY_AUTH[@]}" --wait --timeout 45m > "$log" 2>&1 || true
    sed 's/^/    /' "$log"
    id=$(awk '/^ *id:/ { print $2; exit }' "$log")
    status=$(awk '/^ *status:/ { s = $2 } END { print s }' "$log")
    if [ "$status" != Accepted ]; then
        local detail=""
        if [ -n "$id" ] && xcrun notarytool log "$id" "${NOTARY_AUTH[@]}" "$OUT_DIR/notary-$2-$id.json" >/dev/null 2>&1; then
            detail="Apple's report: $OUT_DIR/notary-$2-$id.json"
            detail="$detail
$(grep -E '"(path|message)"' "$OUT_DIR/notary-$2-$id.json" | head -20 | sed 's/^ *//')"
        fi
        case "$status" in
            Invalid) fail "Apple rejected the $2 (status: Invalid)." "The report lists each problem with a path. Send it and the log to the developers; this needs a build fix." "$detail" ;;
            "") fail "The upload to Apple didn't finish." "Check the internet connection and run the script again (it starts over safely)." "$detail" ;;
            *) fail "Notarization of the $2 ended with status: $status." \
                   "If it's still In Progress, wait and check with:  xcrun notarytool info $id ${NOTARY_AUTH[*]}  then run the script again." "$detail" ;;
        esac
    fi
    ok "Apple accepted the $2 (submission $id)"
}
if [ "$NOTARIZE" = 1 ]; then
    # the app gets its own ticket so it still opens offline after being copied out of the .dmg
    step "Notarizing the app"
    ditto -c -k --keepParent "$APP" "$WORK/AppKata.zip"
    notarize "$WORK/AppKata.zip" app
    out=$(xcrun stapler staple "$APP" 2>&1) || fail "Stapling the ticket to the app failed." "Wait a minute (Apple's CDN can lag) and run the script again." "$out"
    ok "Ticket stapled to the app"
fi

# ---------------------------------------------------------------- 7. disk image
step "Building the disk image"
DMG="$OUT_DIR/AppKata-$VERSION.dmg"
STAGE="$WORK/dmg"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/AppKata.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG" "$DMG.sha256"
out=$(hdiutil create -volname "AppKata $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG" 2>&1) ||
    fail "hdiutil couldn't create the disk image." "Close any open 'AppKata' disk images in Finder and run again." "$out"
sign_one "$DMG"
ok "$(basename "$DMG") created and signed ($(du -h "$DMG" | cut -f1 | tr -d ' '))"
if [ "$NOTARIZE" = 1 ]; then
    step "Notarizing the disk image"
    notarize "$DMG" "disk image"
    out=$(xcrun stapler staple "$DMG" 2>&1) || fail "Stapling the ticket to the disk image failed." "Wait a minute and run the script again." "$out"
    ok "Ticket stapled to the disk image"
fi

# ---------------------------------------------------------------- 8. final checks
step "Checking the result as Gatekeeper will"
if [ "$NOTARIZE" = 1 ]; then
    out=$(spctl --assess --type exec -vv "$APP" 2>&1) || fail "Gatekeeper rejects the app." "Send the log to the developers." "$out"
    printf '%s' "$out" | grep -q 'Notarized Developer ID' || fail "Gatekeeper accepts the app, but not as notarized." "Send the log to the developers." "$out"
    ok "App: accepted (Notarized Developer ID)"
    out=$(spctl --assess --type open --context context:primary-signature -vv "$DMG" 2>&1) || fail "Gatekeeper rejects the disk image." "Send the log to the developers." "$out"
    ok "Disk image: accepted"
    xcrun stapler validate "$DMG" >/dev/null 2>&1 || fail "The disk image's stapled ticket doesn't validate." "Run the script again."
    ok "Stapled tickets validate"
else
    warn "Skipped (--no-notarize): Gatekeeper rejects Developer ID apps that aren't notarized."
fi
(cd "$OUT_DIR" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")

printf '\n%sDone.%s\n' "$G" "$N"
info "$DMG"
info "$DMG.sha256"
if [ "$NOTARIZE" = 1 ]; then info "Next: attach both files to the release. Opening the .dmg on another Mac is a good final check."
else info "This build isn't notarized: use it for local testing only."; fi
