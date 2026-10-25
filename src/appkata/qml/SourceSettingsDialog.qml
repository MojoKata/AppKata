import QtQuick
import QtQuick.Controls.Basic
import "."

// Source settings (requirement 2.6): forge type, track only, prereleases, and the download filter
// for this platform with a live preview. From a Source's ⋯ menu, or from Add source before the
// Source exists (then Save hands the settings back instead of storing them).
Dialog {
    id: root
    property string url: ""
    property var s: ({})
    property bool pending: false            // from Add source
    property string forge: ""
    property bool trackOnly: false
    property var prereleases: null          // null: use Settings
    property var preview: ({})
    signal saved(var settings)
    title: "Source settings"
    subtitle: (backend.detail(url).name || url.replace(/^https:\/\//, "")).toUpperCase()
    app: backend.detail(url).name ? backend.detail(url) : null
    dialogWidth: 640
    function openFor(u, isPending, current) {
        url = u; pending = !!isPending
        s = backend.sourceSettings(u)
        const c = current || {}
        forge = c.forge !== undefined ? c.forge : s.forge
        trackOnly = c.trackOnly !== undefined ? c.trackOnly : s.trackOnly
        prereleases = c.prereleases !== undefined ? c.prereleases : s.prereleases
        filterField.text = c.assetFilter !== undefined ? c.assetFilter : s.assetFilter
        flatpakField.text = c.flatpak !== undefined ? c.flatpak : (s.flatpak || "")
        packageField.text = c["package"] !== undefined ? c["package"] : (s["package"] || "")
        preview = backend.previewAssetFilter(url, filterField.text)
        open()
    }
    function values() {
        const v = { forge: forge, trackOnly: trackOnly, prereleases: prereleases, assetFilter: filterField.text.trim() }
        if (s.channels) { v.flatpak = flatpakField.text.trim(); v["package"] = packageField.text.trim() }    // requirement 16.1.3
        return v
    }
    function hintText(h) {      // what applies without yours, and its check (requirement 2.6.7, 16.1.4)
        if (!h || !h.found) return "nothing found yet"
        return h.found + (h.from ? " · from " + h.from : "")
               + (h.check === "matches" ? " · matches the project" : h.check === "mismatch" ? " · " + (h.detail || "doesn't match the project") : " · unchecked")
    }

    component Toggle: Switch {
        id: sw
        padding: 0; spacing: 0
        indicator: Rectangle {
            x: sw.width - width; y: (sw.height - height) / 2
            implicitWidth: 38; implicitHeight: 22; radius: 11
            color: sw.checked ? Theme.accent : Theme.track; border.color: sw.checked ? Theme.accent : Theme.borderStrong
            Rectangle { x: sw.checked ? 18 : 2; y: 2; width: 18; height: 18; radius: 9; color: "#ffffff"; Behavior on x { NumberAnimation { duration: 120 } } }
        }
    }
    component Row2: Item {      // a label and hint on the left, a control on the right
        id: r2
        property string label
        property string hint: ""
        default property alias control: slot.data
        width: parent.width; height: Math.max(40, labels.height + 8)
        Column { id: labels; width: r2.width - slot.width - 24; spacing: 3; anchors.verticalCenter: parent.verticalCenter
            Text { text: r2.label; color: Theme.text; font.bold: true; font.pixelSize: 14 }
            Text { visible: r2.hint !== ""; text: r2.hint; width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12 } }
        Item { id: slot; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: childrenRect.width; height: childrenRect.height }
    }

    Text { text: root.url; color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono; width: parent.width; elide: Text.ElideMiddle }
    Row2 {
        label: "Forge"; hint: "Which API to use for this project. Detection is right for almost every host."
        Select {
            readonly property var opts: root.s.forges || []
            readonly property string recForge: (root.s.recommended || {}).forge || ""
            label: root.forge ? (opts.find(o => o[0] === root.forge) || ["", root.forge])[1]
                   : recForge ? "Recommended (" + ((opts.find(o => o[0] === recForge) || ["", recForge])[1]) + ")"
                   : "Detect automatically" + (root.s.detected ? " (" + root.s.detected + ")" : "")
            options: opts; onPicked: k => root.forge = k
        }
    }
    Row2 {
        label: "Track only"; hint: "Follow new versions without offering to install them, for example when a project publishes tags but no files."
        Toggle { checked: root.trackOnly; onToggled: root.trackOnly = checked }
    }
    Row2 {
        label: "Include pre-releases"; hint: "Beta and release-candidate versions."
        Rectangle {
            width: 330; height: 32; radius: 9; color: Theme.track
            Row { x: 3; y: 3
                Repeater {
                    model: [[null, "Default (" + (root.s.prereleasesDefault ? "On" : "Off") + ")"], [true, "Yes"], [false, "No"]]
                    Rectangle { width: 108; height: 26; radius: 7; color: root.prereleases === modelData[0] ? Theme.segOn : "transparent"
                        Text { anchors.centerIn: parent; text: modelData[1]; font.bold: true; font.pixelSize: 12
                               color: root.prereleases === modelData[0] ? Theme.text : Theme.muted }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.prereleases = modelData[0] } } } }
        }
    }
    Row2 {      // the app's Flatpak (requirement 2.6.7, 16.1.3)
        visible: !!root.s.channels
        label: "Flatpak"; hint: "An app ID, optionally after its remote. Empty: " + root.hintText(root.s.flatpakHint)
        Field { id: flatpakField; width: 260; mono: true; placeholder: (root.s.flatpakHint || {}).found || "org.example.App" }
    }
    Row2 {
        visible: !!root.s.channels
        label: "Package"; hint: "The " + (root.s.distro || "distribution") + " package. Empty: " + root.hintText(root.s.packageHint)
        Field { id: packageField; width: 260; mono: true; placeholder: (root.s.packageHint || {}).found || "package-name" }
    }
    Column {    // requirement 2.6.4
        width: parent.width; spacing: 8
        Text { text: "Download filter for " + (root.s.platform || "this computer"); color: Theme.text; font.bold: true; font.pixelSize: 14 }
        Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
               text: "A regular expression for the file name. Leave it empty to let AppKata choose. Other platforms keep their own filter." }
        Field {
            id: filterField
            width: parent.width; mono: true
            placeholder: (root.s.recommended || {}).assetFilter || "e.g. linux-x86_64\\.AppImage$"
            error: !!root.preview.bad
            onEdited: previewTimer.restart()
        }
        Timer { id: previewTimer; interval: 250; onTriggered: root.preview = backend.previewAssetFilter(root.url, filterField.text.trim()) }
        Row {
            spacing: 8
            readonly property bool good: !!root.preview.file
            Rectangle { width: 20; height: 20; radius: 10; color: parent.good ? Theme.okSoft : Theme.warnSoft; anchors.verticalCenter: parent.verticalCenter
                        Icon { anchors.centerIn: parent; name: parent.parent.good ? "check" : "warn"; size: 11; lineWidth: 2; color: parent.parent.good ? Theme.ok : Theme.warn } }
            Text { anchors.verticalCenter: parent.verticalCenter; color: parent.good ? Theme.text : Theme.warn; font.pixelSize: 12
                   font.family: parent.good ? Theme.mono : Qt.application.font.family
                   text: parent.good ? root.preview.file : (root.preview.note || "") }
        }
        Text { visible: !!root.preview.file
               text: filterField.text.trim() ? "Picked by your filter from the latest release"
                     : root.preview.recommended ? "Picked by the filter " + root.preview.by + " recommends, from the latest release"
                     : "AppKata's choice from the latest release"
               color: Theme.faint; font.pixelSize: 11 }
    }
    footerLeft: Text { width: 240; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                       text: root.pending ? "Saved with the Source when you add it." : "Saving checks the project again." }
    footer: [
        FButton { text: "Cancel"; onClicked: root.close() },
        FButton { text: "Save"; primary: true; enabledButton: !root.preview.bad
                  onClicked: { if (root.pending) root.saved(root.values()); else backend.setSourceSettings(root.url, root.values()); root.close() } }
    ]
}
