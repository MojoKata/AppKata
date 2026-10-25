import QtQuick
import QtQuick.Controls.Basic
import "."

// An installed app (requirement 6.1–6.3, 6.6): icon, name, versions, origin, icon-only Update and Uninstall.
// While it installs: the phase, progress and an icon-only Cancel (requirement 4.8).
Rectangle {
    id: root
    property var app: ({})
    property bool selected: false
    property bool trashTip: false
    signal clicked()
    signal uninstall()
    readonly property bool upd: app.state === "update"
    readonly property var busy: backend.busy[app.url]
    height: 60; radius: 12
    color: selected ? Theme.accentSoft : area.containsMouse ? Theme.hover : Theme.surface
    border.width: selected ? 1.5 : 1
    border.color: selected ? Theme.accent : Theme.border
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.clicked() }
    Rectangle { visible: root.upd; x: 0; y: 12; width: 3.5; height: 36; radius: 2; color: Theme.accent }
    AppIcon { x: 16; y: 14; size: 32; app: root.app }
    Text { x: 62; y: 12; text: root.app.name || ""; color: Theme.text; font.bold: true; font.pixelSize: 15; width: root.width * 0.42 - 70; elide: Text.ElideRight }
    Row {
        x: 62; y: 34; spacing: 6
        Text { text: root.app.installed || ""; color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono }
        Text { visible: root.upd; text: "→"; color: Theme.accent; font.pixelSize: 12 }
        Text { visible: root.upd; text: root.app.updateTo || ""; color: Theme.accent; font.pixelSize: 12; font.bold: true; font.family: Theme.mono }
    }
    Row {     // origin (requirement 2.9.3)
        x: root.width * 0.42; y: 13; spacing: 6
        Origin { id: originMark; app: root.app; ring: root.color; anchors.verticalCenter: parent.verticalCenter }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, Math.max(0, statusRow.x - root.width * 0.42 - originMark.width - 18)); elide: Text.ElideRight
            readonly property int n: (root.app.trusts || []).length
            text: root.app.src ? (n ? "Source · " + n + " trust" + (n > 1 ? "s" : "") : "Source") : n === 1 ? root.app.trusts[0].name : n + " trusts"
            color: Theme.muted; font.pixelSize: 13
        }
    }
    Text {
        x: root.width * 0.42; y: 35
        width: Math.min(implicitWidth, Math.max(0, statusRow.x - x - 12)); elide: Text.ElideRight
        text: root.app.ch ? (root.app.host || "") + " · " + (root.app.ch.kind === "flatpak" ? "Flatpak" : "." + (root.app.ch.manager === "dnf" ? "rpm" : "deb") + " · " + (root.app.ch.distro || ""))
                          : (root.app.host || "") + " · " + (root.app.installKind || "").replace("appimage", "AppImage").replace("tarball", "tar.gz")
        color: Theme.faint; font.pixelSize: 12
    }
    Row {
        id: statusRow
        anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        Column {        // install progress (requirement 4.8.1)
            visible: !!root.busy; spacing: 5; anchors.verticalCenter: parent.verticalCenter
            Row { spacing: 8; anchors.right: parent.right
                Text { text: Theme.busyDetail(root.busy); visible: !!root.busy && root.busy.phase === "Downloading" && root.width > 900; color: Theme.faint; font.pixelSize: 11 }
                Text { text: Theme.busyLabel(root.busy); color: root.busy && root.busy.phase === "Waiting" ? Theme.muted : Theme.accent; font.bold: true; font.pixelSize: 12 } }
            Rectangle {
                width: 170; height: 5; radius: 2.5; color: Theme.track; anchors.right: parent.right
                Rectangle { width: parent.width * (root.busy ? root.busy.progress : 0); height: 5; radius: 2.5
                            color: root.busy && root.busy.phase === "Waiting" ? Theme.faint : Theme.accent }
            }
        }
        Pill {      // the Visual C++ run-time (requirement 15.18.2)
            visible: !!root.app.msvcrt && !root.busy; text: "MSVCRT"; tip: "Microsoft Visual C++ Run-time" + (root.app.msvcrtMissing ? ": not installed" : "")
            icon: root.app.msvcrtMissing ? "warn" : ""; u: 0.9; anchors.verticalCenter: parent.verticalCenter
            color: root.app.msvcrtMissing ? Theme.warnSoft : Theme.track; fg: root.app.msvcrtMissing ? Theme.warn : Theme.muted
            onClicked: if (root.app.msvcrtMissing) backend.msvcrtNeeded({ url: root.app.url, name: root.app.name })
        }
        Pill {      // a trusted reviewer avoids the installed version (requirement 10.6.5)
            visible: !!root.app.installedVetoed && !root.busy; text: "Avoid this version"; icon: "warn"; u: 0.9; anchors.verticalCenter: parent.verticalCenter
            color: Theme.errSoft; fg: Theme.err; tip: root.app.avoid ? (root.app.avoid.own ? "You" : root.app.avoid.by) + " · Avoid" + (root.app.avoid.from ? " from " + root.app.avoid.from : "") : ""
        }
        Pill { visible: root.upd && !root.busy && !root.app.installedVetoed; text: root.app.updateAvoided ? "Update · avoid " + root.app.updateTo : "Update available"; showDot: true; dot: Theme.accent; fg: Theme.accent; color: Theme.accentSoft; u: 0.9; anchors.verticalCenter: parent.verticalCenter }
        Row {           // a channel install the system updates, or that nothing updates (requirement 16.5.1)
            visible: !!root.app.ch && !root.busy && root.app.state !== "update"
                     && ["system", "not-updated", "held"].indexOf(root.app.ch.updates) >= 0
            spacing: 8; anchors.verticalCenter: parent.verticalCenter
            Text { visible: root.app.state === "system" && !!root.app.newer; text: root.app.version + " is out"; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            Pill {
                readonly property string u2: root.app.ch ? root.app.ch.updates : ""
                text: u2 === "system" ? "Updated by the system" : u2 === "held" ? "Held by the system" : "Not updated"
                icon: u2 === "not-updated" ? "warn" : u2 === "held" ? "pin" : "sync"
                fg: u2 === "not-updated" ? Theme.warn : Theme.muted; color: u2 === "not-updated" ? Theme.warnSoft : Theme.track; u: 0.9
                readonly property string why: !root.app.ch ? "" : u2 === "system" ? (root.app.ch.updatesBy || "The system") + " updates it automatically"
                     : u2 === "not-updated" ? (root.app.ch.distro || "The system") + " doesn't update this automatically"
                     : "Held at this version by the system's package settings"
                anchors.verticalCenter: parent.verticalCenter
                HoverHandler { id: whyHover }
                Rectangle {     // tooltip, drawn here so the screenshot tour can show it
                    visible: whyHover.hovered || !!root.app.tourTip
                    anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.top; anchors.bottomMargin: 6
                    width: whyText.implicitWidth + 20; height: 26; radius: 7; color: Theme.tipBg; z: 10
                    Text { id: whyText; anchors.centerIn: parent; text: parent.parent.why; color: Theme.tipFg; font.bold: true; font.pixelSize: 12 }
                }
            }
        }
        Pill {          // an update that asks for more permissions (requirement 16.6.3)
            visible: root.upd && !root.busy && !!root.app.permsGrow; text: "Asks for more"; icon: "warn"; u: 0.9
            color: Theme.warnSoft; fg: Theme.warn; anchors.verticalCenter: parent.verticalCenter
            tip: root.app.ch ? (root.app.ch.addedPerms || []).join(", ") : ""
        }
        Row {           // the app updates itself (requirement 4.10)
            visible: root.app.state === "selfupdating" && !root.busy
            spacing: 8; anchors.verticalCenter: parent.verticalCenter
            Text { visible: !!root.app.newer; text: root.app.version + " is out"; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
            Pill { text: "Updates itself"; icon: "sync"; fg: Theme.muted; color: Theme.track; u: 0.9; anchors.verticalCenter: parent.verticalCenter }
        }
        Row {
            visible: root.app.state === "held" || root.app.state === "pinned"
            spacing: 6; anchors.verticalCenter: parent.verticalCenter
            Icon { name: root.app.state === "pinned" ? "pin" : "clock"; size: 15; color: Theme.faint; anchors.verticalCenter: parent.verticalCenter }
            Text { text: root.app.state === "pinned" ? "Pinned at " + root.app.pinned : root.app.held; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; rightPadding: 8 }
        }
        Rectangle {    // icon-only Update (requirement 6.4.1)
            visible: root.upd && !root.busy
            width: 32; height: 32; radius: 9; color: upArea.containsMouse ? Qt.lighter(Theme.accent, 1.08) : Theme.accent
            Icon { anchors.centerIn: parent; name: "update"; color: "#ffffff" }
            MouseArea { id: upArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: backend.update(root.app.url) }
            ToolTip.visible: upArea.containsMouse; ToolTip.text: "Update"
        }
        TipButton {    // icon-only Cancel while it installs (requirement 4.8.3)
            visible: !!root.busy && root.busy.phase !== "Installing"
            icon: "x"; tip: root.busy && root.busy.phase === "Waiting" ? "Remove from the queue" : "Cancel"
            anchors.verticalCenter: parent.verticalCenter; onClicked: backend.cancelInstall(root.app.url)
        }
        Rectangle {    // icon-only Uninstall (not for AppKata itself)
            id: trash
            visible: !root.app.self && !root.busy
            width: 32; height: 32; radius: 9; color: trArea.containsMouse || root.trashTip ? Theme.hover : Theme.surface; border.color: Theme.border
            Icon { anchors.centerIn: parent; name: "trash"; color: Theme.err }
            MouseArea { id: trArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.uninstall() }
            Rectangle {     // tooltip, drawn here so the screenshot tour can show it
                visible: trArea.containsMouse || root.trashTip
                anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.top; anchors.bottomMargin: 6
                width: tipText.implicitWidth + 20; height: 26; radius: 7; color: Theme.tipBg; z: 10
                Text { id: tipText; anchors.centerIn: parent; text: "Uninstall"; color: Theme.tipFg; font.bold: true; font.pixelSize: 12 }
            }
        }
    }
}
