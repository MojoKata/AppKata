import QtQuick
import "."

// Combined Trust (shield) and Rating (stars) with the reviewer count; "Avoid" or "Unreviewed" (requirement 12.4).
Item {
    id: root
    property var app: ({})
    property real u: 1
    implicitWidth: row.implicitWidth
    implicitHeight: 22 * u
    Row {
        id: row
        anchors.verticalCenter: parent.verticalCenter
        spacing: 5 * root.u
        Pill {
            visible: !!root.app.vetoed
            text: "Avoid"; icon: "warn"; fg: Theme.err; color: Theme.errSoft; u: root.u * 0.92; size: 12
        }
        Pill {
            visible: !root.app.vetoed && !root.app.reviewers
            text: "Unreviewed"; fg: Theme.muted; color: Theme.track; u: root.u * 0.92; size: 11
        }
        Icon {
            visible: !root.app.vetoed && root.app.reviewers > 0 && root.app.trust !== null && root.app.trust !== undefined
            name: "shieldCheck"; color: Theme.ok; size: 16 * root.u; anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: !root.app.vetoed && root.app.reviewers > 0 && root.app.trust !== null && root.app.trust !== undefined
            text: root.app.trust !== null && root.app.trust !== undefined ? Number(root.app.trust).toFixed(1) : ""
            color: Theme.text; font.bold: true; font.pixelSize: 13 * root.u; anchors.verticalCenter: parent.verticalCenter
        }
        Stars {
            visible: !root.app.vetoed && root.app.reviewers > 0 && root.app.rating !== null && root.app.rating !== undefined
            value: root.app.rating || 0; r: 5.2 * root.u; anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: !root.app.vetoed && root.app.reviewers > 0
            text: "(" + root.app.reviewers + ")"; color: Theme.faint; font.pixelSize: 12 * root.u; anchors.verticalCenter: parent.verticalCenter
        }
    }
}
