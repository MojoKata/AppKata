import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "."

// Settings (requirement 11).
Dialog {
    id: root
    scrollBody: false                  // its own Flickable scrolls the body
    title: "Settings"
    dialogWidth: 760
    readonly property var p: backend.prefs
    readonly property var loc: backend.locations
    readonly property var sb: backend.sandboxSupport     // system support, defaults, session warning (17.15)
    signal confirmAction(string kind, var args)          // removals ask first (requirement 5.8)
    function show() { tokenHost.text = "github.com"; tokenValue.text = ""; relayField.text = ""; open(); flick.contentY = 0 }
    function scrollTo(section) {     // the tour
        const t = ({ portable: secPortable, sandbox: secSandbox, data: secData, accounts: secAccounts })[section]
        flick.contentY = t ? Math.min(t.y - 4, flick.contentHeight - flick.height) : 0
    }
    function home(path) { return loc.windows ? (path || "") : (path || "").replace(loc.home, "~") }

    component Section: Text {
        color: Theme.faint; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.2; topPadding: 14; bottomPadding: 2
    }
    // one setting: a label (and hint) on the left, its control on the right
    component SettingRow: Item {
        id: sr
        property string label
        property string hint: ""
        default property alias control: slot.data
        width: col.width; height: Math.max(40, labels.height + 12, slot.childrenRect.height + 8)
        Column {
            id: labels
            anchors.verticalCenter: parent.verticalCenter; width: 300; spacing: 3
            Text { text: sr.label; color: Theme.text; font.pixelSize: 14; font.bold: true; width: parent.width; wrapMode: Text.WordWrap }
            Text { visible: sr.hint !== ""; text: sr.hint; color: Theme.muted; font.pixelSize: 12; width: parent.width; wrapMode: Text.WordWrap }
        }
        Item { id: slot; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: col.width - 320; height: childrenRect.height }
    }
    component Toggle: Switch {
        id: sw
        anchors.right: parent ? parent.right : undefined
        padding: 0; spacing: 0          // no Basic-style padding, so it lines up with the other controls' right edge
        indicator: Rectangle {
            x: sw.width - width; y: (sw.height - height) / 2
            implicitWidth: 38; implicitHeight: 22; radius: 11
            color: sw.checked ? Theme.accent : Theme.track; border.color: sw.checked ? Theme.accent : Theme.borderStrong
            Rectangle { x: sw.checked ? 18 : 2; y: 2; width: 18; height: 18; radius: 9; color: "#ffffff"; Behavior on x { NumberAnimation { duration: 120 } } }
        }
    }
    component PathField: Row {
        id: pf
        property string value
        property string placeholder: ""
        property bool folder: true
        signal picked(string path)
        anchors.right: parent ? parent.right : undefined
        spacing: 8
        Field { width: slotWidth() - 40; mono: true; text: root.home(pf.value); placeholder: pf.placeholder
                onAccepted: pf.picked(text.replace(/^~/, root.loc.home)) }
        TipButton { icon: "folder"; tip: "Browse…"; anchors.verticalCenter: parent.verticalCenter; onClicked: { picker.target = pf; picker.open() } }
    }
    function slotWidth() { return col.width - 320 }
    FolderDialog {
        id: picker
        property var target: null
        onAccepted: if (target) target.picked(Theme.localPath(selectedFolder))
    }
    FileDialog {
        id: reviewPicker
        fileMode: FileDialog.SaveFile; nameFilters: ["Markdown (*.md)"]
        currentFolder: Theme.fileUrl(root.loc.home)
        onAccepted: backend.setPref("reviewPath", Theme.localPath(selectedFile))
    }
    FileDialog {
        id: exportPicker
        fileMode: FileDialog.SaveFile; nameFilters: ["AppKata export (*.json)"]
        selectedFile: Theme.fileUrl(root.loc.home + (root.loc.windows ? "\\" : "/") + "appkata-export.json")
        onAccepted: backend.exportTo(Theme.localPath(selectedFile))
    }
    FileDialog {
        id: importPicker
        fileMode: FileDialog.OpenFile; nameFilters: ["AppKata export or URL list (*.json *.txt *.md)", "All files (*)"]
        currentFolder: Theme.fileUrl(root.loc.home)
        onAccepted: backend.importFrom(Theme.localPath(selectedFile))
    }

    Flickable {
        id: flick
        width: parent.width; height: Math.min(560, Overlay.overlay ? Overlay.overlay.height - 220 : 560)
        contentHeight: col.height; clip: true
        layer.enabled: contentY > 0 || contentHeight > height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; x: flick.width - 6 }
        Column {
            id: col
            width: flick.width - 16; spacing: 4

            Section { text: "GENERAL"; topPadding: 0 }
            SettingRow {
                label: "Theme"
                Rectangle {
                    anchors.right: parent.right; width: 330; height: 32; radius: 9; color: Theme.track
                    objectName: "themeChoice"
                    readonly property string mode: Theme.mode     // the theme shown, decided once in Main.qml
                    Row { x: 3; y: 3
                        Repeater { model: [["system", "Match system"], ["dark", "Dark"], ["light", "Light"]]
                            Rectangle { width: 108; height: 26; radius: 7; color: parent.parent.mode === modelData[0] ? Theme.segOn : "transparent"
                                Text { anchors.centerIn: parent; text: modelData[1]; font.bold: true; font.pixelSize: 12
                                       color: parent.parent.parent.mode === modelData[0] ? Theme.text : Theme.muted }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: backend.setPref("theme", modelData[0]) } } } }
                }
            }
            SettingRow { label: "Start in the tray at login"; hint: "Keeps checking for updates; closing the window always leaves AppKata in the tray."
                Toggle { checked: root.loc.windows ? !!root.loc.autostartOn : !!root.p.startInTray; onToggled: backend.setPref("startInTray", checked) } }
            SettingRow { label: "Open appkata:// links"; hint: "A “Get it on AppKata” link opens Add source with the project filled in."
                Toggle { checked: !!root.loc.linksRegistered; onToggled: backend.registerLinks(checked) } }

            Section { text: "REVIEWS" }
            SettingRow { label: "Your AppKata.md"; hint: "Where your reviews are saved."
                Row { anchors.right: parent.right; spacing: 8
                    Field { width: root.slotWidth() - 40; mono: true; text: root.home(root.p.reviewPath); placeholder: root.loc.windows ? root.loc.home + "\\AppKata.md" : "~/AppKata.md"
                            onAccepted: backend.setPref("reviewPath", text.replace(/^~/, root.loc.home)) }
                    TipButton { icon: "folder"; tip: "Browse…"; anchors.verticalCenter: parent.verticalCenter; onClicked: reviewPicker.open() } } }
            SettingRow { label: "Commit reviews automatically"; hint: "When the file is in a git repository."
                Toggle { checked: !!root.p.autoCommit; onToggled: { backend.setPref("autoCommit", checked); if (!checked) backend.setPref("autoPush", false) } } }
            SettingRow { label: "Push reviews automatically"; hint: "Only signed commits are pushed."
                Toggle { checked: !!root.p.autoPush; enabled: !!root.p.autoCommit; opacity: enabled ? 1 : 0.5; onToggled: backend.setPref("autoPush", checked) } }

            Section { text: "UPDATES" }
            SettingRow { label: "Check for updates"
                Select { anchors.right: parent.right
                         label: ({ 0: "Off", 1: "Every hour", 6: "Every 6 hours", 24: "Every day" })[root.p.syncHours] || "Every " + root.p.syncHours + " hours"
                         options: [[0, "Off"], [1, "Every hour"], [6, "Every 6 hours"], [24, "Every day"]]; onPicked: k => backend.setPref("syncHours", parseInt(k)) } }
            SettingRow { label: "Notify me about updates"
                Toggle { checked: root.p.notifications !== false; onToggled: backend.setPref("notifications", checked) } }
            SettingRow { label: "Include pre-releases"; hint: "For apps without their own setting."
                Toggle { checked: !!root.p.prereleases; onToggled: backend.setPref("prereleases", checked) } }
            SettingRow { label: "Minimum age"; hint: "Offer a release only once it's this old. Applies to every app."
                Row { anchors.right: parent.right; spacing: 8
                    Field { width: 80; text: String(root.p.minAgeDefault || 0); field.validator: IntValidator { bottom: 0; top: 365 }
                            onAccepted: backend.setPref("minAgeDefault", parseInt(text || "0")) }
                    Text { text: "days"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter } } }

            Section { id: secPortable; text: "PORTABLE APPS" }
            Text { width: col.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; bottomPadding: 4
                   text: (root.loc.windows ? "Portable .zip and .exe apps, which run without installing." : "AppImages, tarballs and other apps that run without installing.")
                         + " Changes apply to new installs and updates; apps already installed stay where they are." }
            SettingRow { label: "Install apps for"; visible: !!root.loc.windows     // requirement 15.4
                hint: "Everyone on this computer, or just you. Each app can differ, in its Install options."
                Select { anchors.right: parent.right
                         label: root.p.installFor === "everyone" ? "Everyone" : "Just me"
                         options: [["me", "Just me"], ["everyone", "Everyone"]]; onPicked: k => backend.setPref("installFor", k) } }
            SettingRow { label: root.loc.windows ? "Install folder for me" : "Install folder"
                hint: root.loc.windows ? "Apps only you use. Each gets a folder here, with its versions side by side." : "Each app gets a folder here, with its versions side by side."
                PathField { value: root.p.installDir || root.loc.defaultInstallDir; onPicked: path => backend.setPref("installDir", path) } }
            SettingRow { label: "Install folder for everyone"; visible: !!root.loc.windows
                hint: "Apps every account uses. Only you and administrators can change what's in it."
                PathField { value: root.p.installDirEveryone || root.loc.defaultInstallDirEveryone; onPicked: path => backend.setPref("installDirEveryone", path) } }
            SettingRow { label: root.loc.windows ? "Add to the Start menu" : "Add to the app menu"; hint: root.loc.windows ? "A Start-menu shortcut for each app." : "A launcher entry for each app."
                Toggle { checked: root.p.appMenu !== false; onToggled: backend.setPref("appMenu", checked) } }
            SettingRow { label: "Stable name for the current version"
                hint: root.loc.windows ? "<app>\\current → the current version's folder, so shortcuts and command links survive updates."
                                       : "LocalSend.AppImage → LocalSend-1.18.2-x86_64.AppImage, so launchers and links survive updates."
                Toggle { checked: root.p.stableName !== false; onToggled: backend.setPref("stableName", checked) } }
            SettingRow { label: "Command links"; hint: root.loc.windows ? "A short command per app (e.g. localsend.cmd) in a folder AppKata adds to your PATH."
                                                                       : "A short command per app (e.g. localsend) in a folder on your PATH."
                Toggle { checked: root.p.commandLinks !== false; onToggled: backend.setPref("commandLinks", checked) } }
            SettingRow { label: "Command links folder"; visible: root.p.commandLinks !== false
                PathField { value: (root.p.commandDir || root.loc.defaultCommandDir).replace(/^~/, root.loc.home); onPicked: path => backend.setPref("commandDir", path) } }
            SettingRow { label: "Keep older versions"; hint: "Kept versions reinstall instantly from the App Detail panel; remove them there."
                Row { anchors.right: parent.right; spacing: 8
                    Field { width: 80; text: String(root.p.keepVersions === undefined ? 2 : root.p.keepVersions); field.validator: IntValidator { bottom: 0; top: 20 }
                            onAccepted: backend.setPref("keepVersions", parseInt(text || "0")) }
                    Text { text: "per app"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter } } }

            Section { id: secSandbox; text: "SANDBOX"; visible: !root.loc.windows }
            Column {
                visible: !root.loc.windows; width: col.width; spacing: 4
                                Text { width: col.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; bottomPadding: 4
                       text: "Runs portable apps and AppImages in a sandbox (bubblewrap): their own home folder, their files read-only, and "
                             + "only the folders and network you allow. Flatpaks have their own sandbox." }
                Rectangle {     // the session-type warning (17.9), shown prominently
                    visible: !!(root.sb.sessionWarning && root.sb.sessionWarning.text)
                    width: col.width; height: swTxt.height + 20; radius: 10; color: Theme.warnSoft
                    Icon { x: 12; y: 12; name: "warn"; size: 15; color: Theme.warn; lineWidth: 1.6 }
                    Text { id: swTxt; x: 38; y: 11; width: parent.width - 50; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                           text: (root.sb && root.sb.sessionWarning && root.sb.sessionWarning.text) || "" }
                }
                Rectangle {     // an abstract session bus: the network grant reaches it unfiltered (17.9, R3-8)
                    visible: !!(root.sb.busWarning && root.sb.busWarning.text)
                    width: col.width; height: bwTxt.height + 20; radius: 10; color: Theme.warnSoft
                    Icon { x: 12; y: 12; name: "warn"; size: 15; color: Theme.warn; lineWidth: 1.6 }
                    Text { id: bwTxt; x: 38; y: 11; width: parent.width - 50; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                           text: (root.sb && root.sb.busWarning && root.sb.busWarning.text) || "" }
                }
                SettingRow { label: "System support"
                    // 17.10, 17.10.2: "ok" under the system's own bwrap profile (Ubuntu 25.04+) means apps that
                    // bring their own sandbox run without it; "conflict" is AppKata's profile left beside it
                    // A missing tool is named after the status: bubblewrap makes it "unsupported"; xdg-dbus-proxy
                    // only takes Standard apps' desktop services (review 2, F12: it said bubblewrap when only the proxy was)
                    hint: (({ "ok": root.sb.innerSandbox === false
                                   ? "Ready, under this system's own AppArmor profile for bubblewrap. Apps that bring their own sandbox (Chromium, Electron) run without it here, inside AppKata's."
                                   : "Ready — the sandbox can run on this system.",
                             "setup-needed": "This system needs a one-time setup before the sandbox can run (asks for your password once). It lets programs use bubblewrap to create user namespaces again, which this system otherwise restricts."
                                             + (root.sb.declined ? " You chose Not now at an install, so installs don't ask; Set up… still does it." : "")
                                             + (root.sb.waitingNote ? " " + root.sb.waitingNote : ""),
                             "conflict": "AppKata's AppArmor profile, set up before this system was upgraded, now sits beside the system's own profile for bubblewrap, and no sandbox can start. Repair removes AppKata's (asks for your password once); sandboxes then run under the system's.",
                             "unsupported": "",
                             "n/a": "" })[root.sb.status] || "") + (root.sb.status !== "unsupported" && root.sb.toolsHint ? " " : "")
                          + (root.sb.toolsHint || (root.sb.status === "unsupported" ? "bubblewrap isn't installed, so apps run without a sandbox." : ""))
                    Row { anchors.right: parent.right; spacing: 8
                        Pill { anchors.verticalCenter: parent.verticalCenter; u: 0.92
                               text: root.sb.status === "ok" ? "Ready" : root.sb.status === "setup-needed" ? "Not enabled"
                                     : root.sb.status === "conflict" ? "Needs repair" : "Unavailable"
                               icon: root.sb.status === "ok" ? "shieldCheck" : "warn"
                               color: root.sb.status === "ok" ? Theme.okSoft : Theme.warnSoft
                               fg: root.sb.status === "ok" ? Theme.ok : Theme.warn }
                        FButton { visible: root.sb.status === "setup-needed"; text: "Set up…"; primary: true
                                  onClicked: backend.setupSandboxSupport() }
                        FButton { visible: root.sb.status === "conflict"; text: "Repair…"; primary: true; objectName: "repairSandbox"
                                  onClicked: backend.repairSandboxSupport() } }
                }
                SettingRow { label: "Default for new GUI apps"
                    hint: "Apps no Trust has reviewed. Reviewed apps follow their review. Each app can differ, in its Install options."
                    Select { anchors.right: parent.right
                             label: ({ strict: "Strict", standard: "Standard", off: "Off" })[root.sb.guiDefault] || "Strict"
                             options: [["strict", "Strict"], ["standard", "Standard"], ["off", "Off"]]
                             onPicked: k => backend.setPref("sandboxGuiDefault", k) } }
                SettingRow { label: "Command-line tools"; hint: "The CLI tool template: they see only the folder they're run in."
                    Select { anchors.right: parent.right
                             label: ({ "cli-tool": "CLI tool", strict: "Strict", off: "Off" })[root.sb.cliDefault] || "CLI tool"
                             options: [["cli-tool", "CLI tool"], ["strict", "Strict"], ["off", "Off"]]
                             onPicked: k => backend.setPref("sandboxCliDefault", k) } }
                SettingRow { label: "Follow reviewers' suggestions"; hint: "The strictest suggestion of your Trusts, until you choose for an app."
                    Toggle { checked: root.sb.followReviewers !== false; onToggled: backend.setPref("followReviewerSandbox", checked) } }
                SettingRow { label: "Badge apps when reviews suggest a change"
                    hint: "A new version keeps your grants and flags the app for review; it never widens access on its own."
                    Toggle { checked: root.sb.reviewBadge !== false; onToggled: backend.setPref("sandboxReviewBadge", checked) } }
                SettingRow { label: "Built-in templates"
                    hint: "Standard · Offline editor · Online app · Messenger · Media player · Developer tool · Command-line tool · Strict. Each app picks one, then tweaks." }
                SettingRow { label: "Sandbox home folders"; hint: "Each sandboxed app's settings and files."
                    Row { anchors.right: parent.right; spacing: 8
                        Text { width: root.slotWidth() - 44; elide: Text.ElideMiddle; horizontalAlignment: Text.AlignRight
                               text: root.home(root.loc.sandboxDir); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono
                               anchors.verticalCenter: parent.verticalCenter }
                        TipButton { icon: "folder"; tip: "Open folder"; onClicked: backend.openFolder(root.loc.sandboxDir) } } }
            }

            Section { id: secAccounts; text: "ACCOUNTS AND TOKENS" }
            Text { width: col.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; bottomPadding: 4
                   text: "A token raises a forge's rate limit (GitHub allows 60 requests an hour without one). Tokens are only sent to their own host and are never exported." }
            Repeater {
                model: backend.tokenHosts
                Item { width: col.width; height: 36
                    Icon { name: "key"; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { x: 26; anchors.verticalCenter: parent.verticalCenter; text: modelData.host; color: Theme.text; font.bold: true; font.pixelSize: 13 }
                    Text { x: 200; anchors.verticalCenter: parent.verticalCenter; text: modelData.hint; color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono }
                    TipButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; icon: "trash"; danger: true; tip: "Remove"
                                onClicked: root.confirmAction("removeToken", { host: modelData.host }) } }
            }
            Item { width: col.width; height: 46
                Field { id: tokenHost; width: 170; y: 4; placeholder: "github.com" }
                Field { id: tokenValue; x: 178; y: 4; width: col.width - 178 - 44; mono: true; placeholder: "Paste a token"; field.echoMode: TextInput.Password }
                TipButton { anchors.right: parent.right; y: 7; icon: "plus"; accent: true; tip: "Add token"
                            enabledButton: tokenHost.text.trim() !== "" && tokenValue.text.trim() !== ""
                            onClicked: { backend.setToken(tokenHost.text.trim(), tokenValue.text.trim()); tokenValue.text = "" } } }

            Section { text: "NOSTR RELAYS" }
            Text { width: col.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12; bottomPadding: 4
                   text: "Used to find ngit repositories in Explore, and later for ngit Sources and Nostr Trusts." }
            Repeater {
                model: root.p.relays || []
                Item { width: col.width; height: 32
                    Text { anchors.verticalCenter: parent.verticalCenter; text: modelData; color: Theme.text; font.pixelSize: 13; font.family: Theme.mono }
                    TipButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; icon: "trash"; danger: true; tip: "Remove"
                                onClicked: root.confirmAction("removeRelay", { relay: modelData }) } }
            }
            Item { width: col.width; height: 46
                Field { id: relayField; y: 4; width: col.width - 44; mono: true; placeholder: "wss://relay.example.com" }
                TipButton { anchors.right: parent.right; y: 7; icon: "plus"; accent: true; tip: "Add relay"; enabledButton: /^wss?:\/\/\S+/.test(relayField.text.trim())
                            onClicked: { backend.setPref("relays", (root.p.relays || []).concat([relayField.text.trim()])); relayField.text = "" } } }

            Section { id: secData; text: "DATA" }
            SettingRow { label: "Database"; hint: "Sources, Trusts, the Audit and the cache."
                Row { anchors.right: parent.right; spacing: 8
                    Text { width: root.slotWidth() - 88; elide: Text.ElideMiddle; text: root.home(root.loc.database); color: Theme.muted; font.pixelSize: 12
                           font.family: Theme.mono; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: Text.AlignRight }
                    Item { width: 32; height: 32 }
                    TipButton { icon: "folder"; tip: "Open folder"; onClicked: backend.openFolder(root.loc.dataDir) } } }
            SettingRow { label: "App log"; hint: "AppKata.log and AppKata-prev.log, 2 MB each."
                Row { anchors.right: parent.right; spacing: 8
                    Text { width: root.slotWidth() - 88; elide: Text.ElideMiddle; text: root.home(root.loc.logDir); color: Theme.muted; font.pixelSize: 12
                           font.family: Theme.mono; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: Text.AlignRight }
                    TipButton { icon: "open"; tip: "Show"; onClicked: backend.showAppLog() }
                    TipButton { icon: "folder"; tip: "Open folder"; onClicked: backend.openFolder(root.loc.logDir) } } }
            SettingRow { label: "Import and export"; hint: "Sources, Trusts with their Authorities, and settings, as JSON. Import also takes a list of URLs."
                Row { anchors.right: parent.right; spacing: 8
                    FButton { text: "Import…"; icon: "download"; onClicked: importPicker.open() }
                    FButton { text: "Export…"; icon: "save"; onClicked: exportPicker.open() } } }
            Item { width: 1; height: 8 }
        }
    }
    footer: [ FButton { text: "Close"; primary: true; onClicked: root.close() } ]
}
