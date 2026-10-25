import QtQuick
import QtQuick.Controls.Basic
import "."

// Own header bar (requirement 5.3): logo, perspective switcher, sync status, ⋮ menu, close; on
// Windows also minimize and maximize/restore (requirement 15.13).
Rectangle {
    id: root
    property string view: "catalog"
    property var window: null
    signal viewSelected(string view)
    signal about()
    signal installSelf()
    signal settings()
    signal closeWindow()
    signal quit()
    property alias menu: appMenu
    height: 52
    color: Theme.surface
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

    DragHandler { target: null; onActiveChanged: if (active && root.window) root.window.startSystemMove() }
    TapHandler {
        onDoubleTapped: if (root.window) root.window.visibility === Window.Maximized ? root.window.showNormal() : root.window.showMaximized()
    }

    Image { x: 18; y: 12; width: 28; height: 28; source: "assets/appkata.svg"; sourceSize: Qt.size(56, 56); smooth: true }
    Text { x: 56; anchors.verticalCenter: parent.verticalCenter; text: "AppKata"; color: Theme.text; font.pixelSize: 15; font.bold: true }

    Rectangle {
        id: seg
        anchors.centerIn: parent
        width: 500; height: 34; radius: 10; color: Theme.track
        Row {
            x: 3; y: 3
            Repeater {
                model: [["apps", "apps", "Apps"], ["catalog", "grid", "Catalog"], ["sources", "branch", "Sources"], ["audit", "audit", "Audit"]]
                Rectangle {
                    readonly property bool on: root.view === modelData[0]
                    width: (seg.width - 6) / 4; height: 28; radius: 8
                    color: on ? Theme.segOn : "transparent"
                    Row {
                        anchors.centerIn: parent; spacing: 6
                        Icon { name: modelData[1]; color: parent.parent.on ? Theme.text : Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: modelData[2]; color: parent.parent.on ? Theme.text : Theme.muted; font.pixelSize: 13; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
                        Icon {           // an install in progress (requirement 4.8.1)
                            visible: modelData[0] === "apps" && backend.installing
                            name: "sync"; size: 14; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter
                            RotationAnimation on rotation { running: backend.installing; from: 0; to: 360; duration: 1100; loops: Animation.Infinite }
                        }
                        Rectangle {      // updates waiting (requirement 5.3)
                            visible: modelData[0] === "apps" && backend.updateCount > 0
                            width: Math.max(20, cnt.implicitWidth + 10); height: 18; radius: 9; color: Theme.accent
                            anchors.verticalCenter: parent.verticalCenter
                            Text { id: cnt; anchors.centerIn: parent; text: backend.updateCount; color: "#ffffff"; font.bold: true; font.pixelSize: 11 }
                        }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.viewSelected(modelData[0]) }
                }
            }
        }
    }

    // sync status (requirement 9.2)
    Row {
        id: syncRow
        anchors.right: dotsBtn.left; anchors.rightMargin: 22; anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: backend.syncing ? "Syncing " + backend.syncDone + " / " + Math.max(backend.syncTotal, backend.syncDone)
                  : backend.lastSync ? "Synced " + Theme.ago(backend.lastSync) : "Not synced yet"
            color: backend.syncing ? Theme.muted : Theme.faint; font.pixelSize: 12; font.bold: backend.syncing
        }
        Item {
            width: 18; height: 18; anchors.verticalCenter: parent.verticalCenter
            Icon { anchors.centerIn: parent; visible: !backend.syncing && !!backend.lastSync; name: "check"; size: 14; lineWidth: 1.8; color: Theme.ok }
            Rectangle {
                visible: backend.syncing; anchors.centerIn: parent; width: 18; height: 18; radius: 9
                color: "transparent"; border.width: 2.5; border.color: Theme.track
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.accent; x: 6; y: -1.5 }
                RotationAnimation on rotation { running: backend.syncing; from: 0; to: 360; duration: 1000; loops: Animation.Infinite }
            }
        }
    }
    MouseArea {
        anchors.fill: syncRow; anchors.margins: -4
        cursorShape: Qt.PointingHandCursor
        onClicked: backend.syncing ? syncPop.open() : backend.sync()
    }
    Popup {
        id: syncPop
        x: syncRow.x - 40; y: 46; width: 260; padding: 14
        background: Rectangle { radius: 12; color: Theme.raised; border.color: Theme.border }
        contentItem: Column {
            spacing: 10
            Text { text: "Syncing " + backend.syncCurrent; color: Theme.text; font.pixelSize: 13; width: 232; elide: Text.ElideMiddle }
            FButton { text: "Cancel"; onClicked: { backend.cancelSync(); syncPop.close() } }
        }
    }
    Item {
        id: dotsBtn
        anchors.right: winButtons.visible ? winButtons.left : closeBtn.left; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter
        width: 30; height: 30
        Rectangle {
            anchors.fill: parent; radius: 15
            color: appMenu.visible ? Theme.accentSoft : dotsArea.containsMouse ? Theme.track : "transparent"
            border.width: appMenu.visible ? 1.5 : 0; border.color: Theme.accent
        }
        Icon { anchors.centerIn: parent; name: "dots"; color: appMenu.visible ? Theme.accent : Theme.muted }
        MouseArea { id: dotsArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: appMenu.open() }
        PopMenu {
            id: appMenu
            menuWidth: 300
            x: dotsBtn.width - menuWidth; y: 40
            readonly property string mode: Theme.mode         // the theme shown, decided once in Main.qml
            items: [   // requirement 5.4
                { key: "sync", icon: "sync", text: "Sync", subtext: backend.syncing ? "Syncing…" : "Last synced " + Theme.ago(backend.lastSync) },
                { key: "settings", icon: "gear", text: "Settings…" },
                { type: "separator" },
                { key: "system", type: "radio", text: "Match system", checked: mode === "system" },
                { key: "dark", type: "radio", text: "Dark", checked: mode === "dark" },
                { key: "light", type: "radio", text: "Light", checked: mode === "light" },
                { type: "separator" },
                { key: "log", icon: "log", text: "Show app log", note: "Downloads, installs and errors" },
                { key: "about", icon: "info", text: "About AppKata" },
            ].concat(backend.selfInstallOffer ? [{ key: "installSelf", icon: "download", text: "Install AppKata…", note: "Add it to the app menu" }] : []).concat([
                { type: "separator" },
                { key: "close", icon: "window", text: "Close window", note: root.window && root.window.hasTray ? "Keeps running in the tray" : "" },
                { key: "quit", icon: "power", text: "Quit AppKata", danger: true, shortcut: Qt.platform.os === "osx" ? "⌘Q" : "Alt+Q" }])
            onTriggered: key => {
                if (key === "sync") backend.sync()
                else if (key === "settings") root.settings()
                else if (key === "about") root.about()
                else if (key === "installSelf") root.installSelf()
                else if (key === "log") backend.showAppLog()
                else if (key === "close") root.closeWindow()
                else if (key === "quit") root.quit()
                else backend.setPref("theme", key)
            }
        }
    }
    readonly property bool maximized: !!root.window && root.window.visibility === Window.Maximized
    function updateMaxRect() {      // where Maximize is, so Windows can offer Snap Layouts over it
        if (root.window && winButtons.visible) {
            const p = maxBtn.mapToItem(null, 0, 0)
            root.window.maxButtonRect = Qt.rect(p.x, p.y, maxBtn.width, maxBtn.height)
        }
    }
    onWidthChanged: updateMaxRect()
    Component.onCompleted: updateMaxRect()
    Row {
        id: winButtons
        visible: !!root.window && root.window.windowButtons
        onVisibleChanged: root.updateMaxRect()
        anchors.right: closeBtn.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        IconButton { round: true; icon: "minimize"; onClicked: root.window.showMinimized() }
        IconButton {
            id: maxBtn
            round: true; icon: root.maximized ? "restore" : "maximize"
            active: !!root.window && root.window.maxHover
            onClicked: root.maximized ? root.window.showNormal() : root.window.showMaximized()
        }
    }
    IconButton {
        id: closeBtn
        anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
        round: true; icon: "x"
        onClicked: root.closeWindow()
    }
}
