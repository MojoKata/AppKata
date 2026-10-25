import QtQuick
import QtQuick.Controls.Basic
import "."

// The Catalog perspective (requirement 12).
Item {
    id: root
    property string selected: ""
    property real rightInset: 0
    signal openApp(string url)
    signal addSource()
    signal addTrust()
    property alias tagsPopup: tagsPop
    readonly property var items: backend.catalogItems
    readonly property real avail: width - 64 - rightInset
    readonly property int cols: Math.max(1, Math.floor((avail + 16) / (280 + 16)))
    readonly property real tileW: Math.min(600, (avail - 16 * (cols - 1)) / cols)
    readonly property real tileH: Math.max(206, 210 * Math.min(1.12, tileW / 300))

    // title row (requirement 12.2)
    Text { id: title; x: 32; y: 30; text: "Catalog"; color: Theme.text; font.pixelSize: 28; font.bold: true }
    Text {
        anchors.left: title.right; anchors.leftMargin: 14; anchors.baseline: title.baseline
        text: backend.search ? root.items.length + " match" + (root.items.length === 1 ? "" : "es") + " for “" + backend.search + "”"
              : backend.catalogCount + " apps · " + backend.sourceItems.length + " sources, " + backend.trustItems.filter(t => !t.own).length + " trusts"
        color: Theme.muted; font.pixelSize: 14
    }
    Field {
        id: searchBox
        objectName: "catalogSearch"
        anchors.right: parent.right; anchors.rightMargin: 32 + root.rightInset; y: 20
        width: root.rightInset > 0 ? 230 : 300
        icon: "search"; placeholder: "Search apps, tags, sources"
        clearable: true
        text: backend.search
        onEdited: t => backend.setSearch(t)
    }
    Row {
        x: 32; y: 76; spacing: 8
        readonly property var shown: backend.topTags.slice(0, root.rightInset > 0 ? 4 : 6)
        Repeater {
            model: ["All"].concat(parent.shown)
            Rectangle {
                readonly property bool on: modelData === "All" ? backend.tag === "" : backend.tag === modelData
                height: 28; width: lbl.implicitWidth + 22; radius: 14
                color: on ? Theme.accentSoft : Theme.surface
                border.color: on ? Theme.accent : Theme.border
                Text { id: lbl; anchors.centerIn: parent; text: modelData; color: parent.on ? Theme.accent : Theme.muted; font.bold: true; font.pixelSize: 12 }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: backend.setTag(modelData === "All" ? backend.tag : modelData) }
            }
        }
        Rectangle {     // the rest of the tags (requirement 12.2)
            id: moreTags
            objectName: "moreTags"
            visible: backend.topTags.length > parent.shown.length
            readonly property bool on: backend.tag !== "" && parent.shown.indexOf(backend.tag) < 0
            height: 28; width: mlbl.implicitWidth + 22 + 16; radius: 14
            color: on || allTags.visible ? Theme.accentSoft : Theme.surface
            border.color: on || allTags.visible ? Theme.accent : Theme.border
            Row { anchors.centerIn: parent; spacing: 4
                Text { id: mlbl; text: parent.parent.on ? backend.tag : "More…"; color: parent.parent.on || allTags.visible ? Theme.accent : Theme.muted; font.bold: true; font.pixelSize: 12 }
                Icon { name: "chevDown"; size: 11; lineWidth: 1.8; color: mlbl.color; anchors.verticalCenter: parent.verticalCenter } }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: allTags.open() }
            Popup {
                id: allTags
                y: parent.height + 6; width: 330; padding: 14
                background: Rectangle { radius: 12; color: Theme.raised; border.color: Theme.border
                    Rectangle { z: -1; anchors.fill: parent; anchors.topMargin: 4; radius: 13; color: "#000000"; opacity: Theme.dark ? 0.35 : 0.08 } }
                contentItem: Column {
                    spacing: 10
                    Text { text: "All tags · " + backend.topTags.length; color: Theme.faint; font.bold: true; font.pixelSize: 12 }
                    Flow { width: 302; spacing: 6
                        Repeater { model: backend.topTags
                            Chip { text: modelData; size: 11.5; u: 1.08; on: backend.tag === modelData
                                   onClicked: { backend.setTag(modelData); allTags.close() } } } }
                }
            }
        }
    }
    property alias allTagsPopup: allTags
    Select {
        id: sortSel
        anchors.right: searchBox.right; y: 76
        icon: "sort"
        label: "Sort: " + ({ trust: "Trust, name", rating: "Rating", recent: "Recently updated", name: "Name" })[backend.prefs.sort || "trust"]
        options: [["trust", "Trust, then name"], ["rating", "Rating"], ["recent", "Recently updated"], ["name", "Name"]]
        onPicked: key => backend.setPref("sort", key)
    }

    Flickable {
        id: flick
        objectName: "catalogFlick"
        x: 0; y: 120; width: parent.width - root.rightInset; height: parent.height - y
        contentHeight: flow.height + 40 + (note.visible ? 40 : 0)
        clip: true
        layer.enabled: contentY > 0
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Flow {
            id: flow
            x: 32; y: 4; width: root.avail
            spacing: 16
            Repeater {
                id: tiles
                model: root.items
                AppTile {
                    width: root.tileW; height: root.tileH
                    app: modelData
                    selected: modelData.url === root.selected
                    tagsHover: tagsPop.visible && tagsPop.app.url === modelData.url
                    onClicked: root.openApp(modelData.url)
                    onTagsRequested: (app, anchor) => tagsPop.showFor(app, anchor)
                }
            }
        }
        Row {
            id: note
            visible: backend.vetoedShown > 0
            x: 32; anchors.top: flow.bottom; anchors.topMargin: 16; spacing: 8
            Icon { name: "info"; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
            Text {   // requirement 12.6.2
                text: backend.vetoedShown === 1 ? "1 app hidden by a trusted reviewer is shown because it matches your search."
                      : backend.vetoedShown + " apps hidden by trusted reviewers are shown because they match your search."
                color: Theme.muted; font.pixelSize: 13
            }
        }
    }

    // empty state (requirement 12.7)
    Column {
        visible: root.items.length === 0 && !backend.search && backend.sourceItems.length === 0
        anchors.centerIn: parent; spacing: 14
        Image { source: "assets/appkata.svg"; width: 64; height: 64; sourceSize: Qt.size(128, 128); anchors.horizontalCenter: parent.horizontalCenter }
        Text { text: "Add a source or a trust to fill your catalog"; color: Theme.text; font.pixelSize: 17; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
        Row {
            spacing: 10; anchors.horizontalCenter: parent.horizontalCenter
            FButton { text: "Add source"; icon: "plus"; primary: true; onClicked: root.addSource() }
            FButton { text: "Add trust"; icon: "shieldCheck"; onClicked: root.addTrust() }
        }
    }
    Text {
        visible: root.items.length === 0 && !!backend.search
        anchors.centerIn: parent; text: "No apps match “" + backend.search + "”"; color: Theme.muted; font.pixelSize: 15
    }

    function showTagsFor(url) {      // the tour
        const i = root.items.findIndex(a => a.url === url)
        if (i >= 0) tagsPop.showFor(root.items[i], tiles.itemAt(i).moreButton)
    }
    // all of an app's tags (requirement 12.4.1)
    Popup {
        id: tagsPop
        property var app: ({})
        function showFor(a, anchor) {
            app = a
            const p = anchor.mapToItem(root, anchor.width, 0)
            x = Math.max(8, p.x - width + 8); y = p.y - height - 6
            open()
        }
        width: 250; padding: 14
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: 12; color: Theme.raised; border.color: Theme.border
            Rectangle { z: -1; anchors.fill: parent; anchors.topMargin: 4; radius: 13; color: "#000000"; opacity: Theme.dark ? 0.35 : 0.08 }
            HoverHandler { onHoveredChanged: if (!hovered && !tourMode) tagsPop.close() }
        }
        contentItem: Column {
            spacing: 10
            Text { text: (tagsPop.app.tags || []).length + " tags"; color: Theme.faint; font.bold: true; font.pixelSize: 12 }
            Flow {
                width: 222; spacing: 6
                Repeater { model: tagsPop.app.tags || []; Chip { text: modelData; size: 11.5; u: 1.08; on: backend.tag === modelData
                                                                  onClicked: { backend.selectTag(modelData); tagsPop.close() } } }
            }
        }
    }
}
