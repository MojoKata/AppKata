import QtQuick
import QtQuick.Controls.Basic
import "."

// Explore (requirement 7.7): search GitHub, GitLab, Codeberg or ngit for projects, and on Linux
// Flathub and the distribution's AppStream catalog (16.2.3), then open one's page or add it as a
// Source. A Flathub or distribution match needs its project's git URL to become a Source (16.2.4).
Dialog {
    id: root
    property string service: "github"
    property var res: null
    property bool searching: false
    property alias queryField: q
    signal addRequested(string url, var link)
    readonly property var services: backend.exploreServices
    readonly property bool channelSvc: service === "flathub" || service === "distro"
    property int demoTip: -1          // the tour: show one button's tooltip
    title: "Explore"
    dialogWidth: 760
    function openWith(text, svc) { if (svc) service = svc; res = null; demoTip = -1; q.text = text || ""; open(); if (text) run() }
    function run() { if (!q.text.trim()) return; searching = true; res = null; backend.explore(service, q.text.trim()) }
    onServiceChanged: if (visible && q.text.trim()) run()
    Connections { target: backend; function onExploreResults(r) { if (r.service === root.service && r.q === q.text.trim()) { root.res = r; root.searching = false } } }

    Rectangle {     // service picker, like the perspective switcher (requirement 7.7.2)
        id: seg
        width: Math.min(parent.width, 105 * root.services.length); height: 34; radius: 10; color: Theme.track
        Row {
            x: 3; y: 3
            Repeater {
                model: root.services
                Rectangle {
                    readonly property bool on: root.service === modelData.key
                    width: (seg.width - 6) / root.services.length; height: 28; radius: 8
                    color: on ? Theme.segOn : "transparent"
                    Text { anchors.centerIn: parent; text: modelData.label; font.bold: true; font.pixelSize: 13
                           color: !modelData.enabled ? Theme.faint : parent.on ? Theme.text : Theme.muted }
                    MouseArea { id: segArea; anchors.fill: parent; hoverEnabled: true; cursorShape: modelData.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: if (modelData.enabled) root.service = modelData.key }
                    ToolTip.visible: !!modelData.tip && segArea.containsMouse; ToolTip.text: modelData.tip || ""
                }
            }
        }
    }
    Row {
        spacing: 10
        Field { id: q; width: 600; height: 40; icon: "search"; clearable: true
                placeholder: root.service === "ngit" ? "Search ngit repositories on Nostr relays"
                             : root.channelSvc ? "Search apps, e.g. notes" : "Search projects, e.g. password manager"
                onAccepted: root.run() }
        FButton { text: "Search"; primary: true; implicitHeight: 40; onClicked: root.run() }
    }
    Text { visible: root.service === "ngit" || root.channelSvc || (!!root.res && !!root.res.note); width: parent.width; wrapMode: Text.WordWrap
           color: !!root.res && !!root.res.note ? Theme.warn : Theme.faint; font.pixelSize: 12
           text: !!root.res && !!root.res.note ? root.res.note
                 : root.service === "ngit" ? "ngit repositories open on gitworkshop.dev. Adding them as Sources comes with ngit support in a later version."
                 : "An app is its project's git repository: AppKata adds the project as a Source, and keeps " + (root.service === "flathub" ? "the Flatpak" : "the package") + " as a way to install it." }
    Item {
        width: parent.width; height: 420
        Row { visible: root.searching; anchors.centerIn: parent; spacing: 10
            BusyIndicator { width: 24; height: 24; running: root.searching }
            Text { text: "Searching…"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter } }
        Text { visible: !!root.res && !!root.res.error; anchors.centerIn: parent; width: parent.width - 40; wrapMode: Text.WordWrap
               horizontalAlignment: Text.AlignHCenter; color: Theme.err; font.pixelSize: 13; text: root.res ? root.res.error : "" }
        Text { visible: !!root.res && !root.res.error && root.res.matches.length === 0; anchors.centerIn: parent
               text: "Nothing found"; color: Theme.muted; font.pixelSize: 14 }
        Text { visible: !root.res && !root.searching; anchors.centerIn: parent; text: "Search for an app to add as a source."
               color: Theme.faint; font.pixelSize: 13 }
        ListView {
            id: list
            anchors.fill: parent; clip: true; spacing: 6
            layer.enabled: contentY > 0 || contentHeight > height     // icons ignore clipping in the software renderer (the tour's): a layer clips them
            model: root.res ? root.res.matches : []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Rectangle {      // a minimal summary with its tools (requirement 7.7.3)
                width: list.width - 8; height: modelData.channel ? 80 : 70; radius: 12; color: Theme.input; border.color: Theme.border
                Column {
                    x: 14; y: 10; width: parent.width - 14 - 100; spacing: 4
                    Row {
                        spacing: 6
                        Text { visible: !modelData.channel; text: modelData.owner + " / "; color: Theme.muted; font.pixelSize: 14 }
                        Text { text: modelData.name; color: Theme.text; font.bold: true; font.pixelSize: 14 }
                        Text { visible: !!modelData.channel; text: modelData.link; color: Theme.faint; font.pixelSize: 12; font.family: Theme.mono; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: modelData.verified === true; text: "Verified"; icon: "shieldCheck"; color: Theme.okSoft; fg: Theme.ok; u: 0.75; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: modelData.archived; text: "Archived"; color: Theme.track; fg: Theme.muted; u: 0.75; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: modelData.listed && !modelData.isSource; text: "In your trusts"; color: Theme.accentSoft; fg: Theme.accent; u: 0.75; anchors.verticalCenter: parent.verticalCenter }
                    }
                    Text { width: parent.width; elide: Text.ElideRight; text: modelData.description || "No description"; color: Theme.muted; font.pixelSize: 12 }
                    Text {      // the project found for a Flathub or distribution match (requirement 16.2.4)
                        visible: !!modelData.channel; textFormat: Text.StyledText; font.pixelSize: 11
                        color: modelData.url ? Theme.faint : Theme.warn
                        text: modelData.url ? "<font color='" + Theme.muted + "'>" + modelData.url.replace("https://", "") + "</font> · from its " + (modelData.found || "AppStream") + " data"
                              : "No project link found. <a href='enter'>Enter git URL…</a>"
                        linkColor: Theme.accent
                        onLinkActivated: { root.close(); root.addRequested("", modelData.channel === "flatpak" ? { flatpak: modelData.link } : { "package": modelData.link }) }
                    }
                    Row {
                        visible: !modelData.channel
                        spacing: 12
                        Row { visible: modelData.stars > 0; spacing: 4
                            Icon { name: "star"; size: 12; color: Theme.star; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: modelData.stars >= 1000 ? (modelData.stars / 1000).toFixed(1) + "k" : modelData.stars; color: Theme.faint; font.pixelSize: 11 } }
                        Text { visible: !!modelData.language; text: modelData.language; color: Theme.faint; font.pixelSize: 11 }
                        Text { visible: !!modelData.updated; text: "updated " + Theme.ago(modelData.updated); color: Theme.faint; font.pixelSize: 11 }
                    }
                }
                Row {
                    anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    // icon-only, labelled by tooltips (requirement 7.7.3)
                    TipButton { icon: "open"; tip: modelData.service === "ngit" ? "Open on gitworkshop.dev" : "Project page"
                                showTip: root.demoTip === index * 2; onClicked: Qt.openUrlExternally(modelData.page) }
                    TipButton {
                        icon: modelData.isSource ? "check" : "plus"
                        tip: modelData.isSource ? "Already a source" : modelData.addable ? "Add source"
                             : modelData.channel ? "No project link found; enter its git URL to add it" : "ngit sources come in a later version"
                        accent: !modelData.isSource && modelData.addable
                        enabledButton: modelData.addable && !modelData.isSource
                        showTip: root.demoTip === index * 2 + 1
                        tipOffset: 40           // past the Project page button
                        onClicked: { root.close(); root.addRequested(modelData.url, !modelData.channel ? null
                                     : modelData.channel === "flatpak" ? { flatpak: modelData.link } : { "package": modelData.link }) }
                    }
                }
            }
        }
    }
    footer: [ FButton { text: "Close"; onClicked: root.close() } ]
}
