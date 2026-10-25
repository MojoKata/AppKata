import QtQuick
import "."

// The app's icon (requirement 3.2), or a generated gradient tile with its initials.
Item {
    id: root
    property var app: ({})
    property real size: 56
    width: size; height: size
    readonly property bool hasImage: !!app.icon && img.status !== Image.Error
    Rectangle {
        anchors.fill: parent
        radius: root.size * 0.26
        visible: !root.hasImage || img.status !== Image.Ready
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0; color: root.app.c1 || "#8089ff" }
            GradientStop { position: 1; color: root.app.c2 || "#4f46e5" }
        }
        Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.color: "#ffffff"; opacity: 0.14 }
        Text {
            anchors.centerIn: parent
            text: root.app.init || "?"
            color: "#ffffff"; font.bold: true; font.pixelSize: root.size * 0.38
        }
    }
    Rectangle {      // a soft plate behind real icons so transparent ones read on both themes
        anchors.fill: parent
        visible: root.hasImage && img.status === Image.Ready
        radius: root.size * 0.26
        // a plate behind the icon: dark for light glyphs, light for dark ones (backend.icon_tone)
        color: root.app.iconTone === "dark" ? "#2a2e3a" : root.app.iconTone === "light" ? "#f5f6fa" : Theme.dark ? "#2a2e3a" : "#ffffff"
        border.color: Theme.border
        Image {
            id: img
            anchors.fill: parent; anchors.margins: root.size * 0.1
            source: Theme.fileUrl(root.app.icon || "")
            sourceSize: Qt.size(root.size * 2, root.size * 2)
            fillMode: Image.PreserveAspectFit
            smooth: true; mipmap: true; asynchronous: true
        }
    }
}
