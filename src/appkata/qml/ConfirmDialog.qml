import QtQuick
import QtQuick.Controls.Basic
import "."

// Confirmations (requirement 5.8): every removal, trusting a new signer, and quitting during an
// install. Cancel plus a button named for the action. ask(kind, args):
//   uninstall {url} · removeVersion {url, version} · removeTrust {id} · removeAuthority {trust, fp, name}
//   trustSigner / ignoreSigner {trust, fp, name, trustName} · removeToken {host} · removeRelay {relay} · quit {}
//   inUse {url, name, action, version, programs}: Windows can't change a running app (requirement 15.9)
//   msvcrt {url, name}: install Microsoft's Visual C++ run-time (requirement 15.18.3)
//   flathub {url, name, option, updates}: add the Flathub remote before the first Flatpak (requirement 16.3.4)
//   plan {url, name, action, lines, refused, option, updates}: a package plan that changes other packages (16.3.5, 16.4.3)
//   sandboxSetup {url, name, version, choice, ...}: the sandbox's first need, the one-time system setup (17.10)
Dialog {
    id: root
    property string kind: "uninstall"
    property var args: ({})
    property var a: ({})            // the app, for app kinds
    property var t: ({})            // what removing a Trust affects
    property bool deleteSandboxHome: false
    readonly property var sbx: (a.sandbox && a.sandbox.applicable && a.sandbox.installed && a.sandbox.level !== "off") ? a.sandbox : null
    // its private home, at any level: one kept after the app was switched Off is offered too (17.14;
    // review 2's nit: only a sandboxed app's was, so an Off app's home stayed behind, orphaned)
    readonly property var homeOf: (a.sandbox && a.sandbox.applicable && a.sandbox.installed && (a.sandbox.level !== "off" || a.sandbox.hasHome))
                                  ? a.sandbox : null
    readonly property var texts: ({
        uninstall: ["Uninstall " + (a.name || "") + "?", "Uninstall", "trash", true,
                    (a.name || "") + " " + (a.installed || "") + " will be removed. Your settings and documents in your home folder are kept"
                    + (sbx ? ", and the folders you let it use." : ".")],
        removeVersion: ["Remove " + (a.name || "") + " " + (args.version || "") + "?", "Remove version", "trash", true,
                        "This kept version will be deleted. You can still download it again from the list of versions."],
        removeTrust: ["Remove " + (t.name || "") + "?", "Remove trust", "trash", true,
                      "Its " + (t.apps || 0) + " reviews leave your Catalog, and its Authorities are removed with it."],
        removeAuthority: ["Remove " + (args.name || "") + "?", "Remove authority", "trash", true,
                          "Changes signed only by this key will no longer be accepted for " + (args.trustName || "this Trust") + "."],
        trustSigner: ["Trust " + (args.name || "this signer") + "?", "Trust signer", "shieldCheck", false,
                      "Their signed changes to " + (args.trustName || "this Trust") + " will be accepted, including the ones waiting now."],
        ignoreSigner: ["Ignore " + (args.name || "this signer") + "?", "Ignore", "ban", true,
                       "The changes they signed stay unapplied. If they sign again, AppKata asks again."],
        removeToken: ["Remove the token for " + (args.host || "") + "?", "Remove token", "trash", true,
                      "AppKata will use " + (args.host || "the host") + " without a token, with its lower rate limit."],
        removeRelay: ["Remove " + (args.relay || "") + "?", "Remove relay", "trash", true,
                      "Explore will stop searching this relay for ngit repositories."],
        inUse: ["Close " + (args.name || "the app") + " to continue", "Try again", "refresh", false,
                (args.name || "The app") + " is running" + ((args.programs || []).length ? " (" + args.programs.join(", ") + ")" : "")
                + ". Windows can't replace or remove a running program's files. Close it, then try again."],
        msvcrt: ["Install the Visual C++ run-time?", "Install run-time", "download", false,
                 (args.name || "This app") + " needs the Microsoft Visual C++ Run-time, which isn't on this computer. AppKata downloads it"
                 + " from Microsoft and installs it for every account on this computer, so Windows asks for administrator rights once."],
        perms: ["Update " + (a.name || "") + "?", "Update", "update", false,
                (a.name || "The app") + " " + (a.updateTo || "") + " asks for more than the version you have: "
                + (a.ch ? (a.ch.addedPerms || []).join(", ") : "") + ". Reviews were given for what it could do before."],
        flathub: ["Add Flathub?", "Add Flathub", "download", false,
                  (args.name || "This app") + " comes from Flathub, which isn't set up for your account yet. AppKata adds it for you only"
                  + " (flatpak remote-add --user flathub), then installs. No admin password is needed."],
        plan: args.refused
              ? ["Can't " + (args.action === "uninstall" ? "uninstall " : "install ") + (args.name || "the app"), "", "", false,
                 "AppKata never changes what this computer needs to run:"]
              : [(args.action === "uninstall" ? "Uninstall " : args.action === "update" ? "Update " : "Install ") + (args.name || "") + "?",
                 args.action === "uninstall" ? "Uninstall" : args.action === "update" ? "Update" : "Install",
                 args.action === "uninstall" ? "trash" : "download", true,
                 (args.action === "uninstall" ? "Removing it also changes other packages on this computer:" : "This also changes other packages on this computer:")],
        sandboxSetup: ["Set up the sandbox?", "Set up now", "shieldCheck", false,
                       (args.name || "This app") + " runs in a sandbox, but this system blocks it until a one-time setup, which asks for"
                       + " your password once. The setup lets programs use bubblewrap to create user namespaces again, which this system"
                       + " otherwise restricts. Not now installs it to run unsandboxed, and AppKata won't ask again; Settings → Sandbox"
                       + " can set it up later." + (args.waitingNote ? " " + args.waitingNote : "")],
        quit: ["Quit while installing?", "Quit AppKata", "power", true,
               "The install in progress is stopped. A download picks up where it left off the next time you install or update."] })
    readonly property var cur: texts[kind] || ["", "", "", false, ""]
    title: cur[0]
    app: ["uninstall", "removeVersion", "inUse", "msvcrt", "flathub", "plan", "perms", "sandboxSetup"].indexOf(kind) >= 0 ? a : null
    dialogWidth: kind === "removeTrust" && (t.alone || []).length > 0 ? 600 : 500
    function ask(k, x) {
        kind = k
        args = typeof x === "string" ? { url: x } : (x || {})
        a = args.url ? backend.detail(args.url) : ({})
        t = k === "removeTrust" ? backend.trustRemoval(args.id) : ({})
        deleteSandboxHome = false
        open()
    }
    Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 14; lineHeight: 1.15; text: root.cur[4] }
    Rectangle {     // offer to delete the app's private sandbox home (17.14, A23)
        visible: root.kind === "uninstall" && !!root.homeOf
        width: parent.width; height: shCol.height + 20; radius: 10; color: Theme.input; border.color: Theme.border
        Column { id: shCol; x: 14; y: 10; width: parent.width - 28; spacing: 3
            CheckBox { id: cbHome; checked: root.deleteSandboxHome; onToggled: root.deleteSandboxHome = checked
                indicator: Rectangle { y: (parent.height - height) / 2; width: 18; height: 18; radius: 5; color: cbHome.checked ? Theme.accent : "transparent"
                    border.width: cbHome.checked ? 0 : 1.6; border.color: Theme.borderStrong
                    Icon { anchors.centerIn: parent; visible: cbHome.checked; name: "check"; size: 13; lineWidth: 2.2; color: "#ffffff" } }
                contentItem: Text { leftPadding: 26; text: "Also delete its sandbox home folder"; color: Theme.text; font.pixelSize: 13; font.bold: true; verticalAlignment: Text.AlignVCenter } }
            Text { x: 26; text: (root.homeOf ? root.homeOf.home : "").replace(backend.locations.home, "~"); color: Theme.muted; font.pixelSize: 12; font.family: Theme.mono } }
    }
    Rectangle {     // apps that only this Trust lists (requirement 7.5)
        visible: root.kind === "removeTrust" && (root.t.alone || []).length > 0
        width: parent.width; height: aloneCol.height + 24; radius: 11; color: Theme.warnSoft
        Column {
            id: aloneCol
            x: 14; y: 12; width: parent.width - 28; spacing: 6
            Row { spacing: 8
                Icon { name: "warn"; color: Theme.warn; lineWidth: 1.7; anchors.verticalCenter: parent.verticalCenter }
                Text { text: "No other origin, so no more updates:"; color: Theme.text; font.bold: true; font.pixelSize: 13 } }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 13
                   text: (root.t.alone || []).map(x => x.name + " " + x.installed).join(", ") }
            Text { width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
                   text: "Keep updating as my sources adds them as your own Sources first." }
        }
    }
    Rectangle {     // the packages a plan changes (requirement 16.3.5, 16.4.3)
        visible: root.kind === "plan"
        width: parent.width; height: planCol.height + 20; radius: 10; color: root.args.refused ? Theme.errSoft : Theme.input; border.color: Theme.border
        Column {
            id: planCol
            x: 14; y: 10; width: parent.width - 28; spacing: 4
            Repeater {
                model: root.kind === "plan" ? (root.args.lines || []) : []
                Text { width: planCol.width; wrapMode: Text.WordWrap; text: modelData; font.pixelSize: 12; font.family: Theme.mono
                       color: root.args.refused ? Theme.err : Theme.text }
            }
        }
    }
    Text {
        visible: root.kind === "plan" && !root.args.refused
        width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 12
        text: "Check the list before you go on. The package manager asks for your admin password."
    }
    Text {
        visible: root.kind === "quit"
        width: parent.width; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 13
        text: "Installing: " + Object.keys(backend.busy).map(u => (backend.detail(u).name || u) + " (" + Theme.busyLabel(backend.busy[u]) + ")").join(", ")
    }
    footer: [
        FButton { text: root.kind === "plan" && root.args.refused ? "Close" : "Cancel"; onClicked: root.close() },
        FButton {      // the first-need prompt's other answer: install it to run Off, and don't ask again (17.10)
            visible: root.kind === "sandboxSetup"
            text: "Not now"
            onClicked: { backend.answerSandboxSetup(root.args, false); root.close() }
        },
        FButton {
            visible: root.kind === "removeTrust" && (root.t.alone || []).length > 0
            text: "Keep updating as my sources"; icon: "branch"
            onClicked: { backend.removeTrust(root.args.id, true); root.close() }
        },
        FButton {
            visible: root.cur[1] !== ""
            text: root.cur[1]; icon: root.cur[2]; primary: true; danger: root.cur[3]
            onClicked: {
                const x = root.args
                if (root.kind === "uninstall") { if (root.homeOf) backend.uninstallSandbox(x.url, root.deleteSandboxHome); else backend.uninstall(x.url) }
                else if (root.kind === "removeVersion") backend.removeVersion(x.url, x.version)
                else if (root.kind === "removeTrust") backend.removeTrust(x.id, false)
                else if (root.kind === "removeAuthority") backend.removeAuthority(x.trust, x.fp)
                else if (root.kind === "trustSigner") backend.trustSigner(x.trust, x.fp)
                else if (root.kind === "ignoreSigner") backend.ignoreSigner(x.trust, x.fp)
                else if (root.kind === "removeToken") backend.setToken(x.host, "")
                else if (root.kind === "removeRelay") backend.setPref("relays", (backend.prefs.relays || []).filter(r => r !== x.relay))
                else if (root.kind === "quit") Qt.quit()
                else if (root.kind === "msvcrt") backend.installMsvcrt()
                else if (root.kind === "perms") backend.updateWithPermissions(x.url)
                else if (root.kind === "flathub") backend.addFlathubAndInstall(x.url, x.option, x.updates || "")
                else if (root.kind === "sandboxSetup") backend.answerSandboxSetup(x, true)
                else if (root.kind === "plan") {
                    if (x.action === "uninstall") backend.uninstallConfirmed(x.url)
                    else if (x.action === "install-release") backend.installReleaseConfirmed(x.url)
                    else if (x.action === "update") backend.updateChannelConfirmed(x.url)
                    else backend.installChannelConfirmed(x.url, x.option || ({}), x.updates || "")
                }
                else if (root.kind === "inUse") {
                    if (x.action === "uninstall") backend.uninstall(x.url)
                    else if (x.action === "removeVersion") backend.removeVersion(x.url, x.version)
                    else if (x.version) backend.installVersion(x.url, x.version)
                    else backend.update(x.url)
                }
                root.close()
            }
        }
    ]
}
