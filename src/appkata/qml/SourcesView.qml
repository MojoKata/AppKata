import QtQuick
import QtQuick.Controls.Basic
import "."

// The Sources perspective (requirement 7): Sources list plus the Trust panel.
Item {
    id: root
    signal addSource()
    signal explore()
    signal removeSource(var src)
    signal addTrust()
    signal sourceSettings(string url)
    signal confirmAction(string kind, var args)
    property alias trustPanel: trusts
    property string highlightUrl: ""
    property alias sourceMenu: srcMenu
    property alias trustsPopup: trustsPop
    property string filter: ""
    property var menuSrc: ({})
    property string trustsHoverUrl: ""
    readonly property real panelW: backend.prefs.trustPanelOpen === false ? 56 : 400
    readonly property var items: filter ? backend.sourceItems.filter(s => (s.name + " " + s.url).toLowerCase().indexOf(filter.toLowerCase()) >= 0)
                                        : backend.sourceItems
    readonly property real rightEdge: width - panelW - 28

    Text { id: title; x: 32; y: 30; text: "Sources"; color: Theme.text; font.pixelSize: 28; font.bold: true }
    Text { anchors.left: title.right; anchors.leftMargin: 14; anchors.baseline: title.baseline
           text: backend.sourceItems.length + " source" + (backend.sourceItems.length === 1 ? "" : "s"); color: Theme.muted; font.pixelSize: 14 }
    FButton { id: addBtn; x: root.rightEdge - width; y: 22; text: "Add source"; icon: "plus"; primary: true; onClicked: root.addSource() }
    FButton { id: exploreBtn; x: addBtn.x - 10 - width; y: 22; text: "Explore"; icon: "compass"; onClicked: root.explore() }     // requirement 7.7.1
    Field { x: exploreBtn.x - 12 - width; y: 22; width: 170; height: 34; icon: "filter"; placeholder: "Filter"; clearable: true; onEdited: t => root.filter = t }

    Flickable {
        id: flick
        x: 0; y: 80; width: root.rightEdge + 28; height: parent.height - y
        contentHeight: list.height + 30; clip: true
        layer.enabled: contentY > 0
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Column {
            id: list
            x: 32; width: root.rightEdge - 32; spacing: 8
            Repeater {
                model: root.items
                SourceRow {
                    width: list.width; src: modelData
                    menuOpen: srcMenu.visible && root.menuSrc.url === modelData.url
                    trustsHover: trustsPop.visible && root.trustsHoverUrl === modelData.url
                    highlighted: root.highlightUrl === modelData.url
                    onMenu: anchor => root.openMenu(modelData, anchor)
                    onTrustsRequested: anchor => root.showTrusts(modelData, anchor)
                    onOpenTrust: id => trusts.select(id)
                }
            }
        }
    }
    Column {
        visible: backend.sourceItems.length === 0
        x: 32; y: 120; width: root.rightEdge - 32; spacing: 12
        Text { text: "No sources yet"; color: Theme.text; font.bold: true; font.pixelSize: 16 }
        Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13
               text: "A Source is an app you've decided to trust yourself: add its git project URL (GitHub, GitLab, Forgejo or Gitea) or its releases page." }
    }

    // an app's "Source" pill (requirement 2.9.5): scroll to its row and highlight it for a while
    function showSource(url) {
        filter = ""; highlightUrl = url
        const i = backend.sourceItems.findIndex(s => s.url === url)
        if (i >= 0) Qt.callLater(() => { const row = list.children[i]; if (row) flick.contentY = Math.max(0, Math.min(row.y - 40, flick.contentHeight - flick.height)) })
        highlightTimer.restart()
    }
    Timer { id: highlightTimer; interval: 4000; onTriggered: if (!tourMode) root.highlightUrl = "" }
    function openMenu(s, anchor) {
        menuSrc = s
        const p = anchor.mapToItem(root, anchor.width, anchor.height)
        srcMenu.x = p.x - srcMenu.width
        srcMenu.y = p.y + 290 > root.height ? p.y - anchor.height - 296 : p.y + 6     // opens upward near the bottom
        srcMenu.open()
    }
    function showTrusts(s, anchor) {
        trustsHoverUrl = s.url
        trustsPop.listing = backend.trustsListing(s.url)
        const p = anchor.mapToItem(root, 0, anchor.height)
        trustsPop.x = p.x; trustsPop.y = p.y + 6
        trustsPop.open()
    }
    PopMenu {     // requirement 7.1.3
        id: srcMenu
        menuWidth: 280
        items: [
            { key: "pin", icon: "pin", text: root.menuSrc.pinned ? "Unpin" : "Pin" + (root.menuSrc.installed ? " at " + root.menuSrc.installed : ""),
              enabled: !!root.menuSrc.installed },
            { key: "settings", icon: "gear", text: "Source settings…", note: "Track only, pre-releases, download filter" },
            { key: "page", icon: "open", text: "Open project page" },
            { type: "separator" },
            { key: "remove", icon: "trash", text: "Remove source", danger: true, enabled: !root.menuSrc.builtin,
              note: root.menuSrc.builtin ? "AppKata's own Source is built in" : "" }]
        onTriggered: key => {
            if (key === "pin") backend.setPinned(root.menuSrc.url, !root.menuSrc.pinned)
            else if (key === "settings") root.sourceSettings(root.menuSrc.url)
            else if (key === "page") Qt.openUrlExternally(root.menuSrc.url)
            else if (key === "remove") root.removeSource(root.menuSrc)
        }
    }
    Popup {     // the Trusts that also list a Source (requirement 2.9.4, 2.9.5)
        id: trustsPop
        property var listing: []
        width: 330; padding: 6
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 14; color: Theme.raised; border.color: Theme.border
                                Rectangle { z: -1; anchors.fill: parent; anchors.topMargin: 4; radius: 15; color: "#000000"; opacity: Theme.dark ? 0.35 : 0.08 } }
        contentItem: Column {
            spacing: 2
            Text { text: "Also listed by " + trustsPop.listing.length + " trust" + (trustsPop.listing.length === 1 ? "" : "s"); color: Theme.faint; font.bold: true; font.pixelSize: 12; leftPadding: 10; topPadding: 8; bottomPadding: 6 }
            Repeater {
                model: trustsPop.listing
                Rectangle {
                    width: 318; height: 48; radius: 10; color: lArea.containsMouse || (tourMode && index === 0) ? Theme.hover : "transparent"
                    Avatar { x: 12; anchors.verticalCenter: parent.verticalCenter; person: modelData.avatars[0] || ({}); size: 26; ring: parent.color }
                    Row { x: 50; y: 7; spacing: 6
                        Text { text: modelData.name; color: Theme.text; font.bold: true; font.pixelSize: 13 }
                        Stars { value: modelData.score; r: 4; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter } }
                    Row { x: 50; y: 27; spacing: 5
                        Icon { name: "shield"; size: 12; color: modelData.trust === 0 ? Theme.err : Theme.ok; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: modelData.trust === null ? "–" : modelData.trust === 0 ? "Avoid" : modelData.trust; color: Theme.text; font.bold: true; font.pixelSize: 12 }
                        Stars { value: modelData.rating || 0; r: 4.2; anchors.verticalCenter: parent.verticalCenter } }
                    Row { anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                        Text { text: "Open"; color: Theme.accent; font.bold: true; font.pixelSize: 12 }
                        Icon { name: "chevRight"; size: 12; lineWidth: 1.8; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter } }
                    MouseArea { id: lArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { trustsPop.close(); trusts.select(modelData.id) } }
                }
            }
        }
    }

    TrustPanel {
        id: trusts
        x: parent.width - width; width: root.panelW; height: parent.height
        onAddTrust: root.addTrust()
        onConfirmAction: (k, x) => root.confirmAction(k, x)
    }
}
