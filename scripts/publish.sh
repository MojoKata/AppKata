#!/bin/sh
# The owner's steps for AppKata's release key and releases, as commands (GENESIS.md says when each
# is run; docs/github-workflows.md how CI builds, signs and drafts a release). Needs git, gpg 2.2+
# and gh, logged in as an admin of the repository for setup, check, release, publish and
# field-test, and python3 for field-test.
#
#   The release key, on your own machine. DIR is the key's home: keep it offline (a USB stick)
#   and plug it in for key-github and key-extend.
#     key-new DIR 'NAME <EMAIL>'  make it: an ed25519 main key that only certifies (5 years) and an
#                                 ed25519 signing subkey (2 years); writes DIR/gnupg, the public key,
#                                 the fingerprint and a revocation certificate
#     key-github DIR              give CI the signing subkey: the release environment's two secrets,
#                                 the subkey alone under a random passphrase of its own
#     key-export DIR              write packaging/appkata-release-key.asc (commit it) and send the
#                                 key to keys.openpgp.org
#     key-extend DIR              move both expiry dates on (5 and 2 years from today) and export
#                                 the key again; then key-github
#   The repository's settings:
#     setup                       the release environment, the tag ruleset, immutable releases,
#                                 actions pinned by SHA, the field-test label and, once CI has
#                                 passed, the required ci check: each only if missing
#     check                       read back every setting GENESIS.md lists
#   A release, from a clone of the repository on master:
#     release                     tag v<version>, push it, wait for CI, show the files' SHA-256s,
#                                 approve the signing, then check the draft (verify)
#     resume [VERSION]            the same from "wait for CI", for a tag already pushed (after an
#                                 interruption)
#     verify [VERSION]            download a release or its draft and check it: the files, their
#                                 .sha256s, the signature and its key's fingerprint
#     publish [VERSION]           verify the draft again and publish it
#     field-test [VERSION]        open the release's field-test issue and, under it, one for each
#                                 environment with its checklist (docs/testing.md, "Tracking the
#                                 runs on GitHub")
#
# Options: --repo OWNER/NAME (the default is APPKATA_REPO's, src/appkata_core/__init__.py: another
# repository, a fork, to try these); --key FILE (the public key verify trusts; the default is
# packaging/appkata-release-key.asc); --yes (no questions: for trying it out).
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(sed -n 's#^APPKATA_REPO = "https://github.com/\(.*\)"#\1#p' "$HERE/src/appkata_core/__init__.py")
KEY="$HERE/packaging/appkata-release-key.asc"
YES=
while [ $# -gt 0 ]; do
    case $1 in
        --repo) REPO=$2; shift 2 ;;
        --key) KEY=$2; shift 2 ;;
        --yes) YES=1; shift ;;
        *) break ;;
    esac
done
[ $# -gt 0 ] || { sed -n '2,/^set -eu/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; exit 2; }
CMD=$1; shift
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$HERE/src/appkata_core/__init__.py")

say() { printf '%s\n' "$*" >&2; }
die() { say "publish.sh: $*"; exit 1; }
ask() {      # QUESTION: go on only on y
    [ -z "$YES" ] || return 0
    printf '%s [y/N] ' "$1" >&2
    read -r a </dev/tty
    case $a in y|Y|yes) ;; *) die "stopped" ;; esac
}
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
tmpdir() { mktemp -d "${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/appkata-publish.XXXXXX"; }
CLEAN=
cleanup() {
    for d in $CLEAN; do
        [ -d "$d" ] || continue
        GNUPGHOME=$d gpgconf --kill all 2>/dev/null || true
        rm -rf "$d"
    done
}
trap cleanup EXIT INT TERM

# --- the release key -----------------------------------------------------------------------------

keyhome() {      # DIR: GNUPGHOME and FPR, the main key's fingerprint
    [ -f "$1/fingerprint" ] && [ -d "$1/gnupg" ] || die "$1 holds no release key (key-new makes one)"
    GNUPGHOME=$1/gnupg FPR=$(cat "$1/fingerprint")
    export GNUPGHOME
}
signing_subkey() {     # [any]: the newest signing subkey's fingerprint, valid only unless "any"
    gpg --batch --list-keys --with-colons "$FPR" | awk -F: -v any="${1:-}" '
        $1 == "sub" { s = ($12 ~ /s/ && $2 != "r" && (any != "" || $2 !~ /[eni]/)) ? $6 : "" }
        $1 == "fpr" && s != "" { if (s + 0 > best + 0) { best = s; fpr = $10 }; s = "" }
        END { print fpr }'
}
loopback() {     # gpg's options to take the passphrase from APPKATA_KEY_PASSPHRASE_FILE (for trying it)
    [ -z "${APPKATA_KEY_PASSPHRASE_FILE:-}" ] || echo "--pinentry-mode loopback --passphrase-file $APPKATA_KEY_PASSPHRASE_FILE"
}
export_public() {
    gpg --batch --armor --export "$FPR" > "$DIR/appkata-release-key.asc"
    cp "$DIR/appkata-release-key.asc" "$HERE/packaging/appkata-release-key.asc"
}

key_new() {
    DIR=$1 UID_=$2
    [ ! -e "$DIR/gnupg" ] || die "$DIR/gnupg exists: a key is there already"
    mkdir -p "$DIR/gnupg" && chmod 700 "$DIR" "$DIR/gnupg"
    GNUPGHOME=$DIR/gnupg
    export GNUPGHOME
    say "== the main key (gpg asks for its passphrase: keep it with the key, never in GitHub)"
    # shellcheck disable=SC2046
    gpg --batch $(loopback) --quick-gen-key "$UID_" ed25519 cert 5y
    FPR=$(gpg --batch --list-keys --with-colons "$UID_" | awk -F: '$1 == "fpr" { print $10; exit }')
    [ -n "$FPR" ] || die "gpg made no key"
    echo "$FPR" > "$DIR/fingerprint"
    say "== the signing subkey"
    # shellcheck disable=SC2046
    gpg --batch $(loopback) --quick-add-key "$FPR" ed25519 sign 2y
    cp "$DIR/gnupg/openpgp-revocs.d/$FPR.rev" "$DIR/revocation.asc"
    gpg --batch --armor --export "$FPR" > "$DIR/appkata-release-key.asc"
    gpg --batch --list-keys "$FPR" >&2
    say "Made the release key $FPR in $DIR."
    say "Next: copy $DIR to the offline place you keep it, then key-github $DIR and key-export $DIR."
}

key_github() {
    DIR=$1
    keyhome "$DIR"
    SUB=$(signing_subkey)
    [ -n "$SUB" ] || die "the key has no valid signing subkey (key-extend moves its expiry on)"
    gh api "repos/$REPO/environments/release" >/dev/null 2>&1 || die "$REPO has no release environment: run setup first"
    T=$(tmpdir); CLEAN="$CLEAN $T"
    (cd "$DIR/gnupg" && tar cf - --exclude 'S.*' --exclude gpg-agent.conf .) | (cd "$T" && tar xf -)
    # A throwaway copy of the keyring, whose agent asks this pinentry: the main key's passphrase to
    # unlock it, and the new one, made here, for the copy CI gets. Both are files in a 0700 folder,
    # removed when this ends; DIR keeps the passphrase it had.
    cat > "$T/pinentry" <<'EOF'
#!/bin/sh
d=${0%/*}
echo OK
while IFS= read -r line; do
    case $line in
        SETDESC*) desc=$line; echo OK ;;
        SETREPEAT*) repeat=1; echo OK ;;
        GETPIN*) case $desc in *unlock*) f=old ;; *) f=new ;; esac
                 [ -z "$repeat" ] || echo "S PIN_REPEATED"
                 printf 'D %s\nOK\n' "$(sed -e 's/%/%25/g' "$d/.$f")" ;;
        BYE*) echo OK; exit 0 ;;
        *) echo OK ;;
    esac
done
EOF
    chmod 700 "$T/pinentry" && echo "pinentry-program $T/pinentry" > "$T/gpg-agent.conf"
    ( umask 077
      if [ -n "${APPKATA_KEY_PASSPHRASE_FILE:-}" ]; then tr -d '\n' < "$APPKATA_KEY_PASSPHRASE_FILE" > "$T/.old"
      else
          printf 'The main key'"'"'s passphrase: ' >&2
          stty -echo </dev/tty; IFS= read -r p </dev/tty; stty echo </dev/tty; echo >&2
          printf '%s' "$p" > "$T/.old"
      fi
      head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-40 > "$T/.new" )
    GNUPGHOME=$T gpg --batch --passwd "$FPR" </dev/null || die "gpg didn't take the passphrase"
    GNUPGHOME=$T gpg --batch --pinentry-mode loopback --passphrase-file "$T/.new" --armor \
        --export-secret-subkeys "$SUB!" > "$T/ci.asc"
    # the copy holds the subkey alone, and signs with the new passphrase
    U=$(tmpdir); CLEAN="$CLEAN $U"
    GNUPGHOME=$U gpg --batch --quiet --import "$T/ci.asc" 2>/dev/null
    GNUPGHOME=$U gpg --batch --list-secret-keys | grep -q '^sec#' || die "the copy for CI holds the main key"
    echo check > "$U/f"
    GNUPGHOME=$U gpg --batch --pinentry-mode loopback --passphrase-file "$T/.new" --detach-sign -o "$U/f.sig" "$U/f" ||
        die "the copy for CI doesn't sign"
    gh secret set APPKATA_SIGNING_KEY --env release --repo "$REPO" < "$T/ci.asc"
    tr -d '\n' < "$T/.new" | gh secret set APPKATA_SIGNING_PASSPHRASE --env release --repo "$REPO"
    say "$REPO's release environment now holds the signing subkey $SUB."
}

key_export() {
    DIR=$1
    keyhome "$DIR"
    export_public
    say "Wrote packaging/appkata-release-key.asc: commit it (with the fingerprint in README.md and docs/gpg.md)."
    ask "Send the key to keys.openpgp.org?"
    gpg --batch --keyserver hkps://keys.openpgp.org --send-keys "$FPR"
    say "keys.openpgp.org publishes the key's name only once its address is verified: run"
    say "  curl -sS --data-urlencode keytext@packaging/appkata-release-key.asc https://keys.openpgp.org/vks/v1/upload"
    say "and follow the link in its answer, or use https://keys.openpgp.org/upload."
    say "Fingerprint: $FPR"
}

key_extend() {
    DIR=$1
    keyhome "$DIR"
    # shellcheck disable=SC2046
    gpg --batch $(loopback) --quick-set-expire "$FPR" 5y
    SUB=$(signing_subkey any)
    [ -n "$SUB" ] || die "the key has no signing subkey"
    # shellcheck disable=SC2046
    gpg --batch $(loopback) --quick-set-expire "$FPR" 2y "$SUB"
    gpg --batch --list-keys "$FPR" >&2
    key_export "$DIR"
    say "Now key-github $DIR: the copy in GitHub carries the old date, and stops signing when it passes."
}

# --- the repository's settings -------------------------------------------------------------------

ruleset_id() {      # NAME: its id, nothing when there's none; fails when the rulesets can't be read
    _rs=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$1\") | .id" 2>/dev/null) || return 1
    printf '%s\n' "$_rs"
}

setup() {
    say "== $REPO"
    me=$(gh api user --jq .id)
    if gh api "repos/$REPO/environments/release" >/dev/null 2>&1; then say "release environment: there"
    else
        ask "Make the release environment (you approve, v* tags only)?"
        printf '{"reviewers":[{"type":"User","id":%s}],"prevent_self_review":false,"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' "$me" |
            gh api -X PUT "repos/$REPO/environments/release" --input - >/dev/null
        gh api -X POST "repos/$REPO/environments/release/deployment-branch-policies" -f name='v*' -f type=tag >/dev/null
        say "release environment: made"
    fi
    id=$(ruleset_id tags) || die "can't read $REPO's rulesets"
    if [ -n "$id" ]; then say "tags ruleset: there"
    else
        ask "Make the tags ruleset (only admins create, move or delete any tag)?"
        gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null <<'EOF'
{"name": "tags", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
 "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
 "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]}
EOF
        say "tags ruleset: made"
    fi
    if [ "$(gh api "repos/$REPO/immutable-releases" --jq .enabled 2>/dev/null)" = true ]; then say "immutable releases: on"
    else
        ask "Turn on immutable releases?"
        gh api -X PUT "repos/$REPO/immutable-releases" >/dev/null
        say "immutable releases: turned on"
    fi
    if [ "$(gh api "repos/$REPO/actions/permissions" --jq .sha_pinning_required)" = true ]; then say "actions pinned by SHA: required"
    else
        ask "Require every action to be pinned to a full-length commit SHA?"
        gh api "repos/$REPO/actions/permissions" --jq '{enabled, allowed_actions, sha_pinning_required: true}' |
            gh api -X PUT "repos/$REPO/actions/permissions" --input - >/dev/null
        say "actions pinned by SHA: required"
    fi
    id=$(ruleset_id master) || die "can't read $REPO's rulesets"
    if [ -z "$id" ]; then say "master ruleset: missing (GENESIS.md says how it is made): the ci check not added"
    elif gh api "repos/$REPO/rulesets/$id" --jq '.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context' | grep -qx ci; then
        say "the ci check: required"
    elif [ -z "$(gh run list --repo "$REPO" --workflow ci.yml --status success --limit 1 --json databaseId --jq '.[].databaseId')" ]; then
        say "the ci check: not required yet (GitHub offers it once it has passed: run setup again then)"
    else
        ask "Require the ci check in the master ruleset?"
        gh api "repos/$REPO/rulesets/$id" --jq '{name, target, enforcement, conditions, bypass_actors,
            rules: (.rules + [{type: "required_status_checks", parameters: {strict_required_status_checks_policy: false,
              required_status_checks: [{context: "ci", integration_id: 15368}]}}])}' |
            gh api -X PUT "repos/$REPO/rulesets/$id" --input - >/dev/null
        say "the ci check: required"
    fi
    if gh label list --repo "$REPO" --limit 500 --json name --jq '.[].name' | grep -qx field-test; then say "the field-test label: there"
    else
        ask "Make the field-test label, for a release's field-test issues (docs/testing.md)?"
        gh label create field-test --repo "$REPO" --color 5319E7 --description "A release's field test: docs/testing.md" >/dev/null
        say "the field-test label: made"
    fi
}

check() {
    FAIL=0
    is() {     # WHAT GOT WANT
        if [ "$2" = "$3" ]; then say "ok    $1: $2"; else say "FAIL  $1: $2 (want $3)"; FAIL=1; fi
    }
    # GitHub's answer, or "(can't read)": gh prints a refused read's error JSON on stdout, which
    # isn't the answer, and a read that fails mustn't end the check (set -e) before its other lines
    api() { _a=$(gh api "repos/$REPO$1" --jq "$2" 2>/dev/null) && printf '%s\n' "$_a" || echo "(can't read)"; }
    BYPASS='if has("bypass_actors") then [.bypass_actors[] | select(.actor_type == "RepositoryRole" and .actor_id == 5)] | length else "(can'"'"'t read)" end'
    is "visibility" "$(api "" .visibility)" public
    is "default branch" "$(api "" .default_branch)" master
    # GitHub leaves out what only an admin may read (the merge methods, a ruleset's bypass list): that
    # is "(can't read)" too, not a wrong value
    is "merge methods (squash merge rebase)" "$(api "" 'if .allow_squash_merge == null then "(can'"'"'t read)" else "\(.allow_squash_merge) \(.allow_merge_commit) \(.allow_rebase_merge)" end')" "true false false"
    if ! id=$(ruleset_id master); then is "master ruleset" "(can't read)" there
    elif [ -z "$id" ]; then is "master ruleset" missing there
    else
        m=/rulesets/$id
        is "master ruleset" "$(api "$m" '"\(.enforcement) \(.target) \(.conditions.ref_name.include | join(","))"')" "active branch ~DEFAULT_BRANCH"
        is "master ruleset: rules" "$(api "$m" '[.rules[].type] | sort | join(" ")')" "deletion non_fast_forward pull_request required_status_checks"
        is "master ruleset: pull requests" "$(api "$m" '.rules[] | select(.type == "pull_request") | .parameters | "\(.required_approving_review_count) approvals, \(.allowed_merge_methods | join(","))"')" "0 approvals, squash"
        is "master ruleset: required checks" "$(api "$m" '[.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context] | join(",")')" ci
        is "master ruleset: admins bypass" "$(api "$m" "$BYPASS")" 1
    fi
    if ! id=$(ruleset_id tags); then is "tags ruleset" "(can't read)" there
    elif [ -z "$id" ]; then is "tags ruleset" missing there
    else
        t=/rulesets/$id
        is "tags ruleset" "$(api "$t" '"\(.enforcement) \(.target) \(.conditions.ref_name.include | join(",")) \([.rules[].type] | sort | join(","))"')" "active tag ~ALL creation,deletion,update"
        is "tags ruleset: admins bypass" "$(api "$t" "$BYPASS")" 1
    fi
    is "workflow token" "$(api /actions/permissions/workflow '"\(.default_workflow_permissions), approves PRs: \(.can_approve_pull_request_reviews)"')" "read, approves PRs: false"
    is "fork PR runs wait for approval" "$(api /actions/permissions/fork-pr-contributor-approval .approval_policy)" all_external_contributors
    is "actions pinned by SHA" "$(api /actions/permissions .sha_pinning_required)" true
    envs=$(api /environments '[.environments[].name] | index("release") != null')
    if [ "$envs" = true ]; then
        is "release environment" "$(api /environments/release '"\([.protection_rules[].type] | sort | join(",")), custom: \(.deployment_branch_policy.custom_branch_policies)"')" "branch_policy,required_reviewers, custom: true"
        is "release environment: deploys" "$(api /environments/release/deployment-branch-policies '[.branch_policies[] | "\(.type) \(.name)"] | join(",")')" "tag v*"
        secrets=$(gh secret list --env release --repo "$REPO" --json name --jq '[.[].name] | sort | join(",")' 2>/dev/null) ||
            secrets="(can't read)"
        is "release environment: secrets" "$secrets" "APPKATA_SIGNING_KEY,APPKATA_SIGNING_PASSPHRASE"
    elif [ "$envs" = false ]; then is "release environment" missing there
    else is "release environment" "(can't read)" there
    fi
    is "immutable releases" "$(api /immutable-releases .enabled)" true
    is "private vulnerability reporting" "$(api /private-vulnerability-reporting .enabled)" true
    is "field-test label" "$(api "/labels?per_page=100" 'if [.[].name] | index("field-test") then "there" else "missing" end')" there
    if [ -f "$KEY" ]; then is "release key" "${KEY#"$HERE"/} $(keyfpr "$KEY" | cut -c1-8)..." "${KEY#"$HERE"/} $(keyfpr "$KEY" | cut -c1-8)..."
    else is "release key" "no ${KEY#"$HERE"/}" "${KEY#"$HERE"/}"
    fi
    [ "$FAIL" = 0 ] || exit 1
}

# --- a release -----------------------------------------------------------------------------------

keyfpr() {      # FILE: the main key's fingerprint in a public key file
    gpg --batch --with-colons --import-options show-only --import "$1" 2>/dev/null | awk -F: '$1 == "fpr" { print $10; exit }'
}

verify() {
    V=${1:-$VERSION} TAG=v${1:-$VERSION}
    [ -f "$KEY" ] || die "no public key to check the signature with: ${KEY#"$HERE"/}"
    want=$(keyfpr "$KEY")
    [ -n "$want" ] || die "${KEY#"$HERE"/} holds no key"
    draft=$(gh release view "$TAG" --repo "$REPO" --json isDraft --jq .isDraft) || die "$REPO has no release $TAG"
    D="$HERE/build/publish/$TAG"
    rm -rf "$D" && mkdir -p "$D"
    gh release download "$TAG" --repo "$REPO" -D "$D"
    names=$(cd "$D" && ls | sort | tr '\n' ' ')
    expect="AppKata-$V-setup.exe AppKata-$V-setup.exe.sha256 AppKata-$V-x86_64.AppImage AppKata-$V-x86_64.AppImage.asc AppKata-$V-x86_64.AppImage.sha256 "
    [ "$names" = "$expect" ] || die "the release's files are: $names; want: $expect"
    (cd "$D" && sha256 -c ./*.sha256) >&2 || die "a file doesn't match its .sha256"
    G=$(tmpdir); CLEAN="$CLEAN $G"
    GNUPGHOME=$G gpg --batch --quiet --import "$KEY" 2>/dev/null
    status=$(GNUPGHOME=$G gpg --batch --status-fd 1 --verify "$D/AppKata-$V-x86_64.AppImage.asc" "$D/AppKata-$V-x86_64.AppImage" 2>/dev/null) ||
        die "the AppImage's signature doesn't verify"
    got=$(echo "$status" | awk '$2 == "VALIDSIG" { print $NF }')
    [ "$got" = "$want" ] || die "the AppImage is signed by $got, not the release key $want"
    say "$TAG ($([ "$draft" = true ] && echo draft || echo published)): every file matches its .sha256, and the AppImage's signature is the release key's ($want)"
    if [ "$draft" = false ] && [ "$(gh api "repos/$REPO/immutable-releases" --jq .enabled 2>/dev/null)" = true ]; then
        gh release verify "$TAG" --repo "$REPO" >&2
    fi
    (cd "$D" && sha256 "AppKata-$V-x86_64.AppImage" "AppKata-$V-setup.exe") >&2
}

release() {
    TAG=v$VERSION
    cd "$HERE"
    remote=$(git remote -v | awk -v r="$REPO" '$2 ~ "github.com[:/]" r "(\\.git)?$" && $3 == "(push)" { print $1; exit }')
    [ -n "$remote" ] || die "no git remote points at $REPO"
    [ -z "$(git status --porcelain)" ] || die "the work tree has changes"
    [ "$(git rev-parse --abbrev-ref HEAD)" = master ] || die "not on master"
    git fetch -q "$remote" master
    [ "$(git rev-parse HEAD)" = "$(git rev-parse "$remote/master")" ] || die "master isn't $remote/master"
    ! git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || die "$TAG exists here"
    [ -z "$(git ls-remote --tags "$remote" "$TAG")" ] || die "$TAG exists on $remote"
    [ -f "tests/data/state/$VERSION.json" ] || ask "tests/data/state/$VERSION.json is missing (build.md, \"Before tagging a release\", 3): tag anyway?"
    ask "Tag $(git rev-parse --short HEAD) as $TAG and push it to $REPO?"
    git tag -a "$TAG" -m "AppKata $VERSION"
    git push -q "$remote" "$TAG"
    resume "$VERSION"
}

resume() {
    VERSION=${1:-$VERSION} TAG=v${1:-$VERSION}
    say "== waiting for CI's run of $TAG"
    id=
    while [ -z "$id" ]; do
        sleep 10
        id=$(gh run list --repo "$REPO" --workflow ci.yml --branch "$TAG" --event push --limit 1 --json databaseId --jq '.[].databaseId')
    done
    say "run $id: https://github.com/$REPO/actions/runs/$id"
    waiting=
    while :; do
        [ "$(gh api "repos/$REPO/actions/runs/$id/pending_deployments" --jq length)" = 0 ] || { waiting=1; break; }
        case $(gh run view "$id" --repo "$REPO" --json status,conclusion --jq '"\(.status) \(.conclusion)"') in
            "completed success") break ;;                 # signed already: resumed after the approval
            completed*) die "the run ended without signing: gh run view $id --repo $REPO" ;;
        esac
        sleep 20
    done
    say "== what CI built (its jobs' sha256 notices)"
    built=$(for job in appimage windows; do
        j=$(gh run view "$id" --repo "$REPO" --json jobs --jq ".jobs[] | select(.name == \"$job\") | .databaseId")
        gh api "repos/$REPO/check-runs/$j/annotations" --jq '.[] | select(.title == "sha256") | .message'
    done)
    [ "$(echo "$built" | grep -c .)" = 2 ] || die "the run's build jobs posted no sha256 notices"
    say "$built"
    if [ -n "$waiting" ]; then
        ask "Sign the AppImage and make the draft release?"
        env=$(gh api "repos/$REPO/actions/runs/$id/pending_deployments" --jq '.[] | select(.environment.name == "release") | .environment.id')
        gh api -X POST "repos/$REPO/actions/runs/$id/pending_deployments" -F "environment_ids[]=$env" -f state=approved -f comment="publish.sh release" >/dev/null
        gh run watch "$id" --repo "$REPO" --exit-status >/dev/null || die "the run failed: gh run view $id --repo $REPO"
    fi
    verify "$VERSION"
    drafted=$(cd "$HERE/build/publish/$TAG" && sha256 "AppKata-$VERSION-x86_64.AppImage" "AppKata-$VERSION-setup.exe")
    [ "$(echo "$drafted" | sort)" = "$(echo "$built" | sort)" ] || die "the draft's files aren't the ones approved: $drafted"
    say "The draft's two files are the ones whose SHA-256s you approved."
    say "The draft: https://github.com/$REPO/releases (only you see it). Before publishing it: build.md,"
    say "\"Before tagging a release\", 6 (the field test by hand, with the draft's files); then publish.sh publish."
}

publish() {
    TAG=v${1:-$VERSION}
    [ "$(gh release view "$TAG" --repo "$REPO" --json isDraft --jq .isDraft)" = true ] || die "$TAG isn't a draft"
    verify "${1:-$VERSION}"
    ask "Publish $TAG? Every AppKata offers it as an update from its next sync."
    gh release edit "$TAG" --repo "$REPO" --draft=false --latest >/dev/null
    verify "${1:-$VERSION}"
}

field_test() {      # [VERSION]: the release's field-test issue, and a sub-issue for each environment
    V=${1:-$VERSION}
    gh label list --repo "$REPO" --limit 500 --json name --jq '.[].name' | grep -qx field-test ||
        die "$REPO has no field-test label: publish.sh setup makes it"
    have=$(gh issue list --repo "$REPO" --label field-test --state all --search "\"Field test: $V\" in:title" --json number --jq '.[].number')
    [ -z "$have" ] || die "$REPO has field-test issues for $V already: $(echo $have)"
    envs=$(python3 "$HERE/scripts/sandbox/fieldtest_questions.py" --environments) || die "can't read docs/testing.md's environments"
    ask "Open $REPO's field-test issues for $V: one for the release, one under it for each of $(echo "$envs" | paste -sd, - | sed 's/,/, /g')?"
    parent=$(printf '%s\n\n%s\n' \
        "The field test of AppKata $V, before it is published: one sub-issue for each environment docs/testing.md names (\"By hand, before a release\"), with its checklist. This issue closes when every sub-issue has closed, or when the owner waives one and says why there." \
        "$(echo "$envs" | sed 's/^/- /')" | gh issue create --repo "$REPO" --title "Field test: $V" --label field-test --body-file -)
    say "the release's: $parent"
    echo "$envs" | while IFS= read -r env; do
        child=$(sh "$HERE/scripts/sandbox/field-test.sh" --issue-body "$env" |
            gh issue create --repo "$REPO" --title "Field test: $V on $env" --label field-test --body-file -)
        id=$(gh api "repos/$REPO/issues/${child##*/}" --jq .id)
        gh api -X POST "repos/$REPO/issues/${parent##*/}/sub_issues" -F sub_issue_id="$id" >/dev/null
        say "  $env: $child"
    done
}

case $CMD in
    key-new) [ $# = 2 ] || die "key-new DIR 'NAME <EMAIL>'"; key_new "$@" ;;
    key-github|key-export|key-extend) [ $# = 1 ] || die "$CMD DIR"; "key_${CMD#key-}" "$1" ;;
    setup|check|release) "$CMD" ;;
    resume|verify|publish) "$CMD" "$@" ;;
    field-test) field_test "$@" ;;
    *) die "no command $CMD (publish.sh with none says what there is)" ;;
esac
