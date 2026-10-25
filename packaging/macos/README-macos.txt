AppKata macOS hand-off
======================

The Linux build assembled AppKata.app (universal2: Intel and Apple silicon) but could
not sign it. Finish the release on any Mac with macOS 12 or newer.

1. Copy the .tar.gz itself to the Mac (AirDrop, USB, scp of the file), then unpack it there:
       shasum -a 256 -c AppKata-*-macos-unsigned.tar.gz.sha256
       tar -xzf AppKata-*-macos-unsigned.tar.gz
   Don't copy the unpacked folder: shared folders and some copy tools drop the symlinks
   that the Qt frameworks need.

2. One-time setup:
       xcode-select --install
       (import your "Developer ID Application" certificate into the login keychain)
       xcrun notarytool store-credentials appkata-notary --apple-id you@example.com --team-id TEAMID

3. Check (changes nothing), then sign:
       cd AppKata-*-macos
       ./mac-sign.sh --check --profile appkata-notary
       ./mac-sign.sh --profile appkata-notary

The result is AppKata-<version>.dmg (signed, notarized, stapled) and its .sha256, written
next to the script, plus mac-sign-<date>.log. If a step fails, the script says what went
wrong and what to do; it's safe to run again. ./mac-sign.sh --help lists the options.
