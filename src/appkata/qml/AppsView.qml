import QtQuick
import QtQuick.Controls.Basic
import "."

// The Apps perspective (requirement 6): installed apps, updates first, then by name.
Item {
    id: root
    property string selected: ""
    property real rightInset: 0
    property string hoverTrash: ""
    property string filter: ""
    signal openApp(string url)
    signal confirmUninstall(string url)
    signal browse()
    readonly property var all: backend.installedItems
    readonly property var items: filter ? all.filter(a => a.name.toLowerCase().indexOf(filter.toLowerCase()) >= 0) : all
    readonly property var updates: items.filter(a => a.state === "update")
    readonly property var rest: items.filter(a => a.state !== "update")
    readonly property real rightEdge: width - 32 - rightInset

    Text { id: title; x: 32; y: 30; text: "Apps"; color: Theme.text; font.pixelSize: 28; font.bold: true }
    Text {
        anchors.left: title.right; anchors.leftMargin: 14; anchors.baseline: title.baseline
        text: root.all.length + " installed" + (backend.updateCount ? " · " + backend.updateCount + " update" + (backend.updateCount === 1 ? "" : "s") : "")
        color: Theme.muted; font.pixelSize: 14
    }
    Field {
        id: filterBox
        x: root.rightEdge - width; y: 20; width: root.rightInset > 0 ? 170 : 240
        icon: "filter"; placeholder: "Filter"; clearable: true
        onEdited: t => root.filter = t
    }
    FButton {
        visible: backend.updateCount > 0
        anchors.right: filterBox.left; anchors.rightMargin: 12; y: 22
        text: "Update all"; icon: "update"; primary: true
        onClicked: backend.updateAll()
    }

    Flickable {
        id: flick
        x: 0; y: 80; width: parent.width - root.rightInset; height: parent.height - y
        contentHeight: list.height + 40; clip: true
        layer.enabled: contentY > 0
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Column {
            id: list
            x: 32; width: root.rightEdge - 32; spacing: 8
            Text { visible: root.updates.length > 0; text: "UPDATES · " + root.updates.length; color: Theme.accent; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.2; topPadding: 4; bottomPadding: 4 }
            Repeater {
                model: root.updates
                AppRow { width: list.width; app: modelData; selected: modelData.url === root.selected; trashTip: root.hoverTrash === modelData.url
                         onClicked: root.openApp(modelData.url); onUninstall: root.confirmUninstall(modelData.url) }
            }
            Item { visible: root.updates.length > 0; width: 1; height: 8 }
            Text { visible: root.rest.length > 0; text: "INSTALLED · " + root.rest.length; color: Theme.faint; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.2; topPadding: 4; bottomPadding: 4 }
            Repeater {
                model: root.rest
                AppRow { width: list.width; app: modelData; selected: modelData.url === root.selected; trashTip: root.hoverTrash === modelData.url
                         onClicked: root.openApp(modelData.url); onUninstall: root.confirmUninstall(modelData.url) }
            }
        }
    }
    Column {     // empty state (requirement 6.7)
        visible: root.all.length === 0
        anchors.centerIn: parent; spacing: 14
        Text { text: "No apps installed yet"; color: Theme.text; font.pixelSize: 17; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
        FButton { text: "Browse the Catalog"; icon: "grid"; primary: true; anchors.horizontalCenter: parent.horizontalCenter; onClicked: root.browse() }
    }
}
