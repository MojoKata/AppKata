import QtQuick
import "."

// A signer's avatar: initials on a gradient from their key (requirement 10.9).
Rectangle {
    id: root
    property var person: ({})
    property real size: 26
    property color ring: Theme.surface
    property bool dim: false
    width: size + 4; height: size + 4; radius: width / 2
    color: ring
    Rectangle {
        anchors.centerIn: parent
        width: root.size; height: root.size; radius: root.size / 2
        opacity: root.dim ? 0.4 : 1
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0; color: root.person.c1 || "#8089ff" }
            GradientStop { position: 1; color: root.person.c2 || "#4f46e5" }
        }
        Text {
            anchors.centerIn: parent
            text: root.size < 22 ? (root.person.init || "?").charAt(0) : (root.person.init || "?")
            color: "#ffffff"; font.bold: true; font.pixelSize: Math.max(7, root.size * 0.42)
        }
    }
}
