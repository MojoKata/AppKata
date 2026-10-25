import QtQuick
import "."

// A Source (requirement 7.1.1): icon, name, chips, URL, forge, version, error, ⋯ menu.
Rectangle {
    id: root
    property var src: ({})
    property bool menuOpen: false
    property bool trustsHover: false
    property bool highlighted: false        // opened from an app's "Source" pill (requirement 2.9.5)
    signal menu(Item anchor)
    signal trustsRequested(Item anchor)
    signal openTrust(int id)
    readonly property var chips: {
        const c = []
        if (["installed", "update", "held", "pinned", "selfupdating", "system"].indexOf(src.state) >= 0) c.push(["Installed", Theme.okSoft, Theme.ok, ""])
        if (src.foreign) c.push(["Installed outside AppKata", Theme.warnSoft, Theme.warn, "info"])
        if (src.builtin) c.push(["Built in", Theme.accentSoft, Theme.accent, ""])
        if (src.pinned) c.push(["Pinned at " + src.pinned, Theme.track, Theme.muted, "pin"])
        if (src.trackOnly) c.push(["Track only", Theme.track, Theme.muted, ""])
        return c
    }
    height: src.errorText ? 86 : 70
    radius: 12
    color: highlighted ? Theme.accentSoft : Theme.surface; border.color: highlighted ? Theme.accent : Theme.border
    border.width: highlighted ? 1.5 : 1
    AppIcon { x: 16; y: 15; size: 40; app: root.src }
    Row {
        x: 70; y: 13; spacing: 6
        Text { text: root.src.name || ""; color: Theme.text; font.bold: true; font.pixelSize: 15; anchors.verticalCenter: parent.verticalCenter; rightPadding: 4 }
        Repeater {
            model: root.chips
            Pill { text: modelData[0]; color: modelData[1]; fg: modelData[2]; icon: modelData[3]; u: 0.8; size: 13; anchors.verticalCenter: parent.verticalCenter }
        }
        Rectangle {     // also listed by Trusts (requirement 2.9.4)
            id: inTrusts
            objectName: "inTrusts"
            visible: (root.src.trusts || []).length > 0
            height: 19; width: tr.implicitWidth + 14; radius: 9.5; anchors.verticalCenter: parent.verticalCenter
            color: root.trustsHover || itArea.containsMouse ? Theme.accentSoft : Theme.track
            border.width: root.trustsHover || itArea.containsMouse ? 1 : 0; border.color: Theme.accent
            readonly property int n: (root.src.trusts || []).length
            Row {
                id: tr; anchors.centerIn: parent; spacing: 5
                AvatarStack { people: (root.src.trusts || []).map(t => t.avatars[0]); size: 13; ring: inTrusts.color; anchors.verticalCenter: parent.verticalCenter }
                Text { text: "In " + inTrusts.n + " trust" + (inTrusts.n > 1 ? "s" : ""); color: Theme.accent; font.bold: true; font.pixelSize: 11; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea { id: itArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onEntered: root.trustsRequested(inTrusts)
                        // one Trust: open it; several: the popup lists them, each with Open (requirement 7.1.1)
                        onClicked: inTrusts.n === 1 ? root.openTrust(root.src.trusts[0].id) : root.trustsRequested(inTrusts) }
        }
    }
    Text { x: 70; y: 40; text: root.src.inputUrl || root.src.url || ""; color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono
           width: root.width - 70 - 200; elide: Text.ElideMiddle }
    Row {
        visible: !!root.src.errorText
        x: 70; y: 60; spacing: 6
        Icon { name: "clock"; size: 13; color: Theme.warn; anchors.verticalCenter: parent.verticalCenter }
        Text { text: root.src.errorText || ""; color: Theme.warn; font.bold: true; font.pixelSize: 12 }
    }
    Column {
        anchors.right: parent.right; anchors.rightMargin: 60; y: 15; spacing: 4
        Text { anchors.right: parent.right; text: root.src.version ? "v" + root.src.version : "—"; color: Theme.text; font.bold: true; font.pixelSize: 13; font.family: Theme.mono }
        Text { anchors.right: parent.right
               text: (({ github: "GitHub", gitlab: "GitLab", forgejo: "Forgejo", gitea: "Gitea", ghe: "GitHub Enterprise" })[root.src.forge] || root.src.host || "")
                     + (root.src.date ? " · " + Theme.shortDate(root.src.date) : "")
               color: Theme.faint; font.pixelSize: 12 }
    }
    Rectangle {
        id: dots
        objectName: "dots"
        anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
        width: 30; height: 30; radius: 15
        color: root.menuOpen ? Theme.accentSoft : dArea.containsMouse ? Theme.track : "transparent"
        border.width: root.menuOpen ? 1.5 : 0; border.color: Theme.accent
        Icon { anchors.centerIn: parent; name: "more"; color: root.menuOpen ? Theme.accent : Theme.muted }
        MouseArea { id: dArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.menu(dots) }
    }
}
