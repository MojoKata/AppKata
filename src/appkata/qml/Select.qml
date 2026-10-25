import QtQuick
import "."

// A compact select: a pill with a label and chevron that opens a PopMenu of options.
Rectangle {
    id: root
    property string label
    property string icon: ""
    property var options: []            // [[key, text], …]
    property string current: ""
    signal picked(string key)
    height: 28
    width: row.implicitWidth + 24
    radius: 14
    color: area.containsMouse || menu.visible ? Theme.hover : Theme.surface
    border.color: Theme.border
    Row {
        id: row
        anchors.centerIn: parent; spacing: 6
        Icon { visible: root.icon !== ""; name: root.icon; size: 15; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
        Text { text: root.label; color: Theme.text; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
        Icon { name: "chevDown"; size: 13; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
    }
    MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: menu.open() }
    PopMenu {
        id: menu
        menuWidth: 220
        x: root.width - menuWidth; y: root.height + 6
        items: root.options.map(o => ({ key: o[0], text: o[1] }))
        onTriggered: key => root.picked(key)
    }
}
