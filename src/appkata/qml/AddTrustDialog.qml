import QtQuick
import QtQuick.Controls.Basic
import "."

// Adding a Trust (requirement 7.6.2): find AppKata.md, check the signature, confirm the signer.
Dialog {
    id: root
    property var p: null
    property bool checking: false
    property int score: 3
    title: "Add trust"
    dialogWidth: 600
    function openWith(text) { p = null; checking = false; score = 3; urlBox.text = text || ""; open(); if (text) check() }
    function check() { if (!urlBox.text.trim()) return; checking = true; p = null; backend.previewTrust(urlBox.text.trim()) }
    Connections { target: backend; function onTrustPreview(res) { if (res.url === urlBox.text.trim()) { root.p = res; root.checking = false } } }

    Column {
        width: parent.width; spacing: 8
        Text { text: "Repository or AppKata.md URL"; color: Theme.muted; font.bold: true; font.pixelSize: 13 }
        Field { id: urlBox; width: parent.width; height: 42; mono: true; placeholder: "https://github.com/owner/reviews"
                error: !!root.p && !!root.p.error; onAccepted: root.check() }
        Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
               text: "AppKata looks for AppKata.md in the root or docs/ folder. The commit that last changed it must be signed (GPG or SSH)." }
    }
    FButton { visible: !root.p && !root.checking; text: "Check"; onClicked: root.check() }
    Row { visible: root.checking; spacing: 10
        BusyIndicator { width: 22; height: 22; running: root.checking }
        Text { text: "Fetching and checking signatures…"; color: Theme.muted; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter } }
    Text { visible: !!root.p && !!root.p.error; width: parent.width; wrapMode: Text.WordWrap; color: Theme.err; font.pixelSize: 13; text: root.p ? root.p.error : "" }
    Column {
        visible: !!root.p && !root.p.error
        width: parent.width; spacing: 10
        Text { text: root.p ? root.p.name : ""; color: Theme.text; font.bold: true; font.pixelSize: 16 }
        Text { text: root.p ? root.p.path + " · " + root.p.apps + " apps · signed commit " + root.p.commit : ""; color: Theme.muted; font.pixelSize: 13 }
        Row { spacing: 12
            Text { text: "Score"; color: Theme.text; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
            StarPicker { noZero: true; value: root.score; onPicked: v => root.score = v }
            Text { text: "How much its reviews count; change it any time."; color: Theme.faint; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter } }
        Text { text: "Confirm the signing key. It becomes this Trust's first Authority; later changes must be signed by an Authority."
               width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13 }
        Repeater {
            model: root.p ? root.p.signers : []
            Rectangle {
                width: parent.width; height: 64; radius: 12; color: Theme.input; border.color: Theme.border
                Avatar { x: 12; anchors.verticalCenter: parent.verticalCenter; person: modelData; size: 34; ring: Theme.input }
                Column { x: 60; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    Text { text: (modelData.name || "") + (modelData.email ? "  <" + modelData.email + ">" : ""); color: Theme.text; font.bold: true; font.pixelSize: 13 }
                    Text { text: (modelData.kind === "ssh" ? "SSH" : "GPG") + " · " + modelData.fingerprint; color: Theme.muted; font.pixelSize: 11; font.family: Theme.mono } }
            }
        }
        Repeater { model: root.p ? root.p.warnings.slice(0, 3) : []
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12; text: "⚠ " + modelData } }
    }
    footer: [
        FButton { text: "Cancel"; onClicked: root.close() },
        FButton { text: "Trust this signer"; icon: "shieldCheck"; primary: true; enabledButton: !!root.p && !root.p.error
                  onClicked: { backend.addTrustScored(urlBox.text.trim(), root.score); root.close() } }
    ]
}
