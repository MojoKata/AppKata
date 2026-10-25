# Release signatures and what AppKata verifies

What AppKata checks when it downloads a release, where a cryptographic **signature** does and doesn't
enter the picture, and what adding publisher-GPG verification would take. Requirements: downloads and
checksums (4.4), review signatures (7.6.2, 10.7, 10.8), review Details (10.3.4), Windows Authenticode
(15.11), package-channel trust (16.3.6).

## Short answers

- **Does AppKata verify a publisher's GPG/PGP (or minisign) signature on a release download?** **No.**
  On Linux portable installs (AppImage, tarball) it checks a **checksum** if one is published, which is
  *integrity*, not *authenticity*. Detached signatures (`.asc`, `.sig`, `.minisig`) are ignored.
- **Can the SHA-256 hashes be wrapped in a GPG signature?** You can publish `SHA256SUMS` +
  `SHA256SUMS.asc`, but **AppKata won't check the `.asc` today** — it would use `SHA256SUMS` for the
  checksum and skip the signature. It only helps someone verifying by hand.
- **Is there a signed-commit mechanism for release downloads?** No. The signed-commit machinery is for
  the **trust files** (`AppKata.md`), i.e. reviewer *identity* — not the binaries. There is, however, a
  related *signed attestation of a binary's digest* through reviews; see
  [Authenticity through signed reviews](#authenticity-through-signed-reviews).

## What a release download is checked against today

For a portable install (`kind in ("appimage", "tarball")`) the chain is:

1. **TLS** to the forge (the asset URL from GitHub/GitLab/Forgejo/Gitea).
2. **Checksum**, if the release carries one. `assets.checksum_for()` looks, in order, for
   `<asset>.sha256`, `<asset>.sha256sum`, `<asset>.sha512`, then a `SHA256SUMS` / `checksums.txt`
   asset. `install.install()` compares the download's SHA-256 to it:
   - match → the install record's `verified` is **`"checksum"`**;
   - no checksum published → **`"unverified"`**.

A checksum is integrity only: whoever can replace the binary on the release page can replace the
checksum file next to it. It defends against a corrupted or truncated download and against a mirror
that serves a different file than the forge, not against a compromised release.

### Where `verified: "signed"` comes from

`"signed"` is set in exactly three places, **none of them a Linux portable download**:

| Origin | Mechanism | Code |
|---|---|---|
| Windows `.exe`/`.msi`/`.msix` | **Authenticode** — the OS verifies the embedded signature; the signer is shown (15.11) | `install.py` (`authenticode` / `signature_verdict`) |
| Flatpak | installed through `flatpak`, which verifies against the **remote's GPG key** (Flathub) (16.3.6) | `install.py` (flatpak branch) |
| `.deb` / `.rpm` | installed through `apt`/`dnf`, which verify against the **distro's repo keys** (16.3.6) | `install.py` (package branch) |

So the AppImage and tarball paths — the only two the sandbox covers — never produce `"signed"`.

### What the `.asc`/`.sig` files do (nothing, for now)

`assets.py`'s `SKIP` pattern lists `asc|sig|minisig|sbom|spdx|…` so those files are never offered as
*installable* assets. There is no verification of them either: nothing in `install.py`, `assets.py`,
`sync.py` or `forges.py` calls `gpg --verify`, `gpgv`, `minisign`, `signify` or an OpenPGP library on a
download. (The only OpenPGP use in `sync.py` is fetching a *reviewer's* key from `keys.openpgp.org` to
check a signed `AppKata.md` commit — see below — not a release.)

## The signed-commit machinery is about reviewers, not binaries

`gitsig.py` and `sshsig.py` verify that changes to a Trust's `AppKata.md` were **signed by one of its
Authorities** (7.6.2, 10.7, 10.8): OpenPGP via `gpg` in a keyring holding only that Trust's keys, and
SSH signatures in pure Python (so trust checks don't depend on the host's OpenSSH version). This
authenticates *who wrote a review*. It says nothing, on its own, about the bytes of a release.

## Authenticity through signed reviews

There is one path by which a cryptographic signature does reach a specific binary, and it is easy to
miss. A reviewer can record a file's **SHA-256 in the review's `Details`** (10.3.4,
`### <App>[<version>]::Details` → `SHA-256: …`). Because that review lives in a **signed commit**, the
digest is a **signed third-party attestation of that exact file**. When the file AppKata is about to
install (or has installed) has the same digest, App Detail shows **"Same file as \<reviewer\>
reviewed"** (`detail()` builds this as `sameFileAs`, comparing each review's `Details` SHA-256 — and
Flatpak `Commit` — against the chosen/installed asset's digest).

In AppKata's model, then, a release binary's *authenticity* comes from **trusted reviewers attesting
its digest**, not from the publisher signing it. That is arguably stronger than publisher
self-signing: it doesn't rest on the publisher's own key (which an attacker who owns the release also
tends to own), and it composes with the Trust/Score system the rest of AppKata already uses.

## If we wanted publisher-GPG verification

This would be a **new feature** (and a new `requirements.md` §4.4 clause), not a tweak. Sketch:

1. **A signing key per app/source.** A fingerprint, with lookup like the Trust layer already does
   (`.appkata/keys/` in the repo, then `keys.openpgp.org`), set as a Source setting and/or a review
   `Settings` line (e.g. `- Signing key: <fpr>`).
2. **Verify in the download path.** After the checksum step in `install.install()`, verify a detached
   signature over the asset (`<asset>.asc`/`.sig`) **or** over `SHA256SUMS` (then trust the checksum it
   covers). Reuse the OpenPGP path already in `gitsig.py`; add minisign only if wanted.
3. **A fourth `verified: "signed"` origin**, with the signer surfaced in the UI exactly as
   Authenticode is (the "Verified · \<signer\>" pill in `AppDetail.qml`), and recorded in the install
   record and the Audit.
4. **Fallbacks stay honest:** no signature / unknown key → `"checksum"` or `"unverified"` as today,
   never a silent pass.

Recommendation: keep it a **separate PR** from app sandboxing, since it touches the install/trust path
and needs its own requirement and tests. The signed-review digest attestation (above) already gives a
meaningful authenticity signal in the meantime.

## Publishing signed checksums anyway

Even though AppKata won't check it yet, publishing `SHA256SUMS` + `SHA256SUMS.asc` on a release is
harmless and good practice for users who verify manually:

```sh
cd releases
sha256sum AppKata-*-x86_64.AppImage AppKata-*-setup.exe > SHA256SUMS
gpg --armor --detach-sign SHA256SUMS            # → SHA256SUMS.asc
```

AppKata would pick up `SHA256SUMS` as the checksum source and ignore `SHA256SUMS.asc` until the
feature above exists. See [`github-workflows.md`](github-workflows.md) and [`build.md`](build.md) for
how release files are built and published.
