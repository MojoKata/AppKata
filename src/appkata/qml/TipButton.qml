import QtQuick
import "."

// A small icon-only button whose label is a tooltip, shown to its left on hover (so it stays
// inside clipped lists). accent: the main action's colours.
Rectangle {
    id: root
    property string icon
    property string tip
    property bool accent: false
    property bool danger: false          // a red icon (remove)
    property bool enabledButton: true
    property bool showTip: false        // the screenshot tour
    property real tipOffset: 0          // extra room to the left, to clear neighbouring buttons
    signal clicked()
    width: 32; height: 32; radius: 9
    readonly property bool hot: area.containsMouse && enabledButton
    color: !enabledButton ? Theme.track : accent ? (hot ? Qt.lighter(Theme.accent, 1.08) : Theme.accent) : hot ? Theme.hover : Theme.surface
    border.width: accent || !enabledButton ? 0 : 1
    border.color: Theme.border
    Icon { anchors.centerIn: parent; name: root.icon; color: !root.enabledButton ? Theme.faint : root.accent ? "#ffffff" : root.danger ? Theme.err : Theme.muted }
    MouseArea {
        id: area
        anchors.fill: parent; hoverEnabled: true
        cursorShape: root.enabledButton ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: if (root.enabledButton) root.clicked()
    }
    Rectangle {
        visible: (area.containsMouse || root.showTip) && root.tip !== ""
        anchors.right: parent.left; anchors.rightMargin: 8 + root.tipOffset; anchors.verticalCenter: parent.verticalCenter
        width: tipText.implicitWidth + 20; height: 26; radius: 7; color: Theme.tipBg; z: 20
        Text { id: tipText; anchors.centerIn: parent; text: root.tip; color: Theme.tipFg; font.bold: true; font.pixelSize: 12 }
    }
}
