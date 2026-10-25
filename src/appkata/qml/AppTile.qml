import QtQuick
import "."

// A Catalog tile (requirement 12.3, 12.4), designed at 300 × 210 and scaled with its width.
Rectangle {
    id: root
    property var app: ({})
    property bool selected: false
    property bool tagsHover: false
    property alias moreButton: more
    signal clicked()
    signal tagsRequested(var app, Item anchor)
    readonly property real k: Math.min(1.15, width / 300)
    readonly property var marks: ({
        update: ["Update", Theme.accentSoft, Theme.accent, "update"], installed: ["Installed", Theme.okSoft, Theme.ok, "check"],
        held: ["Installed", Theme.okSoft, Theme.ok, "check"], pinned: ["Installed", Theme.okSoft, Theme.ok, "check"],
        selfupdating: ["Installed", Theme.okSoft, Theme.ok, "check"], system: ["Installed", Theme.okSoft, Theme.ok, "check"],
        foreign: ["Outside AppKata", Theme.warnSoft, Theme.warn, "info"] })
    radius: 16
    color: Theme.surface
    border.width: selected ? 2 : 1
    border.color: selected ? Theme.accent : app.vetoed ? Theme.err : Theme.border

    Rectangle {     // soft glow of the icon's colours
        x: 1; y: 1; width: parent.width - 2; height: 88 * root.k; radius: 15
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.alpha(root.app.c1 || "#8089ff", Theme.dark ? 0.14 : 0.10) }
            GradientStop { position: 1; color: Theme.alpha(root.app.c2 || "#8089ff", 0) }
        }
    }
    Item {
        anchors.fill: parent
        opacity: root.app.vetoed ? 0.6 : 1
        AppIcon { id: icon; x: 18; y: 18; app: root.app; size: 56 * root.k }
        Text {
            id: name
            x: icon.x + icon.width + 14; y: (mark.visible ? 38 : 28) * root.k
            width: root.width - x - 18
            text: root.app.name || ""; elide: Text.ElideRight
            color: Theme.text; font.bold: true; font.pixelSize: 16 * root.k
        }
        Row {
            x: name.x; anchors.top: name.bottom; anchors.topMargin: 4 * root.k
            spacing: 8
            Text { text: root.app.version ? "v" + root.app.version : (root.app.error ? "—" : "…"); color: Theme.muted; font.pixelSize: 12 * root.k; anchors.verticalCenter: parent.verticalCenter }
            Origin { app: root.app; u: root.k; ring: Theme.surface; anchors.verticalCenter: parent.verticalCenter }
        }
        Text {
            x: 18; y: 96 * root.k; width: root.width - 36
            text: root.app.summary || root.app.description || ""
            wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
            color: Theme.muted; font.pixelSize: 13 * root.k; lineHeight: 1.12
        }
    }
    readonly property var busy: backend.busy[app.url]
    Pill {     // state mark (requirement 12.4); "Installing 45%" while it installs (4.8.1)
        id: mark
        visible: !!root.marks[root.app.state] || !!root.app.vetoed || !!root.busy
        anchors.right: parent.right; anchors.rightMargin: 12; y: 12
        readonly property var m: root.busy ? [Theme.busyLabel(root.busy).replace("Downloading", "Installing"), Theme.accentSoft, Theme.accent, "download"]
                                 : root.app.vetoed ? ["Avoid", Theme.errSoft, Theme.err, "warn"] : (root.marks[root.app.state] || ["", "", "", ""])
        text: m[0]; color: m[1]; fg: m[2]; icon: m[3]; u: 0.88; size: 12
    }
    // footer: badge, tags trimmed to fit with a › button (requirement 12.4.1)
    Rectangle { x: 16; width: parent.width - 32; height: 1; y: parent.height - 44 * root.k; color: Theme.border }
    TrustBadge { id: badge; app: root.app; u: Math.min(1.08, root.k); x: 18; y: root.height - 22 * root.k - height / 2 }
    Row {
        id: tagRow
        anchors.right: parent.right; anchors.rightMargin: 16
        y: root.height - 22 * root.k - 10
        spacing: 5
        readonly property real avail: root.width - 16 - (badge.x + badge.width + 8)
        readonly property real cu: Math.min(1.1, root.k)
        readonly property var widths: (root.app.tags || []).map(t => fm.advanceWidth(t) + 18 * cu)
        FontMetrics { id: fm; font.bold: true; font.pixelSize: 11 * tagRow.cu }
        readonly property int shown: {
            const ws = widths, total = ws.reduce((a, b) => a + b + 5, -5)
            if (total <= avail) return ws.length
            let used = 22, n = 0
            while (n < ws.length && used + ws[n] + 5 <= avail) { used += ws[n] + 5; n++ }
            return n
        }
        Repeater {
            model: (root.app.tags || []).slice(0, tagRow.shown)
            Chip { text: modelData; u: tagRow.cu; on: backend.tag === modelData; onClicked: backend.selectTag(modelData) }
        }
        Rectangle {
            id: more
            objectName: "more"
            visible: tagRow.shown < (root.app.tags || []).length
            width: 22; height: 20; radius: 10
            color: root.tagsHover || moreArea.containsMouse ? Theme.accentSoft : Theme.track
            border.width: root.tagsHover || moreArea.containsMouse ? 1 : 0; border.color: Theme.accent
            Icon { anchors.centerIn: parent; name: "chevRight"; size: 12; lineWidth: 1.9; color: root.tagsHover || moreArea.containsMouse ? Theme.accent : Theme.muted }
            MouseArea {
                id: moreArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onEntered: root.tagsRequested(root.app, more)
                onClicked: root.tagsRequested(root.app, more)
            }
            Keys.onReturnPressed: root.tagsRequested(root.app, more)
            activeFocusOnTab: visible
        }
    }
    MouseArea { anchors.fill: parent; z: -1; cursorShape: Qt.PointingHandCursor; onClicked: root.clicked() }
}
