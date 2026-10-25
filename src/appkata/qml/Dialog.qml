import QtQuick
import QtQuick.Controls.Basic
import "."

// A modal dialog shell: title, optional icon/subtitle, close button, body and footer slots.
Popup {
    id: root
    property string title
    property string subtitle: ""
    property var app: null
    property real dialogWidth: 560
    // a body taller than the window scrolls, so the footer stays in the dialog (review 3, R3-22); the
    // dialogs that scroll a part of their own body (Settings, Sandbox) turn it off
    property bool scrollBody: true
    default property alias body: bodyCol.data
    property alias footer: footerRow.data
    property alias footerLeft: footerLeftItem.data
    modal: true
    focus: true
    anchors.centerIn: Overlay.overlay
    width: dialogWidth
    padding: 30
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.scrim }
    background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
    contentItem: Column {
        id: frame
        spacing: 18
        Item {
            id: headItem
            width: parent.width; height: Math.max(38, head.height)
            Row {
                id: head
                spacing: 14
                AppIcon { visible: !!root.app; app: root.app || ({}); size: 40; anchors.verticalCenter: parent.verticalCenter }
                Column {
                    anchors.verticalCenter: parent.verticalCenter; spacing: 3
                    Text { visible: root.subtitle !== ""; text: root.subtitle; color: Theme.faint; font.bold: true; font.pixelSize: 12; font.letterSpacing: 0.8 }
                    Text { text: root.title; color: Theme.text; font.bold: true; font.pixelSize: 20 }
                }
            }
            IconButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; round: true; icon: "x"; onClicked: root.close() }
        }
        Flickable {
            id: bodyFlick
            // what the window leaves the body: its height less the header, the footer, the gaps, the
            // dialog's padding and 16 px above and below
            readonly property real room: Overlay.overlay ? Overlay.overlay.height - headItem.height - footItem.height
                                                           - 2 * frame.spacing - root.topPadding - root.bottomPadding - 32 : bodyCol.height
            width: parent.width
            height: root.scrollBody ? Math.min(bodyCol.height, Math.max(120, room)) : bodyCol.height
            contentHeight: bodyCol.height
            interactive: contentHeight > height
            clip: contentHeight > height
            layer.enabled: clip                 // icons ignore clipping in the software renderer (the tour's)
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; x: bodyFlick.width - 6 }
            Column { id: bodyCol; width: bodyFlick.width; spacing: 14 }
        }
        Item {
            id: footItem
            width: parent.width; height: footerRow.height
            Item { id: footerLeftItem; anchors.verticalCenter: parent.verticalCenter; width: parent.width - footerRow.width - 16; height: childrenRect.height }
            Row { id: footerRow; anchors.right: parent.right; spacing: 10 }
        }
    }
}
