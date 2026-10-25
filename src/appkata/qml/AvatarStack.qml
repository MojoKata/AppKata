import QtQuick
import "."

// Partly overlapping avatars, "+N" after four (requirement 7.6.3). Hovering one reports it.
Item {
    id: root
    property var people: []
    property real size: 26
    property color ring: Theme.surface
    property int max: 4
    signal hovered(int index, var person, real x)
    signal unhovered()
    readonly property real step: size * 0.68
    readonly property int shown: Math.min(people.length, max)
    width: shown > 0 ? (size + 4) + (shown - 1 + (people.length > max ? 1 : 0)) * step : 0
    height: size + 4
    Repeater {
        model: root.shown
        Avatar {
            x: index * root.step
            z: root.shown - index
            person: root.people[index]
            size: root.size
            ring: root.ring
            MouseArea {
                anchors.fill: parent; hoverEnabled: true
                onEntered: root.hovered(index, root.people[index], parent.x)
                onExited: root.unhovered()
            }
        }
    }
    Rectangle {
        visible: root.people.length > root.max
        x: root.max * root.step; z: 0
        width: root.size + 4; height: width; radius: width / 2; color: root.ring
        Rectangle {
            anchors.centerIn: parent; width: root.size; height: root.size; radius: width / 2; color: Theme.track
            Text { anchors.centerIn: parent; text: "+" + (root.people.length - root.max); color: Theme.muted; font.bold: true; font.pixelSize: Math.max(8, root.size * 0.4) }
        }
    }
}
