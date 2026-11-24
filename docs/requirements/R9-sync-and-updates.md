# R9. Sync and updates

R9.1. Catalog, Sources and Trust data are cached in the database (R1.8). Every view shows
cached data straight away, including offline.

R9.2. **Sync** refreshes:

- Each Source: releases, metadata, images and README.
- Each Trust: fetch, verify (R10.7) and parse.

While Sync runs, the header shows a progress ring with "Syncing 12 / 40". Clicking it shows
the current item and a **Cancel** button.

R9.2.1. At most four hosts are fetched at the same time. Rate limits are respected:
`x-ratelimit-reset`, `Retry-After`, and backoff for other failures.

R9.2.2. API tokens are kept per host (R11.1). A host's token is sent only to that host and to the
forge's own API and raw-file hosts, which are named here: for `github.com`, `api.github.com` and
`raw.githubusercontent.com`; for every other host, the host alone. It is never sent to any other
host. It is sent over https only, never over plain http. A redirect carries it on only to an
address with the same scheme, host and port: to any other address the request goes on without the
token, and a redirect to plain http of a request that carried one isn't followed.

R9.2.3. Sync fetches release information for every app in the Catalog, whether it comes from a
Source or a Trust, so tiles show current versions.

R9.3. **Background checks.** While AppKata is running, including in the tray, it syncs
automatically every 6 hours by default (R11.1).

When new updates are found, AppKata shows a system notification: "3 app updates available".
Clicking it opens the Apps view.

R9.4. **Comparing versions.** A version is newer when it compares greater as semver, after
stripping a leading `v` and taking the version-extraction regex (R2.6.2) into account. If
either version isn't semver-like, AppKata compares release dates instead. The same comparison
places reviews on versions (R10.3.5); package versions are first mapped to the project's (R16.7).

A release with no files attached (a bare tag) is skipped, except for track-only Sources.

An update is **available** when the release is newer than the installed version and all of
these hold:

- The app isn't pinned (R9.5).
- The release is at least the minimum age old (R9.5).
- The Source isn't track only (R2.6.1). A track-only Source shows "New version" without an
  Update button.

R9.5. **Pinning and minimum age.** Both belong to the app, whatever its origin (R2.9).

R9.5.1. A pinned app gets no updates until it is unpinned. AppKata records the version it was
pinned at.

R9.5.2. **Minimum age** in days: a release is considered only once it is at least that old.
It is a global setting only (Settings → Updates → Minimum age, R11.1.3; default 0), with no
per-Source or per-app override.
