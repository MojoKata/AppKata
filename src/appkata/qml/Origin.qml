import QtQuick
import "."

// Where an app comes from (requirement 2.9.3): branch icon for a Source, avatars for its Trusts.
Row {
    id: root
    property var app: ({})
    property real u: 1
    property color ring: Theme.surface
    spacing: 4
    Icon { visible: !!root.app.src; name: "branch"; size: 14 * root.u; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
    AvatarStack {
        visible: (root.app.trusts || []).length > 0
        people: (root.app.trusts || []).map(t => t.avatars[0])
        size: 14 * root.u; ring: root.ring
        anchors.verticalCenter: parent.verticalCenter
    }
}
