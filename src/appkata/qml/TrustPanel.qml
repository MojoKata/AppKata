import QtQuick
import QtQuick.Controls.Basic
import "."

// The Trust panel (requirement 7.6): Trust rows, signer hover cards, and the Trust Detail panel.
Rectangle {
    id: root
    property int selected: -1
    property var hoverInfo: null           // {trust, index, person, x, y}
    property var d: ({})
    signal addTrust()
    signal confirmAction(string kind, var args)          // removals and new signers ask first (requirement 5.8)
    function select(id) { selected = id; d = id >= 0 ? backend.trustDetail(id) : ({}) }
    function showSigner(trustId, i) {      // the tour: hover one avatar of one Trust row
        const rows = backend.trustItems, r = rows.findIndex(t => t.id === trustId)
        if (r < 0) return
        const people = rows[r].avatars
        hoverInfo = { trust: trustId, index: i, person: people[i], pos: { x: 22 + 12 + i * 26 * 0.68, y: 70 + r * 74 + 33 + 15 } }
    }
    Connections { target: backend; function onChanged() {
        if (root.selected < 0) return
        if (!backend.trustItems.some(t => t.id === root.selected)) root.select(-1)       // removed
        else root.d = backend.trustDetail(root.selected) } }
    readonly property bool open: backend.prefs.trustPanelOpen !== false
    color: Theme.side
    Rectangle { width: 1; height: parent.height; color: Theme.border }

    // collapsed rail
    Column {
        visible: !root.open
        x: 12; y: 22; spacing: 12
        IconButton { icon: "panel"; onClicked: backend.setPref("trustPanelOpen", true) }
        Item {
            width: 34; height: 34
            Icon { anchors.centerIn: parent; name: "shieldCheck"; size: 20; color: Theme.accent }
            Rectangle { visible: backend.trustItems.some(t => t.warn); x: 24; y: 4; width: 9; height: 9; radius: 4.5; color: Theme.warn }
        }
    }

    Item {
        visible: root.open
        anchors.fill: parent
        Row {
            x: 22; y: 26; spacing: 8
            Icon { name: "shieldCheck"; size: 18; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }
            Text { text: "Trusts"; color: Theme.text; font.bold: true; font.pixelSize: 19; anchors.verticalCenter: parent.verticalCenter }
            Text { text: backend.trustItems.length; color: Theme.faint; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
        }
        IconButton { id: collapse; anchors.right: parent.right; anchors.rightMargin: 22; y: 22; icon: "panel"; onClicked: backend.setPref("trustPanelOpen", false) }
        FButton { anchors.right: collapse.left; anchors.rightMargin: 8; y: 22; implicitHeight: 34; text: "Add"; icon: "plus"; onClicked: root.addTrust() }

        Flickable {
            id: flick
            x: 22; y: 70; width: parent.width - 44
            height: (detail.visible ? detail.y : parent.height) - y - 8
            contentHeight: col.height; clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: col
                width: flick.width; spacing: 8
                Repeater {
                    model: backend.trustItems
                    Rectangle {    // requirement 7.6.3
                        width: col.width; height: 66; radius: 12
                        color: root.selected === modelData.id ? Theme.accentSoft : rArea.containsMouse ? Theme.hover : Theme.surface
                        border.width: root.selected === modelData.id ? 1.5 : 1
                        border.color: root.selected === modelData.id ? Theme.accent : Theme.border
                        MouseArea { id: rArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.select(modelData.id) }
                        AvatarStack {
                            id: stack
                            x: 12; anchors.verticalCenter: parent.verticalCenter
                            people: modelData.avatars; size: 26; ring: parent.color
                            onHovered: (i, person, px) => root.hoverInfo = { trust: modelData.id, index: i, person: person,
                                                                            pos: stack.mapToItem(root, px, stack.height) }
                            onUnhovered: hideTimer.restart()
                        }
                        Column {
                            x: 12 + 26 + 4 * 26 * 0.68 + 18; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                            width: parent.width - x - 44
                            Text { text: modelData.name; color: Theme.text; font.bold: true; font.pixelSize: 14; width: parent.width; elide: Text.ElideRight }
                            Row { spacing: 6; width: parent.width
                                Stars { value: modelData.score; r: 4.4; color: Theme.accent; anchors.verticalCenter: parent.verticalCenter }     // the Score
                                Text { text: modelData.own ? "Your file · always applied" : modelData.apps + " apps · synced " + Theme.ago(modelData.synced)
                                       color: Theme.muted; font.pixelSize: 12; width: parent.width - 56; elide: Text.ElideRight } }
                        }
                        Rectangle {
                            visible: modelData.warn
                            anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                            width: 22; height: 22; radius: 11; color: Theme.warnSoft
                            Icon { anchors.centerIn: parent; name: "warn"; size: 14; color: Theme.warn }
                        }
                    }
                }
                Text {
                    visible: backend.trustItems.length === 0
                    width: col.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13
                    text: "A Trust is a reviewer's signed AppKata.md file. Add one to see their ratings and the apps they list."
                }
            }
        }

        // Trust Detail panel (requirement 7.6.5)
        Rectangle {
            id: detail
            visible: root.selected >= 0 && !!root.d.id
            y: Math.max(300, parent.height * 0.5); width: parent.width; height: parent.height - y
            color: Theme.surface
            Rectangle { width: parent.width; height: 1; color: Theme.border }
            Text { x: 22; y: 22; text: "TRUST DETAILS"; color: Theme.faint; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.2 }
            IconButton { anchors.right: parent.right; anchors.rightMargin: 22; y: 14; round: true; icon: "x"; onClicked: root.select(-1) }
            Flickable {
                x: 22; y: 44; width: parent.width - 44; height: parent.height - y - 8
                contentHeight: dcol.height + 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: dcol
                    width: parent.width; spacing: 8
                    Text { text: root.d.name || ""; color: Theme.text; font.bold: true; font.pixelSize: 16; width: parent.width; elide: Text.ElideRight }
                    Text { text: (root.d.url || "").replace("https://", ""); color: Theme.muted; font.pixelSize: 11; font.family: Theme.mono; width: parent.width; elide: Text.ElideMiddle }
                    Row {       // the Score weights this Trust's reviews (requirement 10.6.2)
                        spacing: 10
                        Text { text: "Score"; color: Theme.text; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                        StarPicker { visible: !root.d.own; noZero: true; value: root.d.score || 3; scale: 0.8; transformOrigin: Item.Left
                                     onPicked: v => backend.setTrustScore(root.selected, v) }
                        Text { visible: !!root.d.own; text: "★★★★★ · your reviews always weigh 5"; color: Theme.accent; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    }
                    Text { visible: !root.d.own; width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 11; topPadding: -6
                           text: "How much this Trust's reviews count: a 5-star Trust weighs five times a 1-star one." }
                    Row {
                        spacing: 6
                        Icon { name: root.d.problem ? "warn" : "check"; size: 13; lineWidth: 1.8; color: root.d.problem ? Theme.warn : Theme.ok; anchors.verticalCenter: parent.verticalCenter }
                        Text {
                            text: root.d.own ? "Your own file: applied without signature checks"
                                  : "Verified at " + (root.d.verifiedShort || "—") + " · " + (root.d.apps || 0) + " apps"
                                    + ((root.d.warnings || []).length ? " · " + root.d.warnings.length + " parse warning" + (root.d.warnings.length > 1 ? "s" : "") : "")
                            color: Theme.muted; font.pixelSize: 12
                        }
                    }
                    Text { visible: !!root.d.problem_detail && root.d.problem !== "unknown-signer"; width: parent.width; wrapMode: Text.WordWrap
                           text: root.d.problem_detail || ""; color: Theme.warn; font.pixelSize: 12 }
                    Repeater {     // pending new signers (requirement 7.6.6)
                        model: (root.d.authorities || []).filter(a => a.pending)
                        Rectangle {
                            width: dcol.width; height: 100; radius: 11; color: Theme.warnSoft; border.color: Theme.warn
                            Rectangle { x: 13; y: 11; width: 26; height: 26; radius: 13; color: Theme.track
                                        Text { anchors.centerIn: parent; text: "?"; color: Theme.muted; font.bold: true; font.pixelSize: 13 } }
                            Text { x: 48; y: 9; text: "New signer · not trusted"; color: Theme.warn; font.bold: true; font.pixelSize: 13 }
                            Text { x: 48; y: 27; width: parent.width - 60; elide: Text.ElideRight; text: (modelData.email || modelData.name) + " · " + modelData.kindLabel + " " + modelData.shortFp
                                   color: Theme.text; font.pixelSize: 11; font.family: Theme.mono }
                            Text { x: 48; y: 46; text: "Signed " + modelData.pending_commits + " change" + (modelData.pending_commits === 1 ? "" : "s") + " since " + (root.d.verifiedShort || "") + " · not applied"
                                   color: Theme.muted; font.pixelSize: 12 }
                            Row {
                                anchors.right: parent.right; anchors.rightMargin: 10; y: 64; spacing: 8
                                FButton { implicitHeight: 28; text: "Ignore"
                                          onClicked: root.confirmAction("ignoreSigner", { trust: root.selected, fp: modelData.fingerprint, name: modelData.email || modelData.name, trustName: root.d.name }) }
                                FButton { implicitHeight: 28; text: "Trust signer"; primary: true
                                          onClicked: root.confirmAction("trustSigner", { trust: root.selected, fp: modelData.fingerprint, name: modelData.email || modelData.name, trustName: root.d.name }) }
                            }
                        }
                    }
                    Text { visible: !root.d.own; text: "AUTHORITIES · " + (root.d.authorities || []).filter(a => !a.pending).length; color: Theme.faint; font.bold: true; font.pixelSize: 11; font.letterSpacing: 1.1; topPadding: 4 }
                    Repeater {    // requirement 7.6.5: remove or disable each
                        model: (root.d.authorities || []).filter(a => !a.pending)
                        Item {
                            width: dcol.width; height: 48
                            Avatar { x: 2; anchors.verticalCenter: parent.verticalCenter; person: modelData; size: 30; ring: Theme.surface; dim: !modelData.enabled }
                            Text { x: 44; y: 6; text: modelData.name || modelData.email; color: modelData.enabled ? Theme.text : Theme.faint; font.bold: true; font.pixelSize: 13
                                   width: parent.width - 44 - 90; elide: Text.ElideRight }
                            Text { x: 44; y: 25; text: modelData.kindLabel + " · " + modelData.shortFp; color: Theme.muted; font.pixelSize: 11; font.family: Theme.mono
                                   width: parent.width - 44 - 90; elide: Text.ElideRight }
                            Switch {
                                id: sw
                                anchors.right: del.left; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                                checked: modelData.enabled
                                onToggled: backend.setAuthorityEnabled(root.selected, modelData.fingerprint, checked)
                                indicator: Rectangle {
                                    implicitWidth: 34; implicitHeight: 20; radius: 10
                                    color: sw.checked ? Theme.accent : Theme.track; border.color: sw.checked ? Theme.accent : Theme.borderStrong
                                    Rectangle { x: sw.checked ? 16 : 2; y: 2; width: 16; height: 16; radius: 8; color: "#ffffff"; Behavior on x { NumberAnimation { duration: 120 } } }
                                }
                            }
                            TipButton { id: del; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; icon: "trash"; danger: true
                                        width: 30; height: 30; tip: "Remove"
                                        onClicked: root.confirmAction("removeAuthority", { trust: root.selected, fp: modelData.fingerprint, name: modelData.name || modelData.email, trustName: root.d.name }) }
                            Rectangle { visible: index < (root.d.authorities || []).filter(a => !a.pending).length - 1; y: parent.height - 1; width: parent.width; height: 1; color: Theme.border }
                        }
                    }
                    FButton { visible: !root.d.own; text: "Remove trust"; icon: "trash"; danger: true; onClicked: root.confirmAction("removeTrust", { id: root.selected }) }
                }
            }
        }
    }

    // signer hover card, closes by itself (requirement 7.6.4)
    Timer { id: hideTimer; interval: tourMode ? 600000 : 3000; onTriggered: root.hoverInfo = null }
    Rectangle {
        visible: !!root.hoverInfo
        x: root.hoverInfo ? Math.min(root.width - width - 10, root.hoverInfo.pos.x) : 0
        y: root.hoverInfo ? root.hoverInfo.pos.y + 6 : 0
        z: 20
        width: 340; height: 168; radius: 14; color: Theme.raised; border.color: Theme.border
        readonly property var p: root.hoverInfo ? root.hoverInfo.person : ({})
        Rectangle { z: -1; anchors.fill: parent; anchors.topMargin: 6; radius: 15; color: "#000000"; opacity: Theme.dark ? 0.35 : 0.1 }
        Avatar { x: 14; y: 16; person: parent.p; size: 40; ring: Theme.raised }
        Text { x: 66; y: 18; text: parent.p.name || parent.p.email || ""; color: Theme.text; font.bold: true; font.pixelSize: 15 }
        Text { x: 66; y: 38; text: parent.p.email || ""; color: Theme.muted; font.pixelSize: 12 }
        Grid {
            x: 16; y: 74; columns: 2; columnSpacing: 14; rowSpacing: 6
            Text { text: "Key"; color: Theme.faint; font.pixelSize: 12 }
            Text { text: (parent.parent.p.kindLabel || "") + " · " + (parent.parent.p.shortFp || ""); color: Theme.text; font.pixelSize: 12; font.family: Theme.mono }
            Text { text: "First seen"; color: Theme.faint; font.pixelSize: 12 }
            Text { text: Theme.shortDate(parent.parent.p.first_at) + " · commit " + (parent.parent.p.first_commit || "").slice(0, 7); color: Theme.text; font.pixelSize: 12 }
            Text { text: "Last signed"; color: Theme.faint; font.pixelSize: 12 }
            Text { text: Theme.shortDate(parent.parent.p.last_at) + " · commit " + (parent.parent.p.last_commit || "").slice(0, 7); color: Theme.text; font.pixelSize: 12 }
            Text { text: "Status"; color: Theme.faint; font.pixelSize: 12 }
            Text { text: parent.parent.p.enabled ? "Enabled authority" : "Disabled"; color: parent.parent.p.enabled ? Theme.ok : Theme.faint; font.pixelSize: 12 }
        }
        Rectangle { x: 14; y: parent.height - 8; width: parent.width - 28; height: 2.5; radius: 1.2; color: Theme.track
                    Rectangle { width: parent.width * 0.6; height: parent.height; radius: 1.2; color: Theme.accent } }
        HoverHandler { onHoveredChanged: if (hovered) hideTimer.stop(); else hideTimer.restart() }
    }
}
