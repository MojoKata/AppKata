import QtQuick
import QtQuick.Shapes
import "."
import "Icons.js" as Icons

// Click a symbol in "–★★★★★" (requirement 8.4.3, 8.4.4). value: null = no opinion, 0–5.
// For Trust, "–" is 0 = Avoid (a veto) and turns red; for Rating it's just 0 stars.
Row {
    id: root
    property var value: null
    property bool trust: false
    property bool noZero: false         // 1–5 only (a Trust's Score): no "–" and no clear
    property int hover: -1
    signal picked(var value)
    readonly property bool avoid: trust && value === 0
    readonly property color onColor: avoid ? Theme.err : trust ? Theme.ok : noZero ? Theme.accent : Theme.star
    spacing: 4
    Rectangle {
        visible: !root.noZero
        width: 34; height: 34; radius: 9
        readonly property bool on: root.value === 0
        color: on ? (root.avoid ? Theme.errSoft : Theme.track) : dashArea.containsMouse ? Theme.hover : "transparent"
        border.width: on ? 1 : 0; border.color: root.avoid ? Theme.err : Theme.borderStrong
        Rectangle { anchors.centerIn: parent; width: 14; height: 2.6; radius: 1.3; color: parent.on ? (root.avoid ? Theme.err : Theme.text) : Theme.faint }
        MouseArea { id: dashArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.picked(0) }
    }
    Repeater {
        model: 5
        Item {
            id: cell
            width: 30; height: 34
            readonly property bool on: root.value !== null && root.value !== undefined && index < root.value
            readonly property bool hot: root.hover >= 0 ? index <= root.hover : false
            Shape {
                anchors.centerIn: parent; width: 26; height: 26
                ShapePath {
                    strokeColor: cell.on || cell.hot ? root.onColor : Theme.borderStrong; strokeWidth: 1.6
                    fillColor: cell.on ? root.onColor : cell.hot ? Theme.alpha(root.onColor, 0.35) : "transparent"
                    joinStyle: ShapePath.RoundJoin
                    PathSvg { path: Icons.starPath(13, 13.5, 12) }
                }
            }
            MouseArea { anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onEntered: root.hover = index; onExited: root.hover = -1; onClicked: root.picked(index + 1) }
        }
    }
    Rectangle {
        visible: !root.noZero
        width: 22; height: 22; radius: 11; color: clrArea.containsMouse ? Theme.border : Theme.track; anchors.verticalCenter: parent.verticalCenter
        Icon { anchors.centerIn: parent; name: "x"; size: 10; lineWidth: 1.8; color: Theme.muted }
        MouseArea { id: clrArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.picked(null) }
    }
}
