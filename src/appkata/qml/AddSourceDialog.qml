import QtQuick
import QtQuick.Controls.Basic
import "."

// Adding a Source (requirement 7.2): detect the forge, preview, then add (or add and install).
Dialog {
    id: root
    property var p: null
    property bool checking: false
    property alias urlField: urlBox
    property alias settingsDialog: ssd
    property var pendingSettings: ({})      // chosen in Source settings before adding (requirement 7.2)
    title: "Add source"
    dialogWidth: 600
    // `link`: a Flatpak or package found by Explore, kept as the Source's channel link (requirement 16.2.4)
    function openWith(text, link) { p = null; checking = false; pendingSettings = link || ({}); urlBox.text = text || ""; open(); if (text) check() }
    SourceSettingsDialog { id: ssd; onSaved: st => root.pendingSettings = st }
    function check() { if (!urlBox.text.trim()) return; checking = true; p = null; backend.previewSource(urlBox.text.trim()) }
    Connections { target: backend; function onSourcePreview(res) { if (res.input === urlBox.text.trim()) { root.p = res; root.checking = false } } }
    Timer { id: debounce; interval: 700; onTriggered: root.check() }

    Column {
        width: parent.width; spacing: 8
        Text { text: "Project or releases URL"; color: Theme.muted; font.bold: true; font.pixelSize: 13 }
        Field { id: urlBox; width: parent.width; height: 42; mono: true; placeholder: "https://github.com/owner/project"
                error: !!root.p && !root.p.ok; onEdited: debounce.restart(); onAccepted: root.check() }
        Text { text: "A forge project, a releases page, or an ngit nostr:// address."; color: Theme.faint; font.pixelSize: 12 }
    }
    Row {
        visible: root.checking; spacing: 10
        BusyIndicator { width: 22; height: 22; running: root.checking }
        Text { text: "Checking…"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
    }
    Text { visible: !!root.p && !root.p.ok; width: parent.width; wrapMode: Text.WordWrap; color: Theme.err; font.pixelSize: 13; text: root.p ? (root.p.error || "") : "" }
    Column {
        visible: !!root.p && !!root.p.ok
        width: parent.width; spacing: 12
        Repeater {
            model: root.p && root.p.ok ? [
                [root.p.forge + " detected", root.p.host + (root.p.releasesPage ? " · from the releases page" : ""), false],
                [root.p.releases ? "Releases found" : "No releases", root.p.releases ? root.p.releases + " releases · latest " + root.p.version + ", " + Theme.shortDate(root.p.date) : "It can still be tracked by tags", false],
                [root.p.asset ? "Download chosen for this computer" : "No download for this computer", root.p.asset ? root.p.asset + (root.p.assetSize ? " · " + Math.round(root.p.assetSize / 1e6) + " MB" : "") : root.p.assetReason, true]] : []
            Row {
                spacing: 10
                readonly property bool good: index < 2 ? root.p.releases > 0 || index === 0 : !!root.p.asset
                Rectangle { width: 22; height: 22; radius: 11; color: parent.good ? Theme.okSoft : Theme.warnSoft
                            Icon { anchors.centerIn: parent; name: parent.parent.good ? "check" : "warn"; size: 12; lineWidth: 2; color: parent.parent.good ? Theme.ok : Theme.warn } }
                Column { spacing: 3
                    Text { text: modelData[0]; color: Theme.text; font.bold: true; font.pixelSize: 14 }
                    Text { text: modelData[1]; color: Theme.muted; font.pixelSize: 12; font.family: modelData[2] ? Theme.mono : Qt.application.font.family } }
            }
        }
        Rectangle {
            visible: !!root.p && root.p.listedBy && root.p.listedBy.length > 0
            width: parent.width; height: 56; radius: 11; color: Theme.accentSoft
            Column {
                x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 3; width: parent.width - 28
                Text { width: parent.width; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 13; textFormat: Text.StyledText
                       text: root.p && root.p.listedBy ? "Already listed by <b>" + root.p.listedBy.join(", ") + "</b>" : "" }
                Text { text: "Adding it makes it your own source too."; color: Theme.muted; font.pixelSize: 12 }
            }
        }
        Text { visible: !!root.p && root.p.exists; text: "This source is already in your list."; color: Theme.warn; font.pixelSize: 13 }
        Row {       // requirement 7.2 step 3
            visible: !!root.p && !root.p.exists
            spacing: 6
            readonly property int n: Object.keys(root.pendingSettings).filter(k => { const v = root.pendingSettings[k]; return v !== "" && v !== null && v !== false }).length
            Icon { name: "gear"; size: 14; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "Source settings" + (parent.n ? " · " + parent.n + " changed" : ""); color: Theme.accent; font.bold: true; font.pixelSize: 13
                   MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: ssd.openFor(root.p.url, true, root.pendingSettings) } }
            Icon { name: "chevRight"; size: 12; lineWidth: 1.8; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    footer: [
        FButton { text: "Add and install"; icon: "download"; enabledButton: !!root.p && root.p.ok && !!root.p.asset && !root.p.exists
                  onClicked: { backend.addSourceWith(urlBox.text.trim(), true, root.pendingSettings); root.close() } },
        FButton { text: "Add source"; primary: true; enabledButton: !!root.p && root.p.ok && !root.p.exists
                  onClicked: { backend.addSourceWith(urlBox.text.trim(), false, root.pendingSettings); root.close() } }
    ]
}
