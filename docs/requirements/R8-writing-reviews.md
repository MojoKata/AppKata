# R8. Writing reviews

R8.1. The user's own `AppKata.md` holds their reviews. Its path is set in Settings (11.1).

R8.2. **Choosing the file.** The first time the user writes a review, if no path is set,
AppKata asks for a location:

- The default is `AppKata.md` in the user's home folder.
- A folder can be chosen; AppKata then uses `AppKata.md` inside it.
- If the file doesn't exist, it is created with the Trust table header (10.1).

R8.3. **Git repositories.** If the chosen file is in a local git repository that has an
`origin` remote, AppKata offers to commit automatically, and to push automatically. These
choices are saved, and appear as checkboxes in the review dialog (8.4.5).

R8.4. **Review dialog.** The review dialog contains:

R8.4.1. The app name. It can't be edited.

R8.4.1.1. **Version**: which review this is (10.3). A select of the app's releases, newest first,
plus **Any version** (the app review). Each item says "Installed" or "Reviewed" when it is.

- It starts at the installed version, or at the latest release when the app isn't installed. When
  the user has no version reviews of the app and the app isn't installed, it starts at **Any
  version**.
- Choosing a version that has a review loads it ("· editing your review of 1.18.2"). Choosing one
  that hasn't starts a new review: Trust, Rating and Tags start from the values in effect for that
  version (10.3.3), the editor starts empty, and a note under the select says "New review of
  2.0.1. Your review of 1.18.2 (2026-03-04) stays in AppKata.md."
- A review of a version the user never installed is allowed, for warnings such as a compromised
  release (10.3.2).

R8.4.2. **Tags**: a multi-select dropdown.

- It lists the predefined tags (10.4), then tags already used in any Trust file.
- The user can also type a new tag. Tags are validated as identifiers (10.4.1).
- Warning tags (`spyware`, `malware`, `ads`, `tracking`, `knownvuln`) are shown in the
  warning colour.

R8.4.3. **Trust**: a row of clickable symbols, `–★★★★★`.

- Clicking `–` sets **0, Avoid**, and the row turns the error colour.
- Clicking a star sets 1–5.
- A small × clears the value (no opinion).

The current value is spelled out next to it, for example "3 · Trusted with reservations".

R8.4.4. **Rating**: the same control as Trust, but `–` means 0 stars and has no veto meaning
and no special colour.

R8.4.4.1. Trust and Rating sit side by side on one line, each with a one-line hint under it
("How far you trust this app and its authors", "How much you like it"); the Avoid warning
replaces the Trust hint. The dialog is wide enough for both (about 780 px).

R8.4.4.2. In the Tags box, the tag chips and the input are vertically centred.

R8.4.5. A **Markdown editor** for the review's text (the `# <App>` or `## <App>[<version>]` text),
with Edit and Preview tabs.

R8.4.5.1. **Include what I have installed**, a checkbox shown when the chosen version is the
installed one. It writes the review's Details (10.3.4) from the install record (4.1): Date,
Platform, Channel, and File and SHA-256, or the Flatpak Commit. Under it, the exact lines in a
small monospace preview. They describe the reviewer's computer and are public once pushed, so the
choice is the user's: it starts checked for apps AppKata installed, unchecked otherwise, and the
last choice is remembered. A review saved without it keeps any Details it already had.

R8.4.6. **Auto-commit** and **Auto-push** checkboxes.

- They are shown only when 8.3 applies.
- Auto-push requires auto-commit.

R8.4.7. **Settings sub-section.** Saving writes the review's Settings (10.3.1): `## <App>::Settings`
for the app review, `### <App>[<version>]::Settings` for a version review. It always holds the
review's Trust, Rating and Tags; the install and Source options are written there only when they
differ from the values carried from the review before (10.3.3). The dialog doesn't show it, and it
isn't part of the Markdown editor's text. The one exception is the sandbox: a sandbox the user chose
for the app themselves (not one from the reviews or the default) is written whole, as the `Sandbox`
lines a reader's AppKata reads back to the same thing, and the dialog shows it first as one line
("Sandbox: Offline editor, with ~/Notes (read-write)") with **Include my sandbox**, on by default,
since it can name personal folders; what a review can't grant (17.3.1) is left out, and the dialog
says so (review 2, F9).

R8.4.8. **Save** and **Cancel** buttons.

R8.5. **Saving.**

1. AppKata replaces the review being edited, or adds the new version review after the app's
   other version reviews, in version order. When the review is the app's newest (10.3.3), it also
   updates the app's row in the table. When it adds the first version review and the app review
   has no Trust, Rating or Tags lines of its own, it first writes the table row's values into
   `## <App>::Settings`, so the app review keeps its verdict. Everything else in the file is kept
   exactly as it was.
2. With auto-commit, AppKata commits the file on its own (message: `Review <App>`, or
   `Review <App> <version>`) and checks
   the commit with `git verify-commit`.
3. If the commit isn't signed, AppKata does **not** push. It says so, and offers **Amend with
   signing** and **How to set up signing**.
4. If the commit is signed and auto-push is on, AppKata pushes.

Before Save, if auto-commit is on and git isn't set up to sign commits (`commit.gpgsign`),
the dialog shows a warning in advance.

R8.6. **Opening the dialog.** The pencil button in the App Detail panel (5.7.1) opens the
review dialog in both Apps and Catalog. It opens at the version chosen by 8.4.1.1, with that
review filled in when there is one.
