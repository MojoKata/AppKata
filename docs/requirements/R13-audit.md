# R13. Audit

R13.1. The **Audit** perspective is an immutable record of key operations, newest first.

R13.2. It is stored in the app's SQLite database (1.8). Entries can only be added: the database
refuses every change or deletion (triggers), and the UI offers neither.

R13.3. **What's recorded.** Each entry has a time, an actor, a kind, an action, a subject (the
app, Source, Trust, Authority or file), the URL when there is one, and details.

- The actor is **You** for what the user does, **Sync** for what AppKata does on its own, or
  **System** for changes AppKata found made by something else (16.9).
- **Apps**: installed, updated, uninstalled (with the version and file), how to install chosen (4.9), pinned, unpinned, and installs of older versions (pinned); a kept version removed; AppKata's own AppImage adopted as installed (2.11); the sandbox set or kept, with the template and level (17.16); an app sandboxed by a setup, an update or AppKata's start once the system can (17.13); a launcher rewritten at AppKata's start, with a hash of its text (17.4).
- **Sources**: added, removed (and whether the app was uninstalled too), settings changed; Sources
  kept from a removed Trust.
- **Trusts**: added (with their Score), removed, Score changed; Sync applying newly verified changes (commit, app count) and
  refusing a change (unsigned, disabled authority, bad signature, rewritten history).
- **Authorities**: added with a Trust, enabled, disabled, removed; a new signer found by Sync,
  approved or ignored.
- **Reviews**: saved (Trust, Rating, tags, commit, signed, pushed); a commit re-signed.
- **Settings**: the review file chosen; API tokens set or removed (never the token itself); `appkata://` links registered (11.3); settings imported or exported; system sandbox support enabled, or put off with Not now, and AppKata's AppArmor profile removed by Repair (17.10, 17.10.2).

Failed operations aren't Audit entries; they're in the App log (14).

R13.4. **Layout.** A title with the entry count and "newest first", a filter box
(subject, action, details, URL) and kind chips (All, Apps, Sources, Trusts, Authorities,
Reviews, Settings). Entries are grouped under day headings ("Today", "Yesterday", then the
date). Each row shows an icon for the kind, a sentence ("You installed **KeePassXC**"), detail
chips, the URL, a **You** or **Sync** pill and the time.

R13.5. The list is virtualized and loads 100 entries at a time as it scrolls; "Start of the
audit" marks the end.
