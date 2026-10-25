import QtQuick
import "."

// Removing a Source (requirement 7.3).
Dialog {
    id: root
    property var src: ({})
    readonly property bool installed: ["installed", "update", "held", "pinned", "selfupdating", "system"].indexOf(src.state) >= 0
    readonly property int trusts: (src.trusts || []).length
    title: "Remove " + (src.name || "") + "?"
    app: src
    dialogWidth: 520
    function openFor(s) { src = s; open() }
    Text { text: (root.src.host || "") + "/" + (root.src.repo || ""); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono }
    Text {
        width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 14; lineHeight: 1.2
        text: root.installed ? (root.src.name + " " + root.src.installed + " was installed by AppKata. You can uninstall it too, or keep it installed.")
                             : "It will no longer be one of your sources."
    }
    Rectangle {     // requirement 7.3.2
        visible: root.installed || root.trusts > 0
        width: parent.width; height: 44; radius: 11; color: root.trusts > 0 ? Theme.accentSoft : Theme.warnSoft
        Row {
            x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            AvatarStack { visible: root.trusts > 0; people: (root.src.trusts || []).map(t => t.avatars[0]); size: 18; ring: Theme.accentSoft; anchors.verticalCenter: parent.verticalCenter }
            Icon { visible: root.trusts === 0; name: "warn"; color: Theme.warn; lineWidth: 1.7; anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter; color: Theme.text; font.pixelSize: 13
                text: root.trusts > 0 ? "Also listed by " + root.trusts + " trust" + (root.trusts > 1 ? "s" : "") + ", so it stays in the Catalog."
                                      : "If you keep it, it won’t get any more updates through AppKata."
            }
        }
    }
    footer: [
        FButton { text: "Cancel"; onClicked: root.close() },
        FButton { visible: root.installed; text: "Remove only"; onClicked: { backend.removeSource(root.src.url, false); root.close() } },
        FButton { text: root.installed ? "Remove and uninstall" : "Remove source"; icon: "trash"; primary: true; danger: true
                  onClicked: { backend.removeSource(root.src.url, root.installed); root.close() } }
    ]
}
