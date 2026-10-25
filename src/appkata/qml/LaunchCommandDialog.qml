import QtQuick
import QtQuick.Controls.Basic
import "."

// "Show the launch command" (requirement 17.4; review 2, F11): the generated launcher's text, exactly
// what runs when the app starts sandboxed, with the hash of it the Audit records at each change.
Dialog {
    id: root
    property string url: ""
    property string command: ""
    property string hash: ""
    title: "Launch command"
    subtitle: "SANDBOX"
    app: backend.detail(url || "")
    dialogWidth: 780
    function openFor(u) {
        url = u
        command = backend.sandboxLaunchCommand(u)
        const info = backend.sandboxInfo(u) || ({})
        hash = info.launcherHash || ""
        open()
    }
    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
           text: "What runs when " + (root.app ? root.app.name : "the app") + " starts, from its menu entry, its command or AppKata's Open."
                 + (root.hash ? " The Audit records it as " + root.hash + "." : "") }
    ScrollView {
        width: parent.width; height: 400; clip: true
        TextArea {
            id: area; objectName: "launchCommand"
            readOnly: true; selectByMouse: true; wrapMode: TextEdit.NoWrap
            text: root.command; color: Theme.text; font.family: Theme.mono; font.pixelSize: 11
            background: Rectangle { radius: 9; color: Theme.input; border.color: Theme.border }
        }
    }
    footer: [
        FButton { text: "Copy"; icon: "copy"; onClicked: { area.selectAll(); area.copy(); area.deselect() } },
        FButton { text: "Close"; primary: true; onClicked: root.close() }
    ]
}
