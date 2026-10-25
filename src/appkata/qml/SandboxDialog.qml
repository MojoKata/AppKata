import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "."

// The per-app Sandbox dialog (requirement 17.3, mockups A21/A25): a template dropdown, a live
// summary, and a collapsed Customize disclosure that opens into Files / Connections / Devices & media
// / Services / Advanced. A settings surface you return to — not a wizard.
Dialog {
    id: root
    scrollBody: false                  // its own Flickable scrolls the body
    property string url: ""
    property var info: ({})
    property string tpl: "strict"          // the chosen template, "off", or "custom"
    property var gs: ({})                   // the working grant set (level, folders, network, sound, devices, caps, exec_deny)
    property bool customized: false
    property bool expanded: false
    signal saved(string url)                 // the install card adopts what was saved here
    // the template, when it is made for a folder the user picks: {mode, suggest} (17.3, review 2 F10)
    readonly property var folderTpl: (function () { const t = (info.templates || []).find(x => x.key === tpl); return t ? t.folder : null })()
    readonly property bool noFolderYet: !!folderTpl && gs.level !== "strict" && Object.keys(gs.folders || {}).filter(p => p !== "$cwd").length === 0
    title: "Sandbox"
    subtitle: info.levelLabel ? "" : ""
    app: backend.detail(url || "")
    dialogWidth: 640

    function openFor(u) { openWith(u, "") }
    function openWith(u, preset) {       // preset: the template the install card has picked, not yet saved
        url = u
        info = backend.sandboxInfo(u) || ({})
        tpl = info.template || "strict"
        gs = JSON.parse(JSON.stringify(info.grants || {}))
        customized = !!info.customized
        widened = false
        expanded = false
        flick.contentY = 0
        if (preset && preset !== tpl) pickTemplate(preset)
        open()
    }
    function scrollTo(what) {        // the tour: A25 shows Customize expanded, scrolled to the groups
        expanded = true
        Qt.callLater(() => { flick.contentY = what === "advanced" ? Math.max(0, flick.contentHeight - flick.height) : 0 })
    }
    function templateGrants(name) {
        if (name === "off") return { level: "off", folders: {}, network: false, ports: null, sound: [], devices: [], caps: [], exec_deny: true }
        const t = (info.templates || []).find(x => x.key === name)
        return t ? JSON.parse(JSON.stringify(t.grants)) : root.gs
    }
    function pickTemplate(name) {
        tpl = name; gs = templateGrants(name); customized = false; widened = false
    }
    function has(arr, v) { return (arr || []).indexOf(v) >= 0 }
    property bool widened: false            // Strict became Standard because a grant was added (17.2)
    function toggleIn(key, v, on) {
        let a = (gs[key] || []).slice()
        const i = a.indexOf(v)
        if (on && i < 0) a.push(v); else if (!on && i >= 0) a.splice(i, 1)
        setField(key, a)
    }
    // Strict has no folders, network, sound, services or writable app folder (17.2): a grant set at
    // that level drops them, so adding one here makes the set Standard with that grant, and says so,
    // rather than showing a folder the launcher would never bind.
    function widens(key, v) {
        if (key === "folders") return Object.keys(v || {}).length > 0
        if (key === "network" || key === "write_app") return !!v
        if (key === "sound" || key === "caps") return (v || []).length > 0
        if (key === "devices") return (v || []).some(d => d !== "x11")
        return false
    }
    function setField(key, v) {
        let g = Object.assign({}, gs); g[key] = v
        if (g.level === "strict" && widens(key, v)) { g.level = "standard"; tpl = "standard"; widened = true }
        gs = g; customized = true
    }
    function home(p) { return (p || "").replace(backend.locations.home, "~") }
    // a folder added here: read-only under a template made for reading one (media player), else read-write
    function addFolder(path) {
        let f = Object.assign({}, gs.folders || {})
        f[path] = folderTpl && folderTpl.mode === "ro" ? "ro" : "rw"
        setField("folders", f)
    }
    function flipMode(path) {      // a granted folder is read-only or read-write (17.2.1, review 2 F10)
        let f = Object.assign({}, gs.folders || {})
        f[path] = f[path] === "rw" ? "ro" : "rw"
        setField("folders", f)
    }
    function userFolder(key) { return (info.userFolders || []).find(x => x.key === key) }

    FolderDialog {
        id: folderPicker
        objectName: "folderPicker"           // the tests find it by name: PySide 6.11 names its class QFileDialogOptions
        onAccepted: root.addFolder(Theme.localPath(selectedFolder).replace(backend.locations.home, "~"))
    }

    Flickable {
        id: flick
        width: parent.width; height: Math.min(root.expanded ? 560 : 360, Overlay.overlay ? Overlay.overlay.height - 240 : 560)
        contentHeight: body.height; clip: true
        layer.enabled: contentY > 0 || contentHeight > height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; x: flick.width - 6 }
        Column {
            id: body
            width: flick.width - 16; spacing: 14

            Row {       // template dropdown + customized state + reset
                width: parent.width; spacing: 12
                Text { text: "Template"; color: Theme.text; font.bold: true; font.pixelSize: 13; width: 72
                       height: 28; verticalAlignment: Text.AlignVCenter }
                Select {
                    objectName: "templateSelect"                 // the dialog contract test picks through it
                    icon: root.tpl === "off" ? "ban" : "shieldCheck"
                    label: (function () { const t = (root.info.templates || []).find(x => x.key === root.tpl)
                                          return t ? t.label : root.tpl === "off" ? "Off" : "Custom" })()
                    options: (root.info.templates || []).map(t => [t.key, t.label]).concat([["off", "Off (no sandbox)"]])
                    onPicked: k => root.pickTemplate(k)
                }
                Text { visible: root.customized && root.tpl !== "off"; text: "· customized"; color: Theme.muted; font.pixelSize: 12
                       height: 28; verticalAlignment: Text.AlignVCenter }
                Row {       // nothing to reset a merged/bespoke set to
                    visible: root.customized && root.tpl !== "off" && root.tpl !== "custom"; spacing: 4
                    height: 28
                    Icon { name: "refresh"; size: 13; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "Reset to template"; color: Theme.accent; font.bold: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                           MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor
                                       onClicked: root.pickTemplate(root.tpl) } }
                }
            }
            Text { visible: !!root.info.reviewBy && root.tpl !== "off" && !root.info.hasSuggestion
                   text: "suggested by " + (root.info.reviewBy || ""); color: Theme.accent; font.pixelSize: 12 }
            Text { visible: root.widened; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                   text: "Strict has no folders, network, sound or services, so this is now Standard with what you added." }
            Rectangle {     // before Save: sandboxing an app that runs unsandboxed gives it an empty home (17.13, review 2 F13)
                visible: !!root.info.freshWarning && root.tpl !== "off"
                width: parent.width; height: fwTxt.height + 20; radius: 10; color: Theme.warnSoft
                Icon { x: 12; y: 12; name: "warn"; size: 15; color: Theme.warn; lineWidth: 1.6 }
                Text { id: fwTxt; x: 38; y: 11; width: parent.width - 50; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                       text: root.info.freshWarning || "" }
            }
            Rectangle {     // the reviewers suggest something else: adopt it in one click (17.11)
                visible: !!root.info.hasSuggestion
                width: parent.width; height: rsCol.height + 20; radius: 10; color: Theme.accentSoft
                Column { id: rsCol; x: 12; y: 10; width: parent.width - 24 - 110; spacing: 4
                    Text { text: (root.info.reviewBy || "A reviewer") + " suggests"; color: Theme.accent; font.bold: true; font.pixelSize: 12 }
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: (root.info.reviewSuggests || []).map(c => c[0]).join(" · ") } }
                FButton { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                          text: "Use theirs"; implicitHeight: 28; objectName: "useTheirs"
                          onClicked: { backend.useSuggestion(root.url); root.close() } }     // a suggested Off becomes the user's own choice (17.3.2)
            }

            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 13; lineHeight: 1.2
                   objectName: "blurb"
                   // a customized template is described by its changes, not the template's own blurb: a
                   // widened Strict read "Network and notifications" over a set with neither (review 2's nit)
                   text: (function () { const t = (root.info.templates || []).find(x => x.key === root.tpl)
                                        return root.tpl === "off" ? "No sandbox — the app runs with your full account."
                                               : t && root.customized ? backend.describeSandbox(root.tpl, root.gs) + "."
                                               : t ? t.blurb : "Your own mix of access, built from a template." })() }
            Flow {      // a template made for a folder the user picks: offer it in place (17.3, review 2 F10)
                visible: root.noFolderYet; width: parent.width; spacing: 8; objectName: "pickFolder"
                Text { text: "Pick its folder:"; color: Theme.text; font.bold: true; font.pixelSize: 12; height: 28
                       verticalAlignment: Text.AlignVCenter }
                Repeater {
                    model: root.folderTpl ? root.folderTpl.suggest.map(k => root.userFolder(k)).filter(x => !!x) : []
                    FButton { text: modelData.label; icon: "folder"; implicitHeight: 28; onClicked: root.addFolder(modelData.path) }
                }
                FButton { text: "Other…"; implicitHeight: 28; onClicked: folderPicker.open() }
            }
            Flow {      // live summary chips
                width: parent.width; spacing: 6
                Repeater {
                    model: backend.summaryChips(root.gs, root.url, root.tpl)
                    Pill { text: modelData[0]; icon: modelData[1]; u: 0.92
                           color: modelData[2] === "ok" ? Theme.okSoft : modelData[2] === "warn" ? Theme.warnSoft : Theme.track
                           fg: modelData[2] === "ok" ? Theme.ok : modelData[2] === "warn" ? Theme.warn : Theme.muted }
                }
            }
            Rectangle {     // the X11 / wlroots caveat (17.9)
                visible: !!(root.info.sessionWarning && root.info.sessionWarning.text) && root.tpl !== "off"
                width: parent.width; height: swText.height + 20; radius: 10; color: Theme.warnSoft
                Icon { x: 12; y: 12; name: "info"; size: 15; color: Theme.warn }
                Text { id: swText; x: 38; y: 11; width: parent.width - 50; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                       text: root.info.sessionWarning ? root.info.sessionWarning.text : "" }
            }

            Rectangle { visible: root.tpl !== "off"; width: parent.width; height: 1; color: Theme.border }
            Item {      // Customize disclosure
                visible: root.tpl !== "off"; width: parent.width; height: 22
                Row {
                    anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; spacing: 10
                    Icon { name: root.expanded ? "chevDown" : "chevRight"; size: 14; lineWidth: 2; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "Customize"; color: Theme.text; font.bold: true; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                    Text { visible: !root.expanded; text: "Files · Connections · Devices & media · Services · Advanced"
                           color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.expanded = !root.expanded }
            }

            Column {    // the Customize groups (A25)
                visible: root.expanded && root.tpl !== "off"; width: parent.width; spacing: 4

                SbxHeader { text: "FILES" }
                Repeater {
                    model: root.info ? (function () { const f = root.gs.folders || {}
                                        return Object.keys(f).map(p => [p, f[p]]) })() : []
                    Row { width: body.width; height: 34; spacing: 8
                        Icon { name: "folder"; size: 15; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: modelData[0] === "$cwd" ? "The folder it's run in" : modelData[0]; color: Theme.text; font.pixelSize: 13
                               anchors.verticalCenter: parent.verticalCenter; font.family: modelData[0] === "$cwd" ? undefined : Theme.mono }
                        Pill { text: modelData[1] === "rw" ? "read-write" : "read-only"; color: Theme.track; fg: Theme.muted; u: 0.82
                               anchors.verticalCenter: parent.verticalCenter }
                        TipButton { icon: modelData[1] === "rw" ? "lock" : "pencil"; width: 26; height: 26
                                    tip: modelData[1] === "rw" ? "Make read-only" : "Make read-write"
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: root.flipMode(modelData[0]) }
                        TipButton { visible: modelData[0] !== "$cwd"; icon: "trash"; danger: true; tip: "Remove"; width: 26; height: 26
                                    anchors.verticalCenter: parent.verticalCenter
                                    onClicked: { let f = Object.assign({}, root.gs.folders); delete f[modelData[0]]; root.setField("folders", f) } }
                    }
                }
                Flow {      // the user folders in one click, by this system's names for them (17.2.1, decision 4)
                    width: body.width; spacing: 8
                    Repeater {
                        model: (root.info.userFolders || []).filter(x => !(x.path in (root.gs.folders || {})))
                        FButton { text: modelData.label; icon: "folder"; implicitHeight: 26; onClicked: root.addFolder(modelData.path) }
                    }
                    Text { text: "Add a folder…"; color: Theme.accent; font.bold: true; font.pixelSize: 12; height: 26
                           verticalAlignment: Text.AlignVCenter
                           MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: folderPicker.open() } }
                }

                SbxHeader { text: "CONNECTIONS" }
                SbxToggle { label: "Network"; ic: "globe"; hint: "Let it reach the internet and the local network."
                            on: !!root.gs.network; onToggled: on => root.setField("network", on) }
                SbxToggle { label: "Limit to ports"; ic: "globe"; badge: "Later"; disabled: true
                            hint: "Allow only certain ports (Landlock, kernel ≥ 6.7). Coming in a later release." }
                SbxToggle { label: "Desktop services (portals)"; ic: "panel"; on: root.gs.level !== "strict"; disabled: true
                            hint: root.gs.level === "strict" ? "Strict has no session bus: the app can't open links or files on this computer, notify, or use any desktop service. Pick Standard or a template for that."
                                                            : "Opening links and files on this computer, settings, printing — always on at Standard. Notifications and keeping the screen awake are the switches below; nothing else on the session bus." }

                SbxHeader { text: "DEVICES & MEDIA" }
                SbxToggle { label: "Play sound"; ic: "wave"; hint: "Send audio to the speakers. Not yet separable from recording: an app that can play sound can also record."
                            on: root.has(root.gs.sound, "play"); onToggled: on => root.toggleIn("sound", "play", on) }
                SbxToggle { label: "Microphone / recording"; ic: "wave"; on: root.has(root.gs.sound, "record")
                            hint: "Record audio from the microphone. Today any sound access allows this; AppKata can't block it separately yet."
                            onToggled: on => root.toggleIn("sound", "record", on) }
                SbxToggle { label: "Camera"; ic: "camera"; on: root.has(root.gs.devices, "camera")
                            hint: "The camera devices themselves. Without this the app has no camera: the camera portal is not open to sandboxed apps."
                            onToggled: on => root.toggleIn("devices", "camera", on) }
                SbxToggle { label: "X11 apps (XWayland)"; ic: "panel"; on: root.has(root.gs.devices, "x11")
                            hint: "On Wayland, also offer X11 for apps that can't use Wayland. Such an app can see and type into other X11 windows (not Wayland ones). Off withholds the socket and the cookie; with the network on, an app can still reach the X server if the compositor's Xwayland takes connections without a cookie (wlroots does, GNOME and KDE don't)."
                            onToggled: on => root.toggleIn("devices", "x11", on) }

                SbxHeader { text: "SERVICES · what the app may use on the session bus" }
                SbxToggle { label: "Tray icon"; ic: "panel"; on: root.has(root.gs.caps, "tray")
                            hint: "Show a status-bar icon (StatusNotifierItem) and own its own bus name. Two sandboxed apps with a tray icon running at once can collide on that name, as with Flatpak."
                            onToggled: on => root.toggleIn("caps", "tray", on) }
                SbxToggle { label: "Media keys"; ic: "play"; on: root.has(root.gs.caps, "mpris")
                            hint: "Play/pause and track info on the keyboard and lock screen (MPRIS)."
                            onToggled: on => root.toggleIn("caps", "mpris", on) }
                SbxToggle { label: "Notifications"; ic: "info"; on: root.has(root.gs.caps, "notifications")
                            hint: "Show desktop notifications, through the notification portal or the desktop's own notification service. Without it the app's notifications never appear."
                            onToggled: on => root.toggleIn("caps", "notifications", on) }
                SbxToggle { label: "Keep the screen awake"; ic: "clock"; on: root.has(root.gs.caps, "inhibit")
                            hint: "Inhibit the screensaver while it's doing something (video, a transfer)."
                            onToggled: on => root.toggleIn("caps", "inhibit", on) }
                SbxToggle { label: "Saved passwords"; ic: "key"; on: root.has(root.gs.caps, "secrets")
                            hint: "Store and read passwords in your keyring (org.freedesktop.secrets). The keyring has no per-app walls: the app can read every unlocked password in it, not only its own."
                            onToggled: on => root.toggleIn("caps", "secrets", on) }
                SbxToggle { label: "Password service"; ic: "key"; warn: true; on: root.has(root.gs.caps, "secrets-provide")
                            hint: "Offer the secret service (org.freedesktop.secrets) to other apps, e.g. KeePassXC. The app then holds every other app's saved passwords."
                            onToggled: on => root.toggleIn("caps", "secrets-provide", on) }

                SbxHeader { text: "ADVANCED · extra hardening inside bwrap (Landlock)" }
                SbxToggle { label: "Block running programs it writes"; ic: "shield"; badge: "Later"; disabled: true; on: !!root.gs.exec_deny
                            hint: "A second lock (Landlock) so the app can write its data but not execute what it drops. Coming later." }
                SbxToggle { label: "Let it change its own files"; ic: "warn"; warn: true; on: !!root.gs.write_app
                            hint: "Only for apps that keep settings or data beside the program; it could then change its own code. An AppImage's own file stays read-only, and AppKata updates a sandboxed app itself."
                            onToggled: on => root.setField("write_app", on) }
            }

            Rectangle { visible: root.tpl !== "off"; width: parent.width; height: 1; color: Theme.border }
            Item {      // its home folder
                visible: root.tpl !== "off"; width: parent.width; height: 30
                Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                       text: "Its home folder"; color: Theme.text; font.bold: true; font.pixelSize: 13 }
                Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 120; elide: Text.ElideMiddle
                       horizontalAlignment: Text.AlignRight; text: root.home(root.info.home || ""); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono }
            }
        }
    }
    footerLeft: Text { width: 300; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                       text: root.info.installed ? "Applies the next time " + (root.app ? root.app.name : "the app") + " starts."
                                                 : "Applies when you install it." }
    footer: [
        FButton { text: "Cancel"; onClicked: root.close() },
        FButton {
            text: "Save"; primary: true; objectName: "save"      // objectName: the dialog contract test presses it
            onClicked: {
                // "custom" names a merged or bespoke set, not a template to resolve: send the set itself (R4-1);
                // a customized template goes with its name, saved as it plus the changes (review 2, F10)
                if (root.tpl === "off") backend.setSandbox(root.url, { template: "off" })
                else if (!root.customized && root.tpl !== "custom") backend.setSandbox(root.url, { template: root.tpl, overrides: {} })
                else if (root.tpl !== "custom") backend.setSandbox(root.url, { template: root.tpl, custom: root.gs })
                else backend.setSandbox(root.url, { custom: root.gs })
                root.saved(root.url)
                root.close()
            }
        }
    ]

    component SbxHeader: Text {
        width: body.width; color: Theme.faint; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.1
        topPadding: 12; bottomPadding: 2
    }
    component SbxToggle: Item {
        id: tg
        property string label
        property string hint: ""
        property string ic: "gear"
        property string badge: ""
        property bool on: false
        property bool warn: false
        property bool disabled: false
        signal toggled(bool on)
        width: body.width; height: Math.max(44, hintText.height + 30)
        Icon { x: 0; y: 4; name: tg.ic; size: 16; color: tg.warn ? Theme.warn : Theme.muted }
        Text { id: lab; x: 26; y: 2; text: tg.label; color: tg.warn ? Theme.warn : Theme.text; font.bold: true; font.pixelSize: 14 }
        Pill { visible: tg.badge !== ""; text: tg.badge; x: 26 + lab.implicitWidth + 8; y: 1; color: Theme.accentSoft; fg: Theme.accent; u: 0.76 }
        Text { id: hintText; x: 26; y: 22; width: body.width - 90; wrapMode: Text.WordWrap; text: tg.hint
               color: tg.warn ? Theme.warn : Theme.muted; font.pixelSize: 12 }
        Switch {
            id: sw; checked: tg.on; enabled: !tg.disabled; opacity: tg.disabled ? 0.45 : 1
            anchors.right: parent.right; y: 2; padding: 0; spacing: 0
            onToggled: tg.toggled(checked)
            indicator: Rectangle {
                x: sw.width - width; implicitWidth: 38; implicitHeight: 22; radius: 11
                color: sw.checked ? Theme.accent : Theme.track; border.color: sw.checked ? Theme.accent : Theme.borderStrong
                Rectangle { x: sw.checked ? 18 : 2; y: 2; width: 18; height: 18; radius: 9; color: "#ffffff" }
            }
        }
    }
}
