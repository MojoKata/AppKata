import QtQuick
import QtQuick.Controls.Basic
import "."

// The App Detail panel (requirement 5.6, 5.7), shared by Apps and Catalog.
Rectangle {
    id: root
    property string url: ""
    property var d: ({})
    property int expanded: 0
    property alias menu: moreMenu
    property bool pencilHover: false
    property int versionsShown: 0
    property int demoVersionTip: -1      // the tour
    function scrollTo(what) {        // the tour
        const target = what === "versions" ? versionsHead : what === "reviews" ? reviewsHead : what === "sandbox" ? sandboxHead : null
        flick.contentY = target ? Math.max(0, Math.min(target.y - 8, flick.contentHeight - flick.height)) : 0
    }
    signal closed()
    signal review(string url)
    signal openTrust(int id)
    signal openSource(string url)
    signal confirmUninstall(string url)
    signal confirmRemoveVersion(string url, string version)
    signal pickTag(string tag)
    signal installOptions(string url)
    signal openSandbox(string url)
    signal showLaunchCommand(string url)          // 17.4's "Show the launch command" (review 2, F11)
    readonly property var sbx: (root.d.sandbox && root.d.sandbox.applicable) ? root.d.sandbox : null
    function refresh() { d = url ? backend.detail(url) : ({}); }
    onUrlChanged: { expanded = 0; refresh(); flick.contentY = 0; versionsShown = d.versionsShown || 6 }
    Connections { target: backend; function onChanged() { root.refresh() } }
    readonly property var busy: backend.busy[url]
    readonly property bool installed: ["installed", "update", "held", "pinned", "selfupdating", "system"].indexOf(d.state) >= 0
    readonly property bool selfUpdating: d.state === "selfupdating"
    readonly property var ch: d.ch || null          // installed from a package channel (requirement 16)
    readonly property bool systemUpdated: d.state === "system"
    color: Theme.surface
    Rectangle { width: 1; height: parent.height; color: Theme.border }
    Rectangle { z: -1; anchors.fill: parent; anchors.leftMargin: -14; color: "#000000"; opacity: Theme.dark ? 0.18 : 0.04 }

    Text { x: 28; y: 26; text: "APP DETAILS"; color: Theme.faint; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.2 }
    Row {
        anchors.right: parent.right; anchors.rightMargin: 28; y: 14; spacing: 8; z: 5
        IconButton {
            id: pencil
            round: true; icon: "pencil"; iconSize: 14; lineWidth: 1.6
            active: root.pencilHover
            onClicked: root.review(root.url)
            property bool hovered: false
            HoverHandler { onHoveredChanged: pencil.hovered = hovered }
            Rectangle {     // tooltip
                visible: pencil.hovered || root.pencilHover
                anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.bottom; anchors.topMargin: 8
                width: tipT.implicitWidth + 20; height: 26; radius: 7; color: Theme.tipBg; z: 30
                Text { id: tipT; anchors.centerIn: parent; text: "Write a review"; color: Theme.tipFg; font.bold: true; font.pixelSize: 12 }
            }
        }
        IconButton {
            visible: root.installed
            round: true; icon: "dots"; iconSize: 14; active: moreMenu.visible
            onClicked: moreMenu.open()
            PopMenu {
                id: moreMenu
                menuWidth: 240; y: 36; x: -200
                items: [
                    { key: "pin", icon: "pin", text: root.d.pinned ? "Unpin" : "Pin at " + (root.d.installed || ""),
                      enabled: !(root.ch && root.ch.kind === "package"),          // 16.5.6
                      note: root.ch && root.ch.kind === "package" ? "Pinning a package would change the whole system"
                            : root.d.pinned ? "Updates resume" : root.ch ? "Also stops the system's updates" : "No updates until unpinned" },
                    { key: "opts", icon: "gear", text: "Install options…",
                      note: root.ch ? root.ch.label + " · " + (root.ch.updates === "system" ? "updated by the system" : "AppKata updates it")
                            : root.d.asset ? root.d.assetLabel + " · " + (root.d.asset.category === "portable" ? "portable" : "system package") : "" },
                    { key: "page", icon: "open", text: "Open project page" }]
                onTriggered: key => {
                    if (key === "pin") backend.setPinned(root.url, !root.d.pinned)
                    else if (key === "opts") root.installOptions(root.url)
                    else Qt.openUrlExternally(root.url)
                }
            }
        }
        IconButton { round: true; icon: "x"; onClicked: root.closed() }
    }

    Flickable {
        id: flick
        x: 28; y: 56; width: parent.width - 56; height: parent.height - y
        contentHeight: col.height + 30; clip: true
        layer.enabled: contentY > 0       // vector icons ignore clipping in the software renderer; a layer clips them
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; x: flick.width + 6 }      // requirement 5.7
        Column {
            id: col
            width: flick.width
            spacing: 14
            Rectangle {   // veto banner (requirement 12.6.1); for the version you have, who and why (10.6.5)
                readonly property var av: root.d.avoid || null
                visible: !!root.d.vetoed
                width: parent.width; height: av ? avCol.height + 24 : 44; radius: 11; color: Theme.errSoft; border.color: Theme.err
                Icon { x: 14; y: parent.av ? 13 : 13; name: "warn"; color: Theme.err; lineWidth: 1.7 }
                Column {
                    id: avCol
                    x: 42; y: parent.av ? 12 : 14; width: parent.width - 56; spacing: 6
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.err; font.bold: true; font.pixelSize: 13
                           text: parent.parent.av ? "A trusted reviewer says to avoid the version you have (" + root.d.installed + ")" : "A trusted reviewer says to avoid this app" }
                    Text { visible: !!parent.parent.av; width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: parent.parent.av ? (parent.parent.av.own ? "You" : parent.parent.av.by) + " · Avoid" + (parent.parent.av.from ? " from " + parent.parent.av.from : "")
                                 + (parent.parent.av.note ? " · “" + parent.parent.av.note + "”" : "") : "" }
                    FButton { visible: !!parent.parent.av && !!root.d.avoidUpdateTo && !root.busy; text: "Update to " + (root.d.avoidUpdateTo || ""); icon: "update"; primary: true
                              implicitHeight: 32; onClicked: backend.installVersion(root.url, root.d.avoidUpdateTo) }
                }
            }
            Rectangle {   // reviewers suggest a sandbox change; the update kept your grants (17.11, A22)
                visible: !!root.sbx && !!root.sbx.reviewBadge
                width: parent.width; height: Math.max(rbCol.height, rbButtons.height + 4) + 24; radius: 11; color: Theme.accentSoft; border.color: Theme.accent
                Icon { x: 14; y: 14; name: "shield"; color: Theme.accent; lineWidth: 1.7 }
                Column { id: rbCol; x: 42; y: 12; width: parent.width - 56 - 108; spacing: 5
                    Text { width: parent.width; wrapMode: Text.WordWrap; text: "Reviewers suggest a sandbox change"; color: Theme.accent; font.bold: true; font.pixelSize: 13 }
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: root.sbx ? root.sbx.reviewBadgeText || "" : "" } }
                Column { id: rbButtons; anchors.right: parent.right; anchors.rightMargin: 12; y: 14; spacing: 6
                    FButton { anchors.right: parent.right; text: "Review…"; primary: true; implicitHeight: 30; onClicked: root.openSandbox(root.url) }
                    FButton { anchors.right: parent.right; text: "Keep mine"; implicitHeight: 30; onClicked: backend.keepSandbox(root.url) } }
            }
            // On a broken host an app that has a launcher keeps it (17.10, review 2 F16): it can't start,
            // rather than run unsandboxed unasked, and the banners say which
            Rectangle {   // AppKata's profile beside the system's own (an upgrade): no sandbox starts (17.10.2)
                visible: !!root.sbx && root.sbx.support && root.sbx.support.status === "conflict" && root.installed
                width: parent.width; height: cfCol.height + 24; radius: 11; color: Theme.warnSoft; border.color: Theme.warn
                Icon { x: 14; y: 14; name: "warn"; color: Theme.warn; lineWidth: 1.7 }
                Column { id: cfCol; x: 42; y: 12; width: parent.width - 56 - 96; spacing: 5
                    Text { text: root.sbx && root.sbx.active ? "Can't start — AppArmor needs a repair" : "Not sandboxed — AppArmor needs a repair"
                           color: Theme.warn; font.bold: true; font.pixelSize: 13 }
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: "AppKata's AppArmor profile from before this system's upgrade now conflicts with the system's own, so no sandbox can start. Repair removes AppKata's (asks for your password once)."
                                 + (root.sbx && root.sbx.active ? " Until then it can't start; set its sandbox to Off to run it unsandboxed." : "") } }
                FButton { anchors.right: parent.right; anchors.rightMargin: 12; y: 14; text: "Repair…"; primary: true; implicitHeight: 30
                          onClicked: backend.repairSandboxSupport() }
            }
            Rectangle {   // the system needs a one-time setup; running Off until then (17.10, A24)
                visible: !!root.sbx && root.sbx.support && root.sbx.support.status === "setup-needed" && root.installed
                width: parent.width; height: snCol.height + 24; radius: 11; color: Theme.warnSoft; border.color: Theme.warn
                Icon { x: 14; y: 14; name: "warn"; color: Theme.warn; lineWidth: 1.7 }
                Column { id: snCol; x: 42; y: 12; width: parent.width - 56 - 96; spacing: 5
                    Text { text: root.sbx && root.sbx.active ? "Can't start — system setup needed" : "Not sandboxed — system setup needed"
                           color: Theme.warn; font.bold: true; font.pixelSize: 13 }
                    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: "This system blocks the sandbox until a one-time setup (asks for your password once; it lets programs use bubblewrap to create user namespaces again). "
                                 + (root.sbx && root.sbx.active ? "Until then it can't start; set its sandbox to Off to run it unsandboxed." : "Until then it runs unsandboxed.")
                                 + (root.sbx && root.sbx.support && root.sbx.support.waitingNote ? " " + root.sbx.support.waitingNote : "") } }
                FButton { anchors.right: parent.right; anchors.rightMargin: 12; y: 14; text: "Enable…"; primary: true; implicitHeight: 30
                          onClicked: backend.setupSandboxSupport() }
            }
            Item {        // hero image with the icon over its lower-left corner (requirement 5.7.2)
                width: parent.width; height: 150 + 36
                Rectangle {
                    id: hero
                    width: parent.width; height: 150; radius: 14; clip: true
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: root.d.c1 || "#8089ff" }
                        GradientStop { position: 1; color: root.d.c2 || "#4f46e5" }
                    }
                    Rectangle { anchors.fill: parent; radius: 14; color: "transparent"; border.color: Theme.border; z: 3 }
                    Image {
                        id: heroImg
                        anchors.fill: parent
                        source: Theme.fileUrl(root.d.hero || "")
                        fillMode: Image.PreserveAspectCrop; asynchronous: true
                        sourceSize.width: 900; smooth: true
                        horizontalAlignment: Image.AlignHCenter; verticalAlignment: Image.AlignTop
                    }
                    Rectangle {
                        visible: heroImg.status !== Image.Ready
                        x: parent.width * 0.62; y: -parent.height * 0.7; width: parent.height * 1.8; height: width; radius: width / 2
                        color: "#ffffff"; opacity: 0.10
                    }
                    Rectangle {
                        anchors.fill: parent
                        gradient: Gradient { GradientStop { position: 0.55; color: "transparent" } GradientStop { position: 1; color: Theme.alpha("#000000", Theme.dark ? 0.35 : 0.18) } }
                    }
                }
                Rectangle {
                    x: 16; y: 112; width: 68; height: 68; radius: 20; color: Theme.surface
                    AppIcon { anchors.centerIn: parent; app: root.d; size: 60 }
                }
            }
            Column {
                width: parent.width; spacing: 4
                Text { text: root.d.name || ""; color: Theme.text; font.pixelSize: 24; font.bold: true; width: parent.width; elide: Text.ElideRight }
                Text { text: (root.d.host || "") + "/" + (root.d.repo || ""); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono; width: parent.width; elide: Text.ElideMiddle }
            }
            Flow {       // From: origins, linking to Source and Trusts (requirement 5.7.3, 2.9.5)
                width: parent.width; spacing: 6
                Text { text: "From"; color: Theme.faint; font.bold: true; font.pixelSize: 12; height: 22; verticalAlignment: Text.AlignVCenter; width: 38 }
                Rectangle {
                    visible: !!root.d.src
                    height: 22; width: srcRow.implicitWidth + 18; radius: 11; color: Theme.track
                    Row { id: srcRow; anchors.centerIn: parent; spacing: 5
                        Icon { name: "branch"; size: 12; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: "Source"; color: Theme.text; font.bold: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.openSource(root.url) }
                }
                Repeater {
                    model: root.d.trusts || []
                    Rectangle {
                        height: 22; width: tRow.implicitWidth + 16; radius: 11; color: Theme.track
                        Row { id: tRow; anchors.centerIn: parent; spacing: 5
                            Avatar { person: modelData.avatars[0]; size: 15; ring: Theme.track; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData.short; color: Theme.accent; font.bold: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                            Icon { name: "chevRight"; size: 11; lineWidth: 1.8; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter } }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.openTrust(modelData.id) }
                    }
                }
            }
            Text {      // the installer's own record disagrees (requirement 15.8.3)
                visible: !!root.d.reportedVersion; width: parent.width; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                text: "Windows reports version " + (root.d.reportedVersion || "") + "."
            }
            Flow {      // chips
                width: parent.width; spacing: 6
                Pill { visible: root.d.verify === "signed"; text: "Verified" + (root.d.signer ? " · " + root.d.signer : "")       // Authenticode (requirement 15.11)
                       tip: root.ch ? "Signed by " + (root.ch.kind === "flatpak" ? "Flathub" : root.ch.distro || "the distribution") : ""    // 16.3.6
                       icon: "shieldCheck"; color: Theme.okSoft; fg: Theme.ok; u: 0.92 }
                Pill { visible: root.d.verify === "checksum"; text: "Checksum"; icon: "check"; color: Theme.accentSoft; fg: Theme.accent; u: 0.92 }
                Pill { visible: root.d.verify === "unverified" && !!root.d.asset; text: "Unverified"; icon: "warn"; color: Theme.warnSoft; fg: Theme.warn; u: 0.92 }
                Pill { visible: !!root.d.foreign; text: "Installed outside AppKata"; icon: "info"; color: Theme.warnSoft; fg: Theme.warn; u: 0.92 }
                Pill {      // the channel and who publishes it (requirement 16.6.1)
                    visible: !!root.ch; text: root.ch ? root.ch.label : ""; icon: root.ch && root.ch.verified ? "shieldCheck" : ""
                    color: root.ch && root.ch.verified ? Theme.okSoft : Theme.track; fg: root.ch && root.ch.verified ? Theme.ok : Theme.muted; u: 0.92 }
                Pill { visible: !!root.ch && root.ch.kind === "flatpak"; text: "Flatpak"; color: Theme.track; fg: Theme.muted; u: 0.92 }
                Pill {      // who updates it (requirement 16.5.1)
                    visible: !!root.ch
                    text: !root.ch ? "" : root.ch.updates === "system" ? "Updated by the system" : root.ch.updates === "not-updated" ? "Not updated automatically"
                          : root.ch.updates === "held" ? "Held by the system" : "AppKata updates it"
                    icon: root.ch && root.ch.updates === "not-updated" ? "warn" : root.ch && root.ch.updates === "held" ? "pin" : "sync"
                    color: root.ch && root.ch.updates === "not-updated" ? Theme.warnSoft : Theme.track
                    fg: root.ch && root.ch.updates === "not-updated" ? Theme.warn : Theme.muted; u: 0.92 }
                Pill { visible: !!root.ch && !!root.ch.extraData; text: "Downloads its program from " + (root.ch ? root.ch.extraData : "")    // 16.6.2
                       icon: "warn"; color: Theme.warnSoft; fg: Theme.warn; u: 0.92 }
                Pill { visible: !!root.ch && root.ch.check === "mismatch"; text: "Doesn't match the project"; icon: "warn"     // 16.1.4
                       tip: root.ch ? root.ch.checkDetail || "" : ""; color: Theme.warnSoft; fg: Theme.warn; u: 0.92 }
                Pill { visible: (root.d.sameFileAs || []).length > 0; icon: "check"; color: Theme.okSoft; fg: Theme.ok; u: 0.92     // 10.3.4
                       text: "Same file as " + (root.d.sameFileAs || []).join(", ") + " reviewed" }
                Pill {      // how it's (or it would be) installed (requirement 4.9.5)
                    visible: !root.ch && (!!root.d.asset || !!root.d.installKind)
                    readonly property string k: root.d.installKind || (root.d.asset ? root.d.asset.kind : "")
                    readonly property bool port: ["appimage", "tarball", "zip", "dmg"].indexOf(k) >= 0 || (!!root.d.asset && root.d.asset.exeKind === "portable")
                    text: k.replace("appimage", "AppImage").replace("tarball", "tar.gz") + " · " + (port ? "portable" : "system package")
                    color: Theme.track; fg: Theme.muted; u: 0.92 }
                Pill { visible: root.installed && (root.d.scope === "everyone" || (!!root.ch && root.ch.system)); text: "For everyone"; color: Theme.track; fg: Theme.muted; u: 0.92 }   // 15.4
                Pill {      // the Visual C++ run-time (requirement 15.18.2)
                    visible: !!root.d.msvcrt; text: "MSVCRT"; tip: "Microsoft Visual C++ Run-time" + (root.d.msvcrtMissing ? ": not installed" : "")
                    icon: root.d.msvcrtMissing ? "warn" : ""; showTip: !!root.d.tourTip
                    color: root.d.msvcrtMissing ? Theme.warnSoft : Theme.track; fg: root.d.msvcrtMissing ? Theme.warn : Theme.muted; u: 0.92
                    onClicked: if (root.d.msvcrtMissing) backend.msvcrtNeeded({ url: root.d.url, name: root.d.name })
                }
                Pill { visible: !!root.d.pinned; text: "Pinned at " + root.d.pinned; icon: "pin"; color: Theme.track; fg: Theme.muted; u: 0.92 }
                Pill { visible: !!root.d.trackOnly; text: "Track only"; color: Theme.track; fg: Theme.muted; u: 0.92 }
                Pill { visible: root.selfUpdating; text: "Updates itself"; icon: "sync"; color: Theme.track; fg: Theme.muted; u: 0.92 }
                Pill { visible: root.installed && !!root.sbx && root.sbx.level !== "off" && !!root.sbx.active      // 17.4
                       text: "Sandboxed"; icon: "shieldCheck"; color: Theme.okSoft; fg: Theme.ok; u: 0.92 }
                Pill { visible: root.installed && !!root.sbx && root.sbx.level !== "off" && !root.sbx.active     // runs Off (17.10)
                       text: "Not sandboxed"; icon: "warn"; color: Theme.warnSoft; fg: Theme.warn; u: 0.92 }
                Pill { visible: !!root.d.archived; text: "Archived"; color: Theme.track; fg: Theme.muted; u: 0.92 }
            }
            Column {     // actions (requirement 5.7.4)
                width: parent.width; spacing: 8
                Row {
                    spacing: 8
                    FButton { visible: !root.installed && !root.d.foreign; text: root.busy ? Theme.busyLabel(root.busy) : "Install"; icon: "download"
                              primary: !root.d.vetoed; danger: !!root.d.vetoed; enabledButton: !root.busy && !!root.d.asset && !root.d.trackOnly
                              onClicked: backend.install(root.url) }
                    FButton { visible: !!root.d.foreign && !root.d.adoptable; text: "Installed outside AppKata"; icon: "ban"; enabledButton: false }
                    FButton { visible: !!root.d.foreign && !!root.d.adoptable; text: "Adopt"; icon: "check"; primary: true      // 16.4.2
                              tip: "Track this copy with AppKata, without reinstalling"; onClicked: backend.adopt(root.url) }
                    FButton { visible: root.d.state === "update"; text: root.busy ? Theme.busyLabel(root.busy) : "Update"; icon: "update"
                              primary: !root.d.updateAvoided; danger: !!root.d.updateAvoided
                              enabledButton: !root.busy; onClicked: backend.update(root.url) }
                    Pill { visible: root.d.state === "update" && !!root.d.updateAvoided && !root.busy; anchors.verticalCenter: parent.verticalCenter
                           text: "Avoid " + (root.d.updateTo || ""); icon: "warn"; color: Theme.errSoft; fg: Theme.err; u: 0.92 }
                    FButton { visible: !!root.busy && root.busy.phase !== "Installing"; text: root.busy && root.busy.phase === "Waiting" ? "Remove from queue" : "Cancel"
                              icon: "x"; onClicked: backend.cancelInstall(root.url) }
                    FButton { visible: !!root.d.restartNeeded; text: "Restart AppKata"; icon: "refresh"; primary: true; onClicked: backend.restartSelf() }
                    FButton { visible: root.installed && !root.d.self && !root.busy; text: "Uninstall"; icon: "trash"; danger: true
                              enabledButton: !root.d.uninstallBlocker; tip: root.d.uninstallBlocker || ""; onClicked: root.confirmUninstall(root.url) }
                    FButton { visible: root.installed && !root.d.self && !root.busy; text: "Open"; icon: "open"; onClicked: backend.openApp(root.url) }
                }
                Rectangle {     // install progress (requirement 4.8.1)
                    visible: !!root.busy; width: parent.width; height: 5; radius: 2.5; color: Theme.track
                    Rectangle { width: parent.width * (root.busy ? root.busy.progress : 0); height: 5; radius: 2.5
                                color: root.busy && root.busy.phase === "Waiting" ? Theme.faint : Theme.accent }
                }
                Text { visible: !!root.busy && Theme.busyDetail(root.busy) !== ""; text: Theme.busyDetail(root.busy); color: Theme.muted; font.pixelSize: 12 }
                Text {      // the app updates itself (requirement 4.10)
                    visible: root.selfUpdating; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                    text: "AppKata only tracks its releases" + (root.d.newer ? " (" + root.d.version + " is out)" : "") + " and leaves updating to the app. "
                          + (root.d.autoUpdateBy === "you" ? "You marked it as updating itself in Install options." : root.d.autoUpdateBy ? root.d.autoUpdateBy + " says it updates itself; change this in Install options." : "")
                }
                Text {      // it would update itself, but runs sandboxed, so AppKata does (17.12, review 2 F3)
                    visible: !!root.d.sandboxedUpdates && !root.busy; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                    text: "It would update itself, but it runs sandboxed and can't change its own files, so AppKata updates it. Switched Off, it updates itself again."
                }
                Text {      // a channel install: who updates it, and versions (requirement 16.5, 16.7.2)
                    visible: !!root.ch && !root.busy; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                    text: !root.ch ? "" : [
                        root.ch.updates === "system" ? (root.ch.updatesBy || "The system") + " updates this " + (root.ch.kind === "flatpak" ? "Flatpak" : "package")
                                                      + " automatically. AppKata shows new releases" + (root.d.newer ? " (" + root.d.version + " is out)" : "") + " but leaves updating to it."
                        : root.ch.updates === "not-updated" ? "Nothing on this computer updates it automatically, so AppKata offers its updates."
                        : root.ch.updates === "held" ? "It's held at this version by the system's package settings, so it gets no updates."
                        : root.ch.updatesBy ? "AppKata updates it. " + root.ch.updatesBy + " may update it too; AppKata can't turn that off." : "",
                        root.ch.updatedBy ? "Updated by " + root.ch.updatedBy + (root.ch.updatedAt ? " on " + Theme.shortDate(root.ch.updatedAt) : "") + "." : "",
                        root.ch.pkgVersion ? (root.ch.distro || "Package") + " " + root.ch.pkgVersion + " · project " + (root.d.version || "?")
                                             + (root.ch.behind ? " (" + root.ch.behind + " release" + (root.ch.behind > 1 ? "s" : "") + " behind)" : "") : "",
                        root.ch.check === "mismatch" ? root.ch.checkDetail : "",
                        root.d.uninstallBlocker ? root.d.uninstallBlocker + ", so AppKata won't uninstall it." : ""].filter(x => x).join(" ")
                }
                Text {
                    visible: !!root.d.foreign; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                    text: "Found: " + (root.d.foreign || "") + (root.d.foreignVersion ? " (" + root.d.foreignVersion + ")" : "") + ". "
                          + (root.d.adoptable ? "It matches this app's package exactly: Adopt tracks it without reinstalling."
                                              : "Uninstall the existing copy first to manage it with AppKata.")
                }
                Text {
                    visible: !root.installed && !root.d.foreign && !root.d.asset && !!root.d.version
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                    text: "No download for this computer in " + (root.d.version || "") + "."
                }
                Text { visible: !!root.d.error; width: parent.width; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12; text: root.d.error || "" }
                Text {      // AppKata itself (requirement 2.11)
                    visible: !!root.d.self; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                    text: root.d.restartNeeded ? "AppKata " + root.d.installed + " is installed. Restart to finish updating; you're running " + appVersion + "."
                          : root.d.selfManaged ? "AppKata updates itself like any portable app and keeps older versions for a quick rollback."
                          : "This AppKata wasn't installed as an AppImage, so it only tells you about new versions; Update opens the release page."
                }
            }
            Row {        // versions (requirement 5.7.5)
                width: parent.width; spacing: 8
                readonly property var boxes: root.installed
                    ? [[root.d.installed, "installed"], [root.d.updateTo || root.d.version || "—", root.d.updateTo ? "latest · " + Theme.shortDate(root.d.date) : "latest"],
                       root.selfUpdating ? ["Itself", "updates it"]
                       : root.systemUpdated ? ["System", "updates it"]
                       : root.d.state === "held" ? [root.d.held.replace("Held · ", ""), "until eligible"]
                       : root.d.state === "update" ? ["Update", "available"] : root.d.pinned ? ["Pinned", "no updates"] : ["Current", "up to date"]]
                    : [[root.d.version || "—", "latest"], [Theme.shortDate(root.d.date) || "—", "released"],
                       root.d.foreign ? [root.d.foreignVersion || "?", "found on system"] : [root.d.size || "—", root.d.assetLabel ? root.d.assetLabel + " · " + (root.d.asset ? "x86_64" : "") : "download"]]
                Repeater {
                    model: parent.boxes
                    Rectangle {
                        width: (col.width - 16) / 3; height: 62; radius: 12; color: Theme.input
                        Text { x: 14; y: 12; width: parent.width - 20; elide: Text.ElideRight; text: modelData[0]; font.pixelSize: 17; font.bold: true
                               color: index === 2 && root.d.state === "update" ? Theme.accent : Theme.text }
                        Text { x: 14; y: 38; width: parent.width - 20; elide: Text.ElideRight; text: modelData[1]; color: Theme.muted; font.pixelSize: 12 }
                    }
                }
            }
            Column {     // Flatpak permissions, and what an update adds (requirement 16.6.3)
                visible: !!root.ch && ((root.ch.perms || []).length > 0 || (root.ch.addedPerms || []).length > 0)
                width: parent.width; spacing: 8
                Text { text: "Permissions"; color: Theme.text; font.bold: true; font.pixelSize: 14 }
                Flow {
                    width: parent.width; spacing: 6
                    Repeater { model: root.ch ? root.ch.perms || [] : []
                               Pill { text: modelData; color: Theme.track; fg: Theme.muted; bold: false; u: 0.92 } }
                    Repeater { model: root.ch ? root.ch.addedPerms || [] : []
                               Pill { text: "+ " + modelData + (root.ch.pending ? " in " + root.ch.pending : ""); icon: "warn"
                                      color: Theme.warnSoft; fg: Theme.warn; u: 0.92 } }
                }
            }
            Column {     // what the sandbox lets the app use (requirement 17, A20)
                id: sandboxHead
                visible: root.installed && !!root.sbx
                width: parent.width; spacing: 10
                Item {
                    width: parent.width; height: 20
                    Text { text: "Sandbox"; color: Theme.text; font.bold: true; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                    Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 16
                        Text { visible: !!root.sbx && !!root.sbx.active; text: "Show the launch command"; objectName: "showLaunchCommand"
                               color: Theme.accent; font.pixelSize: 13
                               MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: root.showLaunchCommand(root.url) } }
                        Text { text: "Change…"; color: Theme.accent; font.bold: true; font.pixelSize: 13
                               MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: root.openSandbox(root.url) } } }
                }
                Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                        model: root.sbx ? root.sbx.chips : []
                        Pill { text: modelData[0]; icon: modelData[1]; u: 0.92
                               color: modelData[2] === "ok" ? Theme.okSoft : modelData[2] === "warn" ? Theme.warnSoft : Theme.track
                               fg: modelData[2] === "ok" ? Theme.ok : modelData[2] === "warn" ? Theme.warn : Theme.muted }
                    }
                }
                Row {     // installed while this system couldn't sandbox, and still can't (17.10); or it keeps
                          // its launcher and can't start (review 2, F16)
                    visible: root.installed && !!root.sbx && root.sbx.level !== "off"
                             && !!root.sbx.support && root.sbx.support.status === "unsupported"
                    width: parent.width; spacing: 8
                    Icon { name: "warn"; size: 14; color: Theme.warn; anchors.top: parent.top; anchors.topMargin: 1 }
                    Text { width: parent.width - 24; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: root.sbx && root.sbx.support && (root.sbx.active ? root.sbx.support.brokenHint : root.sbx.support.appToolsHint)
                                 || "Running unsandboxed: bubblewrap isn't installed. Install it and restart AppKata to sandbox it." }
                }
                Row {     // a Standard app with no xdg-dbus-proxy here runs with no session bus (17.10, review 2 F12)
                    visible: root.installed && !!root.sbx && root.sbx.level === "standard" && !!root.sbx.active
                             && !!root.sbx.support && root.sbx.support.busFilter === false && !!root.sbx.support.appToolsHint
                    width: parent.width; spacing: 8
                    Icon { name: "warn"; size: 14; color: Theme.warn; anchors.top: parent.top; anchors.topMargin: 1 }
                    Text { width: parent.width - 24; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                           text: root.sbx && root.sbx.support ? root.sbx.support.appToolsHint : "" }
                }
                Row {     // Chromium/Electron without their own sandbox under the system's bwrap profile (17.10.2)
                    visible: !!root.sbx && root.sbx.level !== "off" && !!root.sbx.active && !!root.sbx.ownSandbox
                             && !!root.sbx.support && root.sbx.support.innerSandbox === false
                    width: parent.width; spacing: 8
                    Icon { name: "info"; size: 14; color: Theme.faint; anchors.top: parent.top; anchors.topMargin: 1 }
                    Text { width: parent.width - 24; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                           text: "Runs without its own Chromium sandbox here: this system's AppArmor profile for bubblewrap doesn't let an app inside AppKata's sandbox make one, so AppKata starts it with --no-sandbox. It is still inside AppKata's sandbox." }
                }
                Row {     // the X11 / wlroots caveat (17.9)
                    visible: !!root.sbx && root.sbx.level !== "off" && !!(root.sbx.sessionWarning && root.sbx.sessionWarning.text)
                    width: parent.width; spacing: 8
                    Icon { name: "info"; size: 14; color: Theme.faint; anchors.top: parent.top; anchors.topMargin: 1 }
                    Text { width: parent.width - 24; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                           text: (root.sbx && root.sbx.sessionWarning && root.sbx.sessionWarning.text) || "" }
                }
                Row {     // an abstract session bus, for an app with the network grant (17.9, R3-8)
                    visible: !!root.sbx && root.sbx.level !== "off" && !!(root.sbx.busWarning && root.sbx.busWarning.text)
                    width: parent.width; spacing: 8
                    Icon { name: "warn"; size: 14; color: Theme.warn; anchors.top: parent.top; anchors.topMargin: 1 }
                    Text { width: parent.width - 24; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                           text: (root.sbx && root.sbx.busWarning && root.sbx.busWarning.text) || "" }
                }
            }
            Column {     // the channels an app has, when it isn't installed from one (requirement 16.6.1)
                visible: !root.ch && (root.d.channels || []).length > 0
                width: parent.width; spacing: 8
                Text { text: "Also available from"; color: Theme.text; font.bold: true; font.pixelSize: 14 }
                Repeater {
                    model: root.ch ? [] : root.d.channels || []
                    Row {
                        spacing: 8
                        Pill { text: modelData.label; icon: modelData.verified ? "shieldCheck" : ""; u: 0.92
                               color: modelData.verified ? Theme.okSoft : Theme.track; fg: modelData.verified ? Theme.ok : Theme.muted }
                        Text { text: modelData.value; font.family: Theme.mono; font.pixelSize: 12; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                        Text { anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12
                               color: modelData.check === "mismatch" ? Theme.warn : Theme.faint
                               text: modelData.check === "matches" ? "· matches the project" : modelData.check === "mismatch" ? "· " + (modelData.detail || "doesn't match the project")
                                     : "· unchecked" }
                    }
                }
            }
            Item {       // versions (requirement 5.7.5)
                id: versionsHead
                visible: (root.d.versions || []).length > 0
                width: parent.width; height: 22
                Text { text: "Versions"; color: Theme.text; font.bold: true; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 12
                    Row { spacing: 4
                        Icon { name: "play"; size: 10; color: Theme.ok; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: "installed"; color: Theme.faint; font.pixelSize: 11 } }
                    Row { spacing: 4
                        Icon { name: "star"; size: 11; color: Theme.star; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: "newest"; color: Theme.faint; font.pixelSize: 11 } } }
            }
            Rectangle {
                visible: versionsHead.visible
                width: parent.width; radius: 12; color: Theme.input
                height: vcol.height + 8
                Column {
                    id: vcol
                    y: 4; width: parent.width
                    Repeater {
                        model: (root.d.versions || []).slice(0, root.versionsShown)
                        Rectangle {
                            readonly property bool mine: modelData.installed
                            opacity: modelData.avoided && !mine ? 0.55 : 1         // avoided versions dimmed (10.6.5)
                            width: vcol.width; height: 36; radius: 9
                            color: mine ? Theme.okSoft : vArea.containsMouse ? Theme.hover : "transparent"
                            Item {
                                x: 10; width: 14; height: parent.height
                                Icon { anchors.centerIn: parent; visible: modelData.installed; name: "play"; size: 10; color: Theme.ok }
                            }
                            Row {
                                x: 30; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                                Text { text: modelData.version; font.family: Theme.mono; font.pixelSize: 13; font.bold: modelData.installed || modelData.newest
                                       color: modelData.installed ? Theme.ok : Theme.text }
                                Icon { visible: modelData.newest; name: "star"; size: 13; color: Theme.star; anchors.verticalCenter: parent.verticalCenter }
                                Pill { visible: modelData.kept; text: "Kept"; color: Theme.track; fg: Theme.muted; u: 0.78; anchors.verticalCenter: parent.verticalCenter }
                            }
                            Row {        // each version's combined Trust (10.6.5)
                                visible: modelData.trust !== null && modelData.trust !== undefined || !!modelData.avoided
                                anchors.right: vdate.left; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                                Icon { name: modelData.avoided ? "warn" : "shield"; size: 13; color: modelData.avoided ? Theme.err : Theme.ok; anchors.verticalCenter: parent.verticalCenter }
                                Text { text: modelData.avoided ? "Avoid" : Number(modelData.trust || 0).toFixed(1); color: modelData.avoided ? Theme.err : Theme.muted
                                       font.pixelSize: 12; font.bold: !!modelData.avoided }
                            }
                            Text { id: vdate; anchors.right: act.left; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                                   text: Theme.shortDate(modelData.date) + (modelData.date ? ", " + new Date(modelData.date).getFullYear() : "")
                                   color: Theme.faint; font.pixelSize: 12 }
                            Item {
                                id: act
                                anchors.right: parent.right; anchors.rightMargin: 4; width: 76; height: parent.height
                                Text { visible: modelData.installed; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
                                       text: "Installed"; color: Theme.ok; font.bold: true; font.pixelSize: 12 }
                                Row {      // icon-only (requirement 5.7.5.1)
                                    visible: !modelData.installed && !root.d.foreign && !root.busy && !root.selfUpdating && !root.ch   // channels: 16.5.7
                                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                                    TipButton {
                                        width: 28; height: 28
                                        readonly property bool upd: modelData.newest && root.d.state === "update"
                                        icon: upd ? "update" : "download"; accent: upd
                                        tip: upd ? "Update" : modelData.kept ? "Reinstall (kept, no download)" : root.installed ? "Install this version (pins it)" : "Install"
                                        showTip: root.demoVersionTip === index * 2
                                        onClicked: modelData.newest ? backend.install(root.url) : backend.installVersion(root.url, modelData.version)
                                    }
                                    TipButton {     // a kept older version can be removed (requirement 4.3.1.5)
                                        visible: modelData.kept
                                        width: 28; height: 28; icon: "trash"; danger: true; tip: "Remove this version"
                                        showTip: root.demoVersionTip === index * 2 + 1
                                        onClicked: root.confirmRemoveVersion(root.url, modelData.version)
                                    }
                                }
                            }
                            MouseArea { id: vArea; anchors.fill: parent; hoverEnabled: true; z: -1 }
                        }
                    }
                    Text {        // requirement 5.7.5.3
                        visible: (root.d.versions || []).length > root.versionsShown
                        x: 30; height: 30; verticalAlignment: Text.AlignVCenter
                        text: "Show next " + Math.min(5, (root.d.versions || []).length - root.versionsShown) + " older"
                        color: Theme.accent; font.bold: true; font.pixelSize: 12
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.versionsShown += 5 }
                    }
                }
            }
            Text { visible: versionsHead.visible && !!root.d.installed && !root.d.pinned && !root.selfUpdating; width: parent.width; wrapMode: Text.WordWrap
                   text: root.ch ? "The project's releases. " + (root.ch.kind === "flatpak" ? "Flathub builds them on its own schedule." : "The distribution decides which version it ships.")
                                 : "Installing an older version pins the app there until you unpin it. Kept versions reinstall without downloading."
                   color: Theme.faint; font.pixelSize: 11 }
            Item {       // reviews (requirement 5.7.6)
                id: reviewsHead
                width: parent.width; height: 26
                Text { text: "Reviews"; color: Theme.text; font.bold: true; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                TrustBadge { app: root.d; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter }
            }
            Repeater {
                model: root.d.reviews || []
                Rectangle {
                    id: rv
                    readonly property bool has: modelData.section !== "" || (modelData.others || []).length > 0
                    readonly property bool open: root.expanded === index && has
                    property bool earlier: false
                    width: col.width; radius: 11; color: Theme.input
                    height: 50 + (open ? extra.height + 20 : 0)
                    AvatarStack { x: 10; y: 12; people: modelData.avatars; size: 21; ring: Theme.input }
                    Row {
                        x: 104; y: 9; width: parent.width - 104 - 156; spacing: 6; clip: true
                        Text {
                            width: Math.min(implicitWidth, parent.width - (rvVer.visible ? rvVer.implicitWidth + 6 : 0)); elide: Text.ElideRight
                            text: modelData.name; color: modelData.own ? Theme.text : Theme.accent; font.bold: true; font.pixelSize: 13
                            MouseArea { anchors.fill: parent; enabled: !modelData.own; cursorShape: Qt.PointingHandCursor; onClicked: root.openTrust(modelData.trustId) }
                        }
                        Text { id: rvVer; visible: !!modelData.reviewedVersion; text: "· reviewed " + modelData.reviewedVersion   // 10.6.5
                               color: Theme.faint; font.pixelSize: 12; anchors.baseline: parent.children[0].baseline }
                    }
                    Row {
                        x: 104; y: 28; spacing: 4
                        Repeater { model: modelData.tags.slice(0, 3); Chip { text: modelData; u: 0.86; onClicked: root.pickTag(modelData) } }
                    }
                    Row {
                        anchors.right: parent.right; anchors.rightMargin: 34; y: 17; spacing: 5
                        readonly property bool zero: modelData.trust === 0
                        Icon { name: "shield"; size: 15; color: parent.zero ? Theme.err : Theme.ok; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: modelData.trust === null || modelData.trust === undefined ? "–" : parent.zero ? "Avoid" : modelData.trust
                               color: parent.zero ? Theme.err : Theme.text; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter; width: 34 }
                        Stars { value: modelData.rating || 0; r: 4.6; anchors.verticalCenter: parent.verticalCenter }
                    }
                    Icon {
                        visible: rv.has
                        anchors.right: parent.right; anchors.rightMargin: 12; y: 18
                        name: rv.open ? "chevUp" : "chevDown"; size: 13; color: Theme.faint
                    }
                    MouseArea { anchors.fill: parent; z: -1; enabled: rv.has; cursorShape: Qt.PointingHandCursor
                                onClicked: root.expanded = rv.open ? -1 : index }
                    Rectangle { visible: rv.open; x: 12; y: 49; width: parent.width - 24; height: 1; color: Theme.border }
                    Column {
                        id: extra
                        visible: rv.open; x: 14; y: 60; width: parent.width - 28; spacing: 10
                        Text {
                            id: body
                            visible: modelData.section !== ""; width: parent.width
                            text: modelData.section; textFormat: Text.MarkdownText; wrapMode: Text.WordWrap
                            color: Theme.text; font.pixelSize: 13; linkColor: Theme.accent
                            onLinkActivated: l => Qt.openUrlExternally(l)
                        }
                        Row {        // the Trust's other reviews of the app, collapsed (10.6.5)
                            visible: (modelData.others || []).length > 0; spacing: 6
                            Icon { name: rv.earlier ? "chevUp" : "chevDown"; size: 12; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData.othersLabel || ""; color: Theme.accent; font.bold: true; font.pixelSize: 12
                                   MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: rv.earlier = !rv.earlier } }
                        }
                        Repeater {
                            model: rv.earlier ? (modelData.others || []) : []
                            Column {
                                width: extra.width; spacing: 4
                                Row { spacing: 8
                                    Text { text: modelData.version; font.family: Theme.mono; font.bold: true; font.pixelSize: 12; color: Theme.text }
                                    Text { visible: !!modelData.date; text: modelData.date; color: Theme.faint; font.pixelSize: 12 }
                                    Text { text: modelData.trust === 0 ? "Avoid" : modelData.trust === null || modelData.trust === undefined ? "" : "Trust " + modelData.trust
                                           color: modelData.trust === 0 ? Theme.err : Theme.muted; font.pixelSize: 12; font.bold: modelData.trust === 0 }
                                    Stars { visible: modelData.rating !== null && modelData.rating !== undefined; value: modelData.rating || 0; r: 4; anchors.verticalCenter: parent.verticalCenter }
                                }
                                Text { visible: !!modelData.text; width: parent.width; text: modelData.text || ""; textFormat: Text.MarkdownText; wrapMode: Text.WordWrap
                                       color: Theme.muted; font.pixelSize: 13; linkColor: Theme.accent; onLinkActivated: l => Qt.openUrlExternally(l) }
                            }
                        }
                    }
                }
            }
            Text { visible: (root.d.reviews || []).length === 0; text: "No trusted reviewer lists this app yet."; color: Theme.muted; font.pixelSize: 13 }
            Column {     // release notes (requirement 5.7.7)
                visible: !!root.d.notes
                width: parent.width; spacing: 6
                property bool more: false
                Text { text: "What's new in " + (root.d.version || ""); color: Theme.text; font.bold: true; font.pixelSize: 14 }
                Text {
                    width: parent.width; text: root.d.notes || ""; textFormat: Text.MarkdownText; wrapMode: Text.WordWrap
                    maximumLineCount: parent.more ? 400 : 6; elide: Text.ElideRight; clip: true
                    color: Theme.muted; font.pixelSize: 13; linkColor: Theme.accent; onLinkActivated: l => Qt.openUrlExternally(l)
                }
                Text { text: parent.more ? "Show less" : "Show more"; color: Theme.accent; font.bold: true; font.pixelSize: 12
                       MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: parent.parent.more = !parent.parent.more } }
            }
            Text { text: "About"; color: Theme.text; font.bold: true; font.pixelSize: 14 }
            Text {      // README (requirement 3.4)
                width: parent.width
                text: root.d.readme || root.d.summary || ""
                textFormat: root.d.readme ? Text.MarkdownText : Text.PlainText
                wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13; linkColor: Theme.accent
                onLinkActivated: l => Qt.openUrlExternally(l)
            }
        }
    }
}
