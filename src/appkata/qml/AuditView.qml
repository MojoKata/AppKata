import QtQuick
import QtQuick.Controls.Basic
import "."

// The Audit perspective (requirement 13): an immutable record of key operations, newest first,
// loaded a page at a time as the list scrolls.
Item {
    id: root
    property string kind: ""
    property string filter: ""
    property var rows: []
    property bool more: true
    function reload() { rows = []; more = true; loadMore() }
    function loadMore() {
        if (!more) return
        const last = rows.length ? rows[rows.length - 1].id : 0
        const page = backend.auditPage(last, kind, filter)
        more = page.length === 100
        rows = rows.concat(page)
    }
    onVisibleChanged: if (visible) reload()
    onKindChanged: reload()
    Connections { target: backend; function onAuditChanged() { if (root.visible) root.reload() } }
    readonly property var kinds: [["", "All"], ["app", "Apps"], ["source", "Sources"], ["trust", "Trusts"], ["authority", "Authorities"],
                                  ["review", "Reviews"], ["setting", "Settings"], ["actor:system", "System"]]
    readonly property var icons: ({ app: "apps", source: "branch", trust: "shieldCheck", authority: "key", review: "pencil", setting: "gear" })
    function dayLabel(iso) {
        const d = new Date(iso), t = new Date(Theme.now)
        const days = Math.floor((new Date(t.getFullYear(), t.getMonth(), t.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000)
        return days === 0 ? "Today" : days === 1 ? "Yesterday" : d.toLocaleDateString(Qt.locale("en_US"), "dddd, MMMM d, yyyy")
    }

    Text { id: title; x: 32; y: 30; text: "Audit"; color: Theme.text; font.pixelSize: 28; font.bold: true }
    Text { anchors.left: title.right; anchors.leftMargin: 14; anchors.baseline: title.baseline
           text: backend.auditCount + " entries · newest first"; color: Theme.muted; font.pixelSize: 14 }
    Field {
        anchors.right: parent.right; anchors.rightMargin: 32; y: 20; width: 260
        icon: "filter"; placeholder: "Filter by app, trust, key…"; clearable: true
        onEdited: t => { root.filter = t; debounce.restart() }
        Timer { id: debounce; interval: 300; onTriggered: root.reload() }
    }
    Row {
        x: 32; y: 76; spacing: 8
        Repeater {
            model: root.kinds
            Rectangle {
                readonly property bool on: root.kind === modelData[0]
                height: 28; width: kl.implicitWidth + 22; radius: 14
                color: on ? Theme.accentSoft : Theme.surface; border.color: on ? Theme.accent : Theme.border
                Text { id: kl; anchors.centerIn: parent; text: modelData[1]; color: parent.on ? Theme.accent : Theme.muted; font.bold: true; font.pixelSize: 12 }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.kind = modelData[0] }
            }
        }
    }

    ListView {      // virtualized: only visible rows exist (requirement 13.4)
        id: list
        objectName: "auditList"
        x: 32; y: 120; width: parent.width - 64; height: parent.height - y
        clip: true; spacing: 6
        layer.enabled: contentY > 0
        model: root.rows
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        onAtYEndChanged: if (atYEnd && root.more) root.loadMore()
        delegate: Column {
            width: list.width
            readonly property bool firstOfDay: index === 0 || root.dayLabel(root.rows[index - 1].at) !== root.dayLabel(modelData.at)
            Text {
                visible: parent.firstOfDay
                text: root.dayLabel(modelData.at).toUpperCase(); color: Theme.faint; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.2
                topPadding: index === 0 ? 0 : 14; bottomPadding: 8
            }
            Rectangle {
                width: parent.width; height: Math.max(54, body.implicitHeight + 22); radius: 12
                color: Theme.surface; border.color: Theme.border
                Rectangle {
                    x: 14; y: 13; width: 30; height: 30; radius: 15
                    color: modelData.actor === "sync" ? Theme.track : modelData.actor === "system" ? Theme.warnSoft : Theme.accentSoft
                    Icon { anchors.centerIn: parent; name: root.icons[modelData.kind] || "info"; size: 15
                           color: modelData.actor === "sync" ? Theme.muted : modelData.actor === "system" ? Theme.warn : Theme.accent }
                }
                Column {
                    id: body
                    x: 58; y: 11; width: parent.width - 58 - 170; spacing: 5
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.StyledText; color: Theme.text; font.pixelSize: 14
                        text: modelData.actor === "system" ? "<b>" + modelData.subject.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</b> " + modelData.action    // found changed by something else (16.9)
                              : (modelData.actor === "sync" ? "Sync " : "You ") + modelData.action + " <b>" + modelData.subject.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</b>"
                    }
                    Flow {
                        visible: modelData.details.length > 0 || !!modelData.url
                        width: parent.width; spacing: 6
                        Repeater {
                            model: modelData.details
                            Rectangle {
                                height: 20; width: dt.implicitWidth + 16; radius: 6; color: Theme.input; border.color: Theme.border
                                Text { id: dt; anchors.centerIn: parent; text: modelData[0] + " " + modelData[1]; color: Theme.muted; font.pixelSize: 11; font.family: Theme.mono }
                            }
                        }
                        Text { visible: !!modelData.url && modelData.kind !== "setting"; text: (modelData.url || "").replace("https://", "").replace("file://", "")
                               color: Theme.faint; font.pixelSize: 11; font.family: Theme.mono; height: 20; verticalAlignment: Text.AlignVCenter }
                    }
                }
                Pill {
                    anchors.right: time.left; anchors.rightMargin: 12; y: 15
                    text: modelData.actor === "sync" ? "Sync" : modelData.actor === "system" ? "System" : "You"; u: 0.85
                    color: modelData.actor === "sync" ? Theme.track : modelData.actor === "system" ? Theme.warnSoft : Theme.accentSoft
                    fg: modelData.actor === "sync" ? Theme.muted : modelData.actor === "system" ? Theme.warn : Theme.accent
                }
                Text {
                    id: time
                    anchors.right: parent.right; anchors.rightMargin: 16; y: 18
                    text: new Date(modelData.at).toLocaleTimeString(Qt.locale("en_US"), "HH:mm:ss")
                    color: Theme.faint; font.pixelSize: 12; font.family: Theme.mono
                }
            }
        }
        footer: Item {
            width: list.width; height: 50
            Text { anchors.centerIn: parent; visible: !root.more && root.rows.length > 0; text: "Start of the audit"; color: Theme.faint; font.pixelSize: 12 }
            Text { anchors.centerIn: parent; visible: root.more && root.rows.length > 0; text: "Loading more…"; color: Theme.faint; font.pixelSize: 12 }
        }
    }
    Text { visible: root.rows.length === 0; anchors.centerIn: parent; text: root.filter || root.kind ? "No entries match" : "Nothing recorded yet"
           color: Theme.muted; font.pixelSize: 15 }
}
