import QtQuick
import QtQuick.Controls.Basic
import "."

// A text field: optional leading icon and clear button.
Rectangle {
    id: root
    property alias text: input.text
    property string placeholder: ""
    property string icon: ""
    property bool clearable: false
    property bool mono: false
    property bool error: false
    property alias field: input
    signal edited(string text)
    signal accepted()
    height: 38
    radius: 11
    color: Theme.input
    border.width: input.activeFocus || error ? 2 : 1
    border.color: error ? Theme.err : input.activeFocus ? Theme.accent : Theme.border
    Icon { id: ic; visible: root.icon !== ""; name: root.icon; color: Theme.muted; x: 12; anchors.verticalCenter: parent.verticalCenter }
    TextField {
        id: input
        x: root.icon !== "" ? 34 : 6
        width: parent.width - x - (clear.visible ? 34 : 6)
        anchors.verticalCenter: parent.verticalCenter
        background: null
        color: Theme.text
        placeholderText: root.placeholder
        placeholderTextColor: Theme.faint
        selectByMouse: true
        selectionColor: Theme.accentSoft
        selectedTextColor: Theme.text
        font.pixelSize: 14
        font.family: root.mono ? Theme.mono : Qt.application.font.family
        onTextEdited: root.edited(text)
        onTextChanged: if (!activeFocus) cursorPosition = 0      // long paths: show where they start
        onActiveFocusChanged: if (!activeFocus) cursorPosition = 0
        onAccepted: root.accepted()
    }
    Rectangle {
        id: clear
        visible: root.clearable && input.text !== ""
        anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
        width: 20; height: 20; radius: 10; color: Theme.track
        Icon { anchors.centerIn: parent; name: "x"; size: 10; lineWidth: 1.8; color: Theme.muted }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: { input.text = ""; root.edited("") } }
    }
}
