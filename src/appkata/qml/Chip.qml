import QtQuick
import "."

// A tag chip; warning tags (requirement 10.4.3) use the warning colours.
Rectangle {
    id: root
    property string text
    property bool on: false
    property real u: 1
    property real size: 10.5
    property bool closable: false
    signal clicked()
    signal closed()
    readonly property bool warnTag: Theme.warnTags.indexOf(text) >= 0
    readonly property color fg: on ? Theme.accent : warnTag ? Theme.warn : Theme.muted
    height: 20 * u
    width: label.implicitWidth + 18 * u + (closable ? 14 * u : 0)
    radius: height / 2
    color: on ? Theme.accentSoft : warnTag ? Theme.warnSoft : Theme.track
    border.width: on ? 1 : 0
    border.color: Theme.accent
    Text {
        id: label
        x: 9 * root.u; anchors.verticalCenter: parent.verticalCenter
        text: root.text; color: root.fg; font.bold: true; font.pixelSize: root.size * root.u
    }
    Icon {
        visible: root.closable
        anchors.right: parent.right; anchors.rightMargin: 7 * root.u; anchors.verticalCenter: parent.verticalCenter
        name: "x"; size: 9 * root.u; lineWidth: 1.8; color: root.fg
        MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: root.closed() }
    }
    MouseArea {
        anchors.fill: parent; anchors.rightMargin: root.closable ? 16 : 0
        cursorShape: Qt.PointingHandCursor; onClicked: root.clicked()
    }
}
