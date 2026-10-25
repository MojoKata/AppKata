import QtQuick
import QtQuick.Controls.Basic
import "."

// Install options (requirement 4.9): shown on an app's first install when the release offers both
// portable and system-package files, a Windows .exe AppKata can't classify, or, on Linux, package
// channels (Flathub, the distribution; 16.3). The answer is saved for updates. Also opens from the
// App Detail ⋯ menu ("Install options…").
Dialog {
    id: root
    property var plan: ({})
    property int sel: 0
    property string exeAs: ""          // "portable" | "installer" for an unknown .exe
    property bool appMenu: true
    property bool commandLink: true
    property bool stableName: true
    property bool autoUpdate: false     // the app updates itself: a fact AppKata records, not a switch (requirement 4.10)
    property bool change: false        // opened from "Install options…": saves without installing
    property string scope: "me"        // Windows: "me" or "everyone" (requirement 15.4)
    property bool motw: false          // Windows: Mark of the Web (requirement 15.11.1)
    property string sandboxTpl: ""     // the chosen sandbox template (17.3), "" = follow the plan's default/reviews
    property bool sandboxTouched: false
    // the app's kind (17.3.3, review 2 F4): "" = as the download shows (an app until it's known), or the
    // user's "gui"/"cli"; an untouched Sandbox card follows it
    property string appKindChoice: ""
    readonly property string effKind: appKindChoice || (plan.kind ? plan.kind.detected : "") || "gui"
    readonly property var kindEntry: sbx && sbx.byKind ? sbx.byKind[effKind] : null
    onEffKindChanged: {     // read the entry here: kindEntry's own binding may not have caught up yet
        const e = sbx && sbx.byKind ? sbx.byKind[effKind] : null
        if (!sandboxTouched && e) sandboxTpl = e.level === "off" ? "off" : e.template
    }
    signal openSandbox(string url, string template)
    // what the Sandbox dialog saved while this card was open: the card follows it (review 2, F10: the card
    // kept its own pick, and Install sent it over what was saved there)
    property var savedSbx: null
    function sandboxSaved(u) {
        if (u !== plan.url) return
        savedSbx = backend.sandboxInfo(u)
        sandboxTouched = false
        sandboxTpl = savedSbx.level === "off" ? "off" : savedSbx.template
    }
    readonly property var sbx: plan.sandbox && plan.sandbox.applicable ? plan.sandbox : null
    readonly property var sbxTplEntry: sbx ? (sbx.templates || []).find(t => t.key === root.sandboxTpl) : null
    readonly property var sbxChips: !sbx ? [] : root.sandboxTpl === "off" ? [["No sandbox", "ban", "warn"]]
                                   : !root.sandboxTouched && root.savedSbx ? root.savedSbx.chips
                                   : !root.sandboxTouched && root.kindEntry ? root.kindEntry.chips
                                   : root.sbxTplEntry ? root.sbxTplEntry.chips : sbx.chips
    readonly property var win: plan.windows || null
    onSelChanged: if (cur.updatesItself) autoUpdate = true
    readonly property var scopes: !win ? [] : (cur.category === "unknown" && exeAs === "portable") ? ["me", "everyone"] : (cur.scopes || [])
    readonly property var cands: plan.cards || (plan.candidates || []).map(c => Object.assign({ channel: "release" }, c))
    readonly property bool chan: cur.channel === "flatpak" || cur.channel === "package"
    property string updates: "system"       // who updates a channel install (requirement 16.5.3)
    readonly property bool hasPortable: cands.some(c => c.channel === "release" && c.category === "portable")
    onCurChanged: updates = plan.updates || (cur.updater ? "system" : "appkata")
    readonly property var cur: cands[sel] || ({})
    readonly property bool portableChoice: cur.category === "portable" || (cur.category === "unknown" && exeAs === "portable")
    title: (change ? "Install options for " : "Install ") + (plan.name || "") + (change ? "" : " " + (plan.version || ""))
    app: backend.detail(plan.url || "")
    dialogWidth: 680
    function openWith(p, changing) {
        plan = p; change = !!changing; sel = p.chosen || 0; exeAs = ""
        appMenu = p.portable ? p.portable.appMenu : true
        commandLink = p.portable ? p.portable.commandLink : true
        stableName = p.portable ? p.portable.stableName : true
        autoUpdate = !!p.autoUpdate
        scope = p.windows ? p.windows.scope || "me" : "me"
        motw = p.windows ? !!p.windows.motw : false
        appKindChoice = p.kind ? p.kind.choice || "" : ""
        sandboxTouched = false
        savedSbx = null
        const ke = p.sandbox && p.sandbox.byKind ? p.sandbox.byKind[effKind] : null
        sandboxTpl = !(p.sandbox && p.sandbox.applicable) ? "" : ke ? (ke.level === "off" ? "off" : ke.template)
                     : (p.sandbox.level === "off" ? "off" : p.sandbox.template)
        if (cur.updatesItself && !p.autoUpdateBy) autoUpdate = true       // Squirrel apps update themselves (15.7.1)
        updates = p.updates || (cur.updater ? "system" : "appkata")
        open()
    }
    function home(path) { return backend.locations.windows ? (path || "") : (path || "").replace(backend.locations.home, "~") }

    Text {
        width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 14
        readonly property var words: ["", "", "two", "three", "four", "five", "six"]
        text: (root.plan.reasons || []).indexOf("channels") >= 0
              ? (root.plan.name || "It") + " can be installed " + (words[root.cands.length] || root.cands.length) + " ways on "
                + (root.plan.os || "this computer") + ". Choose one; AppKata keeps to it for updates."
              : (root.plan.reasons || []).indexOf("both") >= 0
              ? "This release can be installed two ways on " + (root.plan.os || "this computer") + ". Choose one; AppKata keeps to it for updates."
              : "AppKata couldn't tell whether this download is a portable program or an installer."
    }
    Column {
        width: parent.width; spacing: 8
        Repeater {
            model: root.cands
            Rectangle {
                id: card
                readonly property bool on: index === root.sel
                readonly property var c: modelData
                readonly property bool isCh: c.channel === "flatpak" || c.channel === "package"
                width: parent.width; height: Math.max(74, cardCol.height + 26); radius: 12
                color: on ? Theme.accentSoft : area.containsMouse ? Theme.hover : Theme.input
                border.width: on ? 2 : 1; border.color: on ? Theme.accent : Theme.border
                MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.sel = index }
                Rectangle {     // radio
                    x: 16; anchors.verticalCenter: parent.verticalCenter; width: 20; height: 20; radius: 10
                    color: parent.on ? Theme.accent : "transparent"; border.width: parent.on ? 0 : 1.6; border.color: Theme.borderStrong
                    Rectangle { anchors.centerIn: parent; visible: parent.parent.on; width: 8; height: 8; radius: 4; color: "#ffffff" }
                }
                Column {
                    id: cardCol
                    x: 50; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 50 - 80; spacing: 4
                    Row {
                        spacing: 8
                        Text { text: card.c.label || ""; color: Theme.text; font.bold: true; font.pixelSize: 14 }
                        Pill { visible: !card.isCh
                               text: card.c.category === "portable" ? "Portable" : card.c.category === "system" ? "System package" : "Not sure"
                               color: card.c.category === "portable" ? Theme.okSoft : card.c.category === "system" ? Theme.track : Theme.warnSoft
                               fg: card.c.category === "portable" ? Theme.ok : card.c.category === "system" ? Theme.muted : Theme.warn
                               u: 0.82; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: card.c.channel === "flatpak"; text: "Flatpak"; color: Theme.track; fg: Theme.muted; u: 0.82; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: card.c.channel === "flatpak" && card.c.verified !== undefined && card.c.verified !== null
                               text: card.c.verified ? "Verified" : "Community"; icon: card.c.verified ? "shieldCheck" : ""
                               color: card.c.verified ? Theme.okSoft : Theme.track; fg: card.c.verified ? Theme.ok : Theme.muted; u: 0.82; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: card.c.channel === "package"; text: "System package"; color: Theme.track; fg: Theme.muted; u: 0.82; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: card.c.channel === "package" && !!card.c.origin; text: card.c.origin || ""; color: Theme.track; fg: Theme.muted; u: 0.82; anchors.verticalCenter: parent.verticalCenter }
                        Pill { visible: !!card.c.recommended; text: "Recommended"; color: Theme.accentSoft; fg: Theme.accent; u: 0.82; anchors.verticalCenter: parent.verticalCenter }
                    }
                    Text { visible: card.isCh; width: parent.width; elide: Text.ElideRight; color: Theme.faint; font.pixelSize: 12; font.family: Theme.mono
                           text: (card.c.value || "") + (card.c.version ? " · " + card.c.version : "") + (card.c.channel === "package" ? " · " + (card.c.managerName || "") : "") }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                        text: card.c.channel === "flatpak"
                              ? (card.c.builtFrom ? "Built by Flathub from " + card.c.builtFrom + " · " : "") + "sandboxed · for you only; no admin password"
                              : card.c.channel === "package"
                              ? "Installed for all users with " + (card.c.managerName || "apt") + "; needs your admin password."
                                + (card.c.updater ? " " + (card.c.distro || "The system") + "'s updates keep it current." : " Not updated automatically.")
                              : card.c.category === "portable" ? "Runs from your install folder; no admin password. Updates replace the file."
                              : card.c.category === "system" && root.win ? "Installed by its own installer, which Windows lists in Settings → Apps."
                              : card.c.category === "system" ? "Installed for all users with " + card.c.manager + (card.c.admin ? "; needs your admin password." : ".")
                              : "A Windows program: either portable or an installer."
                    }
                    Text { visible: !card.isCh; text: card.c.name || ""; color: Theme.faint; font.pixelSize: 11; font.family: Theme.mono; width: parent.width; elide: Text.ElideMiddle }
                    Text {      // how far behind the project (16.7.2)
                        visible: card.c.channel === "package" && (card.c.behind || 0) > 0
                        text: card.c.behind + " release" + (card.c.behind > 1 ? "s" : "") + " behind the project"; color: Theme.faint; font.pixelSize: 12 }
                    Text {      // who recommends it, who updates it, the link check (16.1.4, 16.3.2, 16.5.2)
                        visible: text !== ""; width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.StyledText; font.pixelSize: 12; color: Theme.accent
                        text: [card.c.recommendedBy ? "Recommended by " + card.c.recommendedBy : "",
                               card.c.channel === "flatpak" && card.c.updater ? "<font color='" + Theme.warn + "'>" + card.c.updater + " updates Flatpaks automatically</font>" : "",
                               card.c.state === "mismatch" ? "<font color='" + Theme.warn + "'>" + (card.c.via || "The link") + ": " + (card.c.detail || "doesn't match the project") + "</font>" : ""]
                              .filter(x => x).join("  ·  ")
                    }
                }
                Text { anchors.right: parent.right; anchors.rightMargin: 16; y: 14
                       text: card.c.size ? Math.round(card.c.size / 1e6) + " MB" : (card.c.sizeText || ""); color: Theme.faint; font.pixelSize: 12 }
            }
        }
    }
    Row {       // an unclassified .exe (requirement 4.2.1)
        visible: root.cur.category === "unknown"
        spacing: 10
        Text { text: "This file is"; color: Theme.text; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
        Repeater {
            model: [["portable", "A portable program"], ["installer", "An installer"]]
            Rectangle {
                height: 30; width: el.implicitWidth + 24; radius: 15
                color: root.exeAs === modelData[0] ? Theme.accentSoft : Theme.surface; border.color: root.exeAs === modelData[0] ? Theme.accent : Theme.border
                Text { id: el; anchors.centerIn: parent; text: modelData[1]; font.bold: true; font.pixelSize: 12; color: root.exeAs === modelData[0] ? Theme.accent : Theme.text }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.exeAs = modelData[0] }
            }
        }
    }
    Rectangle {     // who updates a channel install (requirement 16.5.3)
        visible: root.chan
        width: parent.width; height: updCol.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: updCol
            x: 16; y: 12; width: parent.width - 32; spacing: 10
            Text { text: "Updates"; color: Theme.text; font.bold: true; font.pixelSize: 13 }
            Repeater {
                model: root.cur.updater ? [["system", "Let " + root.cur.updater + " update it", "detected: it updates " + (root.cur.channel === "flatpak" ? "Flatpaks" : "packages") + " automatically"],
                                           ["appkata", "AppKata updates it", root.cur.updater + " keeps updating it too; AppKata can't turn that off"]]
                                        : [["appkata", "AppKata updates it", "nothing on this computer updates it automatically"]]
                Row {
                    spacing: 10; width: parent.width
                    Rectangle {
                        id: updRadio
                        width: 20; height: 20; radius: 10; anchors.verticalCenter: parent.verticalCenter
                        color: root.updates === modelData[0] ? Theme.accent : "transparent"; border.width: root.updates === modelData[0] ? 0 : 1.6; border.color: Theme.borderStrong
                        Rectangle { anchors.centerIn: parent; visible: root.updates === modelData[0]; width: 8; height: 8; radius: 4; color: "#ffffff" }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.updates = modelData[0] }
                    }
                    Text { anchors.verticalCenter: parent.verticalCenter; textFormat: Text.StyledText; font.pixelSize: 13; color: Theme.text
                           width: parent.width - updRadio.width - parent.spacing; wrapMode: Text.WordWrap      // R3-22
                           text: "<b>" + modelData[1] + "</b> <font color='" + Theme.muted + "'>— " + modelData[2] + "</font>"
                           MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.updates = modelData[0] } }
                }
            }
        }
    }
    Text {
        visible: root.chan && root.hasPortable && !root.change
        text: "Portable options appear when you choose the AppImage."; color: Theme.faint; font.pixelSize: 12
    }
    Rectangle {     // portable options for this app (requirement 4.3.1)
        visible: root.portableChoice && !root.chan
        width: parent.width; height: popts.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: popts
            x: 16; y: 12; width: parent.width - 32; spacing: 10
            // paths and names of any length (Windows' are long): the rows wrap, and so do the texts; the
            // command, whose folder is the long part, comes last (review 3, R3-22)
            Row { spacing: 6; width: parent.width
                Icon { id: installsIcon; name: "folder"; size: 14; color: Theme.muted; y: 1 }
                Text { width: parent.width - installsIcon.width - parent.spacing; wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                       text: "Installs to " + (root.win ? (root.scope === "everyone" ? root.win.folderEveryone : root.win.folderMe) + "\\"
                                                         : root.home((root.plan.portable || {}).folder) + "/") + ((root.plan.portable || {}).command || "")
                       color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono } }
            Flow { spacing: 10; width: parent.width
                CheckBox { id: cbMenu; checked: root.appMenu; onToggled: root.appMenu = checked
                    width: Math.min(implicitWidth, parent.width)
                    indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbMenu.checked ? Theme.accent : "transparent"; border.width: cbMenu.checked ? 0 : 1.6; border.color: Theme.borderStrong
                        Icon { anchors.centerIn: parent; visible: cbMenu.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                    contentItem: Text { leftPadding: 26; text: "Add to the app menu"; color: Theme.text; font.pixelSize: 13; font.bold: true; verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap } }
                CheckBox { id: cbStable; checked: root.stableName; onToggled: root.stableName = checked
                    width: Math.min(implicitWidth, parent.width)
                    indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbStable.checked ? Theme.accent : "transparent"; border.width: cbStable.checked ? 0 : 1.6; border.color: Theme.borderStrong
                        Icon { anchors.centerIn: parent; visible: cbStable.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                    contentItem: Text { leftPadding: 26; text: "Stable name link"; color: Theme.text; font.pixelSize: 13; font.bold: true; verticalAlignment: Text.AlignVCenter; wrapMode: Text.WordWrap } }
                CheckBox { id: cbCmd; checked: root.commandLink; onToggled: root.commandLink = checked
                    width: Math.min(implicitWidth, parent.width)
                    indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbCmd.checked ? Theme.accent : "transparent"; border.width: cbCmd.checked ? 0 : 1.6; border.color: Theme.borderStrong
                        Icon { anchors.centerIn: parent; visible: cbCmd.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                    contentItem: Text { leftPadding: 26; textFormat: Text.StyledText; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13; color: Theme.text
                                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                                        text: "<b>Command</b> <tt>" + ((root.plan.portable || {}).command || "") + "</tt> in " + root.home((root.plan.portable || {}).commandDir) } }
            }
            Row { spacing: 10; visible: !!root.plan.kind     // the app's kind (17.3.3)
                Text { text: "It is"; color: Theme.text; font.pixelSize: 13; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
                Select {
                    objectName: "kindSelect"
                    anchors.verticalCenter: parent.verticalCenter
                    label: root.effKind === "cli" ? "A command-line tool" : "An app with a window"
                    options: [["", root.plan.kind && root.plan.kind.detected ? "As the download shows" : "Decide from the download"],
                              ["gui", "An app with a window"], ["cli", "A command-line tool"]]
                    onPicked: k => { root.appKindChoice = k; if (k) root.appMenu = k === "gui" }
                }
                Text { anchors.verticalCenter: parent.verticalCenter; color: Theme.faint; font.pixelSize: 12
                       text: !root.appKindChoice && root.plan.kind && root.plan.kind.detected ? "from the download"
                             : !root.appKindChoice ? "decided from the download" : "your choice" }
            }
            Text { visible: !!(root.plan.portable || {}).recommendedBy; color: Theme.accent; font.pixelSize: 12
                   text: "Options recommended by " + ((root.plan.portable || {}).recommendedBy || "") }
        }
    }
    Rectangle {     // the Sandbox card (requirement 17.3, C11)
        visible: !!root.sbx && root.portableChoice && !root.chan
        width: parent.width; height: sbxCol.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: sbxCol
            x: 16; y: 12; width: parent.width - 32; spacing: 10
            Row { spacing: 10
                Icon { name: "shield"; size: 15; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
                Text { text: "Sandbox"; color: Theme.text; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                Select {
                    objectName: "sandboxSelect"                  // the dialog contract test picks through it
                    anchors.verticalCenter: parent.verticalCenter
                    icon: root.sandboxTpl === "off" ? "ban" : "shieldCheck"
                    label: (function () { const t = root.sbxTplEntry; return t ? t.label : root.sandboxTpl === "off" ? "Off" : "Custom" })()
                    options: ((root.sbx ? root.sbx.templates : []) || []).map(t => [t.key, t.label]).concat([["off", "Off (no sandbox)"]])
                    onPicked: k => { root.sandboxTpl = k; root.sandboxTouched = true }
                }
                Text { visible: !!root.sbx && root.sbx.source === "reviews" && !!root.sbx.recommendedBy && !root.sandboxTouched
                       text: "suggested by " + (root.sbx ? root.sbx.recommendedBy : ""); color: Theme.accent; font.pixelSize: 12
                       anchors.verticalCenter: parent.verticalCenter }
            }
            Text {      // a review's Off is a suggestion, applied only by the user's click (17.3.2, review 2 F8)
                visible: !!root.sbx && !!root.sbx.suggestsOff && root.sandboxTpl !== "off"
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.accent; font.pixelSize: 12; objectName: "useTheirsOff"
                text: (root.sbx && root.sbx.recommendedBy ? root.sbx.recommendedBy : "A reviewer") + " suggests running it with no sandbox. Use theirs"
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                            onClicked: { root.sandboxTpl = "off"; root.sandboxTouched = true } }
            }
            Flow {
                width: parent.width; spacing: 6
                Repeater {
                    model: root.sbxChips
                    Pill { text: modelData[0]; icon: modelData[1]; u: 0.86
                           color: modelData[2] === "ok" ? Theme.okSoft : modelData[2] === "warn" ? Theme.warnSoft : Theme.track
                           fg: modelData[2] === "ok" ? Theme.ok : modelData[2] === "warn" ? Theme.warn : Theme.muted }
                }
            }
            Text { visible: !!root.sbx && !!root.sbx.appImage && root.sandboxTpl !== "off" && (root.sbx.extractMb || 0) > 0
                   color: Theme.faint; font.pixelSize: 12
                   text: "Unpacking the AppImage for the sandbox adds about " + (root.sbx ? root.sbx.extractMb : 0) + " MB on disk." }
            Text { visible: !!root.sbx && root.sbx.support && root.sbx.support.status === "setup-needed" && root.sandboxTpl !== "off"
                   width: parent.width; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                   text: root.sbx && root.sbx.support && root.sbx.support.declined
                         ? "This system needs a one-time setup before the sandbox can run; until then the app runs unsandboxed. Set it up in Settings → Sandbox."
                         : "This system needs a one-time setup before the sandbox can run; installing asks whether to set it up now." }
            Text {     // Install options on an installed app that runs unsandboxed (17.13, review 2 F13)
                visible: !!root.sbx && !!root.sbx.freshWarning && root.change && root.sandboxTouched && root.sandboxTpl !== "off"
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.warn; font.pixelSize: 12
                text: root.sbx ? root.sbx.freshWarning || "" : "" }
            Text {     // a template made for a folder the user picks, with none yet (17.3, review 2 F10)
                visible: !!root.sbxTplEntry && !!root.sbxTplEntry.folder && root.sandboxTpl !== "off"
                         && root.sbxChips.some(c => c[0] === "No folder yet")
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 12
                text: (root.sbxTplEntry ? root.sbxTplEntry.label : "") + " works on a folder you pick. <a href='#'>Pick its folder…</a>"
                textFormat: Text.StyledText; linkColor: Theme.accent
                onLinkActivated: root.openSandbox(root.plan.url, root.sandboxTouched ? root.sandboxTpl : "")
            }
            Row { spacing: 14
                Text { text: "Customize…"; color: Theme.accent; font.bold: true; font.pixelSize: 12
                       MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor
                                   onClicked: root.openSandbox(root.plan.url, root.sandboxTouched ? root.sandboxTpl : "") } }
            }
        }
    }
    Rectangle {     // who it's for, on Windows (requirement 15.4)
        visible: !!root.win
        width: parent.width; height: scopeCol.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: scopeCol
            x: 16; y: 12; width: parent.width - 32; spacing: 8
            Row {
                spacing: 10
                Text { text: "Install for"; color: Theme.text; font.bold: true; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                Repeater {
                    model: root.scopes.length > 1 ? [["me", "Just me"], ["everyone", "Everyone on this computer"]] : []
                    Rectangle {
                        height: 30; width: sl.implicitWidth + 24; radius: 15
                        color: root.scope === modelData[0] ? Theme.accentSoft : Theme.surface; border.color: root.scope === modelData[0] ? Theme.accent : Theme.border
                        Text { id: sl; anchors.centerIn: parent; text: modelData[1]; font.bold: true; font.pixelSize: 12; color: root.scope === modelData[0] ? Theme.accent : Theme.text }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.scope = modelData[0] }
                    }
                }
                Text { visible: root.scopes.length <= 1; anchors.verticalCenter: parent.verticalCenter; color: Theme.muted; font.pixelSize: 13
                       text: root.scopes.length === 1 ? "Just me: this installer installs only for you" : "This installer decides who it's for" }
            }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                   text: root.scope === "everyone" && root.scopes.length > 1
                         ? "Every account on this computer can use it. Windows asks for administrator rights" + (root.portableChoice ? " once, for the Start-menu shortcut." : " when it installs.")
                         : "Only you can use it. No administrator rights are needed." }
        }
    }
    Rectangle {     // Mark of the Web, in Install options (requirement 15.11.1)
        visible: !!root.win && root.change
        width: parent.width; height: motwCol.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: motwCol
            x: 16; y: 12; width: parent.width - 32; spacing: 6
            CheckBox { id: cbMotw; checked: root.motw; onToggled: root.motw = checked
                indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbMotw.checked ? Theme.accent : "transparent"; border.width: cbMotw.checked ? 0 : 1.6; border.color: Theme.borderStrong
                    Icon { anchors.centerIn: parent; visible: cbMotw.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                contentItem: Text { leftPadding: 26; text: "Mark downloads as from the internet"; color: Theme.text; font.pixelSize: 13; font.bold: true; verticalAlignment: Text.AlignVCenter } }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                   text: "Windows SmartScreen then checks this app's installers and programs, as it does a browser download." }
        }
    }
    Rectangle {     // requirement 4.10.3
        visible: !root.chan
        width: parent.width; height: auCol.height + 24; radius: 12; color: Theme.input; border.color: Theme.border
        Column {
            id: auCol
            x: 16; y: 12; width: parent.width - 32; spacing: 6
            CheckBox { id: cbAuto; checked: root.autoUpdate; onToggled: root.autoUpdate = checked
                indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbAuto.checked ? Theme.accent : "transparent"; border.width: cbAuto.checked ? 0 : 1.6; border.color: Theme.borderStrong
                    Icon { anchors.centerIn: parent; visible: cbAuto.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                contentItem: Text { leftPadding: 26; text: "This app updates itself"; color: Theme.text; font.pixelSize: 13; font.bold: true; verticalAlignment: Text.AlignVCenter } }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                   text: "AppKata installs it and shows new releases, but leaves updating to the app. AppKata can't turn an app's own updater off."
                         + (root.sbx && root.sandboxTpl !== "off" ? " While it runs sandboxed it can't update itself, so AppKata updates it." : "") }
            Text { visible: !!root.plan.autoUpdateBy && root.plan.autoUpdateBy !== "you"; color: Theme.accent; font.pixelSize: 12
                   text: (root.plan.autoUpdateBy || "") + " says it updates itself" }
        }
    }
    footerLeft: Text { width: 280; wrapMode: Text.WordWrap; color: Theme.faint; font.pixelSize: 12
                       text: root.change ? (root.win && root.plan.windows && root.scope !== root.plan.windows.scope && backend.detail(root.plan.url).installed
                                            ? "Saving reinstalls it for " + (root.scope === "everyone" ? "everyone." : "you only.")
                                            : root.sandboxTouched ? "The sandbox applies the next time it starts; the rest from the next update."
                                            : "Applies from the next update.")
                                         : "You can change this later from the app's ⋯ menu." }
    footer: [
        FButton { text: "Cancel"; onClicked: root.close() },
        FButton {
            objectName: "save"                                   // the dialog contract test presses it
            text: root.change ? "Save" : "Install"; icon: root.change ? "" : "download"; primary: true
            enabledButton: root.cur.category !== "unknown" || root.exeAs !== ""
            onClicked: {
                const c = root.cur
                if (root.chan) {      // a package channel (requirement 16.3)
                    const dflt = c.updater ? "system" : "appkata"
                    backend.installWith(root.plan.url, { channel: c.channel, label: c.label, option: c,
                                                         updates: root.updates === dflt && !root.plan.updates ? "" : root.updates,
                                                         install: !root.change })
                    root.close()
                    return
                }
                backend.installWith(root.plan.url, { kind: c.kind, label: c.label, category: root.portableChoice ? "portable" : "system",
                                                     exeKind: c.kind === "exe" ? (c.category === "unknown" ? root.exeAs : c.exeKind) : "",
                                                     appMenu: root.appMenu, commandLink: root.commandLink, stableName: root.stableName,
                                                     autoUpdate: root.autoUpdate,
                                                     scope: root.win ? (root.scopes.length > 1 ? root.scope : root.scopes.length === 1 ? "me" : root.scope) : undefined,
                                                     motw: root.win ? root.motw : undefined,
                                                     sandbox: root.sandboxTouched ? (root.sandboxTpl === "off" ? { template: "off" } : { template: root.sandboxTpl, overrides: {} }) : undefined,
                                                     cliKind: root.sbx ? root.appKindChoice : undefined,
                                                     install: !root.change })
                root.close()
            }
        }
    ]
}
