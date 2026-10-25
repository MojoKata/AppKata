import QtQuick
import QtQuick.Controls.Basic
import "."

// "Install AppKata?" on the first start of a downloaded AppImage (requirement 2.11.3.1).
// offer: {version, image, dest, folder}
Dialog {
    id: root
    property var offer: ({})
    property bool deleteDownload: true
    title: "Install AppKata?"
    dialogWidth: 560
    function openWith(o) { offer = o || {}; deleteDownload = true; open() }
    function home(p) { return (p || "").replace(backend.locations.home, "~") }
    Row {
        spacing: 14
        Image { source: "assets/appkata.svg"; width: 48; height: 48; sourceSize: Qt.size(96, 96) }
        Text { width: root.dialogWidth - 60 - 62; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 14; lineHeight: 1.15
               anchors.verticalCenter: parent.verticalCenter
               text: "AppKata " + (root.offer.version || "") + " is running from where it was downloaded. Install it to keep it in your app"
                     + " menu and let it update itself." }
    }
    Rectangle {
        width: parent.width; height: col.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: col
            x: 16; y: 12; width: parent.width - 32; spacing: 8
            Row { spacing: 6
                Icon { name: "folder"; size: 14; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                Text { text: "Installs to " + root.home(root.offer.dest); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono } }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                   text: "Adds AppKata to the app menu with its icon, and points appkata:// links and starting at login at the installed copy." }
            CheckBox { id: cbDel; checked: root.deleteDownload; onToggled: root.deleteDownload = checked
                indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbDel.checked ? Theme.accent : "transparent"; border.width: cbDel.checked ? 0 : 1.6; border.color: Theme.borderStrong
                    Icon { anchors.centerIn: parent; visible: cbDel.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                contentItem: Text { leftPadding: 26; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13; font.bold: true; color: Theme.text
                                    text: "Delete the downloaded file" } }
            Text { leftPadding: 26; width: parent.width; elide: Text.ElideMiddle; text: root.home(root.offer.image)
                   color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono }
        }
    }
    footerLeft: [ Row { spacing: 2
        Text { text: "You can install it later from the"; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
        Icon { name: "dots"; size: 14; color: Theme.faint; anchors.verticalCenter: parent.verticalCenter }
        Text { text: "menu."; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } } ]
    footer: [
        FButton { text: "Run from here"; onClicked: { backend.declineSelfInstall(); root.close() } },
        FButton { text: "Install"; icon: "download"; primary: true; onClicked: { backend.installSelf(root.deleteDownload); root.close() } }
    ]
}
