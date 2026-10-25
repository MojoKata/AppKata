import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import "."

// Writing a review to the user's AppKata.md (requirement 8.2–8.5).
Dialog {
    id: root
    property string url: ""
    property var r: ({})
    property var tags: []
    property var trustValue: null
    property var ratingValue: null
    property bool autoCommit: false
    property bool autoPush: false
    property var result: null
    property bool saving: false
    property string version: ""             // which review: a release, or "" for Any version (requirement 8.4.1.1)
    property bool includeDetails: false
    property bool includeSandbox: true      // write my own sandbox into the review (10.3.1; review 2, F9)
    readonly property var cur: (r.versionReviews || {})[version] || ({})
    property alias editor: editorArea
    readonly property var trustWords: ["Avoid", "Wary", "Cautious", "Trusted with reservations", "Trusted", "Fully trusted"]
    title: r.app || ""
    subtitle: "REVIEW"
    app: backend.detail(url)
    dialogWidth: 780

    function openFor(u) {
        url = u
        r = backend.reviewData(u)
        result = null; saving = false
        if (!r.path) { pathDialog.open(); return }
        load()
        open()
    }
    function load() {
        version = r.defaultVersion || ""
        includeDetails = !!r.includeDetails
        includeSandbox = true
        loadVersion()
        autoCommit = r.inRepo && r.autoCommit; autoPush = r.inRepo && r.autoPush
        tabs.preview = false
    }
    function loadVersion() {        // the chosen review, or a new one starting from the values in effect (10.3.3)
        const c = (r.versionReviews || {})[version] || {}
        tags = (c.tags || []).slice(); trustValue = c.trust === undefined ? null : c.trust
        ratingValue = c.rating === undefined ? null : c.rating
        editorArea.text = c.text || ""
    }
    Connections {
        target: backend
        function onReviewSaved(res) {
            root.saving = false; root.result = res
            if (res.saved && !res.error && (!root.autoPush || res.pushed)) { root.close(); backend.toast("info", "Review saved" + (res.pushed ? " and pushed." : res.committed ? " and committed (" + res.committed + ")." : ".")) }
        }
    }
    FileDialog {     // requirement 8.2: choose where AppKata.md lives (home folder by default)
        id: pathDialog
        title: "Where should your AppKata.md go?"
        fileMode: FileDialog.SaveFile
        currentFolder: Theme.fileUrl(root.r.defaultDir || "")
        selectedFile: Theme.fileUrl((root.r.defaultDir || "") + (Qt.platform.os === "windows" ? "\\" : "/") + "AppKata.md")
        nameFilters: ["Markdown (*.md)"]
        onAccepted: {
            let p = Theme.localPath(selectedFile)
            if (!p.toLowerCase().endsWith(".md")) p += "/AppKata.md"
            backend.setPref("reviewPath", p)
            root.r = backend.reviewData(root.url); root.load(); root.open()
        }
    }

    // where it's saved
    Row {
        spacing: 6
        Icon { name: "folder"; size: 14; color: Theme.faint; anchors.verticalCenter: parent.verticalCenter }
        Text { text: (root.r.path || "").replace(root.r.defaultDir, "~"); color: Theme.faint; font.pixelSize: 12; font.family: Theme.mono }
        Text { visible: !!root.cur.exists; text: "· editing your review" + (root.version ? " of " + root.version : ""); color: Theme.faint; font.pixelSize: 12 }
    }
    // which review this is (requirement 8.4.1.1)
    Column {
        width: parent.width; spacing: 8
        Text { text: "Version"; color: Theme.muted; font.bold: true; font.pixelSize: 13 }
        Row {
            width: parent.width; spacing: 16
            Rectangle {
                id: verBox
                width: 220; height: 38; radius: 11; color: Theme.input; border.color: verMenu.visible ? Theme.accent : Theme.border
                border.width: verMenu.visible ? 2 : 1
                readonly property var choice: (root.r.versionChoices || []).find(c => c.key === root.version) || ({ text: "Any version", note: "" })
                Text { x: 14; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 44; elide: Text.ElideRight
                       text: verBox.choice.text + (verBox.choice.note ? " · " + verBox.choice.note : ""); color: Theme.text; font.pixelSize: 13 }
                Icon { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; color: Theme.muted }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: verMenu.open() }
                PopMenu {
                    id: verMenu
                    menuWidth: 260; y: 42
                    items: (root.r.versionChoices || []).slice(0, 12).map(c => ({ key: c.key === "" ? "*any*" : c.key, text: c.text, note: c.note }))
                    onTriggered: key => { root.version = key === "*any*" ? "" : key; root.loadVersion() }
                }
            }
            Text {
                width: parent.width - verBox.width - 16; anchors.verticalCenter: parent.verticalCenter
                wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                visible: text !== ""
                text: root.cur.exists ? "" : root.version === "" ? "Your review of the app as a whole, for versions you haven't reviewed."
                      : "New review of " + root.version + "." + (root.cur.from ? " Your review of " + root.cur.from + (root.cur.fromDate ? " (" + root.cur.fromDate + ")" : "")
                        + " stays in AppKata.md; Trust, Rating and Tags start from it." : "")
            }
        }
    }
    // tags (requirement 8.4.2)
    Column {
        width: parent.width; spacing: 8
        Text { text: "Tags"; color: Theme.muted; font.bold: true; font.pixelSize: 13 }
        Rectangle {
            width: parent.width; height: 42; radius: 11; color: Theme.input
            border.width: tagInput.activeFocus ? 2 : 1; border.color: tagInput.activeFocus ? Theme.accent : Theme.border
            Row {
                x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                Repeater {
                    model: root.tags
                    Chip { anchors.verticalCenter: parent.verticalCenter
                           text: modelData; on: Theme.warnTags.indexOf(modelData) < 0; size: 12; u: 1.08; closable: true
                           onClosed: root.tags = root.tags.filter(t => t !== modelData) }
                }
                TextField {
                    id: tagInput
                    anchors.verticalCenter: parent.verticalCenter; topPadding: 0; bottomPadding: 0; verticalAlignment: TextInput.AlignVCenter
                    width: 200; background: null; color: Theme.text; font.pixelSize: 13
                    placeholderText: "Add a tag…"; placeholderTextColor: Theme.faint
                    validator: RegularExpressionValidator { regularExpression: /[A-Za-z][A-Za-z0-9]*/ }
                    onTextEdited: tagMenu.open()
                    onAccepted: { const t = text.toLowerCase(); if (t && root.tags.indexOf(t) < 0) root.tags = root.tags.concat([t]); text = "" }
                }
            }
            Icon { anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; name: "chevDown"; color: Theme.muted
                   MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: tagMenu.open() } }
            PopMenu {
                id: tagMenu
                menuWidth: 300; y: 46
                items: (root.r.knownTags || []).filter(t => root.tags.indexOf(t) < 0 && t.indexOf(tagInput.text.toLowerCase()) === 0).slice(0, 7)
                       .map(t => ({ key: t, text: t, note: (root.r.tagMeanings || {})[t] || "" }))
                onTriggered: key => { root.tags = root.tags.concat([key]); tagInput.text = "" }
            }
        }
    }
    // trust and rating on one line (requirement 8.4.3, 8.4.4)
    Row {
        width: parent.width; spacing: 28
        Column {
            spacing: 8; width: 380
            Text { text: "Trust"; color: Theme.muted; font.bold: true; font.pixelSize: 13 }
            Row {
                spacing: 14
                StarPicker { id: trustPick; trust: true; value: root.trustValue; onPicked: v => root.trustValue = v }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.trustValue === null || root.trustValue === undefined ? "No opinion" : root.trustValue + " · " + root.trustWords[root.trustValue]
                    color: root.trustValue === 0 ? Theme.err : root.trustValue ? Theme.ok : Theme.faint; font.bold: true; font.pixelSize: 14
                }
            }
            Text { text: root.trustValue === 0 ? "Avoid hides this app from everyone who trusts your file." : "How far you trust this app and its authors"
                   color: root.trustValue === 0 ? Theme.err : Theme.faint; font.pixelSize: 12 }
        }
        Rectangle { width: 1; height: 80; color: Theme.border }
        Column {
            spacing: 8
            Text { text: "Rating"; color: Theme.muted; font.bold: true; font.pixelSize: 13 }
            Row { spacing: 14
                StarPicker { id: ratePick; value: root.ratingValue; onPicked: v => root.ratingValue = v }
                Text { anchors.verticalCenter: parent.verticalCenter; text: root.ratingValue === null || root.ratingValue === undefined ? "No opinion" : root.ratingValue + " of 5"
                       color: root.ratingValue === null || root.ratingValue === undefined ? Theme.faint : Theme.text; font.bold: true; font.pixelSize: 14 } }
            Text { text: "How much you like it"; color: Theme.faint; font.pixelSize: 12 }
        }
    }
    // the app's section (requirement 8.4.5)
    Item {
        width: parent.width; height: 26
        Text { text: "Review"; color: Theme.muted; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
        Rectangle {
            id: tabs
            property bool preview: false
            anchors.right: parent.right; width: 150; height: 28; radius: 8; color: Theme.track
            Row { x: 3; y: 3
                Repeater { model: ["Edit", "Preview"]
                    Rectangle { width: 72; height: 22; radius: 6; color: (index === 1) === tabs.preview ? Theme.segOn : "transparent"
                        Text { anchors.centerIn: parent; text: modelData; color: (index === 1) === tabs.preview ? Theme.text : Theme.muted; font.bold: true; font.pixelSize: 12 }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: tabs.preview = index === 1 } } } }
        }
    }
    Rectangle {
        width: parent.width; height: detailsBox.visible ? (cbDetails.checked ? 96 : 140) : 170; radius: 11; color: Theme.input
        border.width: editorArea.activeFocus ? 2 : 1; border.color: editorArea.activeFocus ? Theme.accent : Theme.border
        Rectangle {
            x: 1; y: 1; width: parent.width - 2; height: 32; radius: 10; color: Theme.dark ? "#1f222b" : "#f0f2f7"
            Row { x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Repeater {
                    model: [["bold", "**", "**"], ["italic", "*", "*"], ["list", "- ", ""], ["link", "[", "](https://)"]]
                    IconButton { implicitWidth: 26; outlined: false; icon: modelData[0]; iconSize: 14
                        onClicked: { const s = editorArea.selectionStart, e = editorArea.selectionEnd, t = editorArea.text
                                     editorArea.text = t.slice(0, s) + modelData[1] + t.slice(s, e) + modelData[2] + t.slice(e); editorArea.forceActiveFocus() } } } }
            Text { anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
                   text: root.version ? "## " + (root.r.app || "") + "[" + root.version + "]" : "# " + (root.r.app || ""); color: Theme.faint; font.pixelSize: 12; font.family: Theme.mono }
        }
        ScrollView {
            x: 2; y: 34; width: parent.width - 4; height: parent.height - 36
            visible: !tabs.preview
            TextArea {
                id: editorArea
                background: null; color: Theme.text; wrapMode: TextArea.Wrap
                font.family: Theme.mono; font.pixelSize: 13; leftPadding: 14; rightPadding: 14; topPadding: 10
                placeholderText: "What should people who trust you know about this app? Markdown works."
                placeholderTextColor: Theme.faint; selectByMouse: true; selectionColor: Theme.accentSoft
            }
        }
        ScrollView {
            x: 16; y: 44; width: parent.width - 32; height: parent.height - 52
            visible: tabs.preview
            Text { width: parent.width; text: editorArea.text; textFormat: Text.MarkdownText; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 13 }
        }
    }
    // what I have installed (requirement 8.4.5.1)
    Column {
        id: detailsBox
        visible: !!root.version && root.version === root.r.installedVersion && (root.r.details || []).length > 0
        width: parent.width; spacing: 6
        CheckBox { id: cbDetails; checked: root.includeDetails; onToggled: { root.includeDetails = checked; backend.setPref("includeDetails", checked) }
                   indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbDetails.checked ? Theme.accent : "transparent"; border.width: cbDetails.checked ? 0 : 1.6; border.color: Theme.borderStrong
                       Icon { anchors.centerIn: parent; visible: cbDetails.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                   contentItem: Text { leftPadding: 26; textFormat: Text.StyledText; color: Theme.text; font.pixelSize: 14; verticalAlignment: Text.AlignVCenter
                       text: "<b>Include what I have installed</b> <font color='" + Theme.faint + "'>as Details, published with your review</font>" } }
        Rectangle {
            visible: cbDetails.checked
            x: 26; width: parent.width - 26; height: detailsCol.height + 14; radius: 9; color: Theme.input; border.color: Theme.border
            Column { id: detailsCol; x: 12; y: 7
                Repeater { model: root.r.details || []
                    Text { text: "- " + modelData[0] + ": " + (modelData[0] === "SHA-256" ? modelData[1].slice(0, 12) + "…" : modelData[1]); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono } } }
        }
    }
    // the sandbox I chose for the app, written as the review's suggestion (10.3.1, 8.4.7; review 2, F9).
    // Shown, unlike the other Settings lines (gaps.md 28): a sandbox can name personal folders.
    Column {
        visible: !!root.r.sandboxLine
        width: parent.width; spacing: 4
        CheckBox { id: cbSandbox; objectName: "includeSandbox"; checked: root.includeSandbox; onToggled: root.includeSandbox = checked
                   indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbSandbox.checked ? Theme.accent : "transparent"; border.width: cbSandbox.checked ? 0 : 1.6; border.color: Theme.borderStrong
                       Icon { anchors.centerIn: parent; visible: cbSandbox.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                   contentItem: Text { leftPadding: 26; textFormat: Text.StyledText; color: Theme.text; font.pixelSize: 14; verticalAlignment: Text.AlignVCenter
                       text: "<b>Include my sandbox</b> <font color='" + Theme.faint + "'>as your review's suggestion</font>" } }
        Text { x: 26; width: parent.width - 26; wrapMode: Text.WordWrap; color: cbSandbox.checked ? Theme.text : Theme.faint; font.pixelSize: 12
               text: "Sandbox: " + (root.r.sandboxLine || "") }
        Text { x: 26; width: parent.width - 26; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
               visible: cbSandbox.checked && (root.r.sandboxRefused || []).length > 0
               text: "Left out, since a review can't grant it: " + (root.r.sandboxRefused || []).map(x => x[0]).join(", ") + "." }
    }
    // commit and push (requirement 8.3, 8.4.6)
    Row {
        visible: !!root.r.inRepo
        spacing: 22
        Row { spacing: 8
            CheckBox { id: cbCommit; checked: root.autoCommit; onToggled: { root.autoCommit = checked; if (!checked) root.autoPush = false; backend.setPref("autoCommit", checked) }
                       indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbCommit.checked ? Theme.accent : "transparent"; border.width: cbCommit.checked ? 0 : 1.6; border.color: Theme.borderStrong
                           Icon { anchors.centerIn: parent; visible: cbCommit.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                       contentItem: Text { leftPadding: 26; text: "Auto-commit"; color: Theme.text; font.bold: true; font.pixelSize: 14; verticalAlignment: Text.AlignVCenter } } }
        CheckBox { id: cbPush; checked: root.autoPush; enabled: root.autoCommit && !!root.r.remote
                   onToggled: { root.autoPush = checked; backend.setPref("autoPush", checked) }
                   indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbPush.checked ? Theme.accent : "transparent"; border.width: cbPush.checked ? 0 : 1.6; border.color: Theme.borderStrong
                       opacity: cbPush.enabled ? 1 : 0.5
                       Icon { anchors.centerIn: parent; visible: cbPush.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                   contentItem: Text { leftPadding: 26; text: "Auto-push"; color: cbPush.enabled ? Theme.text : Theme.faint; font.bold: true; font.pixelSize: 14; verticalAlignment: Text.AlignVCenter } }
        Row { spacing: 6; anchors.verticalCenter: parent.verticalCenter
            Icon { name: "branch"; size: 14; color: Theme.faint; anchors.verticalCenter: parent.verticalCenter }
            Text { text: (root.r.branch || "") + (root.r.remote ? " → origin  " + root.r.remote.replace(/^https?:\/\//, "").replace(/^git@/, "").replace(/\.git$/, "") : " · no origin remote")
                   color: Theme.faint; font.pixelSize: 12 } }
    }
    // signing status / result (requirement 8.5)
    Rectangle {
        readonly property bool bad: !!root.result && !!root.result.error
        readonly property bool warnUnsigned: !root.result && root.autoCommit && !root.r.signs
        visible: !!root.r.inRepo && root.autoCommit || bad
        width: parent.width; height: bad ? 60 : 40; radius: 11
        color: bad ? Theme.errSoft : warnUnsigned ? Theme.warnSoft : Theme.okSoft
        border.width: bad ? 1 : 0; border.color: Theme.err
        Icon { x: 14; y: parent.bad ? 13 : 12; name: parent.bad ? "lock" : parent.warnUnsigned ? "warn" : "key"; lineWidth: 1.7; color: parent.bad ? Theme.err : parent.warnUnsigned ? Theme.warn : Theme.ok }
        Column {
            x: 40; anchors.verticalCenter: parent.verticalCenter; spacing: 3; width: parent.width - 40 - (parent.bad ? 200 : 14)
            Text { width: parent.width; elide: Text.ElideRight; font.pixelSize: parent.parent.bad ? 13 : 12.5; font.bold: parent.parent.bad
                   color: parent.parent.bad ? Theme.err : Theme.text
                   text: parent.parent.bad ? root.result.error
                         : parent.parent.warnUnsigned ? "Git isn't set to sign commits (commit.gpgsign), so a push would be refused."
                         : "Commits are signed with your " + (root.r.signFormat === "ssh" ? "SSH" : "OpenPGP") + " key " + (root.r.signKey || "").split("/").pop() }
            Text { visible: parent.parent.bad; text: "Your trust file must be signed by one of its authorities."; color: Theme.text; font.pixelSize: 12 }
        }
        FButton { visible: parent.bad; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                  text: "How to set up signing"; implicitHeight: 34; onClicked: Qt.openUrlExternally("https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits") }
    }
    footerLeft: Text { visible: !!root.result && root.result.saved && !!root.result.committed; text: "Saved to AppKata.md and committed locally."; color: Theme.muted; font.pixelSize: 13 }
    footer: [
        FButton { text: "Cancel"; onClicked: root.close() },
        FButton {
            primary: true
            readonly property bool amend: !!root.result && !!root.result.committed && !root.result.signed
            text: root.saving ? "Saving…" : amend ? "Amend with signing" : "Save"
            enabledButton: !root.saving
            onClicked: {
                if (amend) { backend.amendSigned(); return }
                root.saving = true
                backend.saveReview(root.url, root.tags, root.trustValue, root.ratingValue, editorArea.text, root.autoCommit, root.autoPush,
                                   root.version, root.includeDetails, root.includeSandbox)
            }
        }
    ]
}
