import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import "."

ApplicationWindow {
    id: win
    width: 1280
    height: 800
    minimumWidth: 1000
    minimumHeight: 660
    visible: false
    title: "AppKata"
    flags: Qt.Window | Qt.FramelessWindowHint
    color: Theme.bg
    property bool hasTray: false
    property bool windowButtons: false     // Windows: minimize and maximize in the header bar (requirement 15.13)
    property rect maxButtonRect: Qt.rect(0, 0, 0, 0)    // where Maximize is, for Snap Layouts
    property bool maxHover: false
    property string view: backend.installedItems.length > 0 ? "apps" : "catalog"      // requirement 5.1
    property string detailUrl: ""
    readonly property bool detailOpen: detailUrl !== "" && (view === "apps" || view === "catalog")
    property alias catalog: catalogView
    property alias apps: appsView
    property alias sources: sourcesView
    property alias detail: detailPanel
    property alias headerItem: headerBar
    property alias review: reviewDialog
    property alias addSource: addSourceDialog
    property alias removeSource: removeSourceDialog
    property alias addTrust: addTrustDialog
    property alias exploreDlg: exploreDialog
    property alias audit: auditView

    Component.onCompleted: Theme.mode = themeOverride || backend.prefs.theme || "system"
    Connections {
        target: backend
        function onPrefsChanged() { if (!themeOverride) Theme.mode = backend.prefs.theme || "system" }
        function onToast(kind, text) { toast.show(kind, text) }
        function onInUse(info) { win.show(); win.raise(); confirm.ask("inUse", info) }      // requirement 15.9
        function onMsvcrtNeeded(info) { win.show(); win.raise(); confirm.ask("msvcrt", info) }    // requirement 15.18.3
        function onFlathubNeeded(info) { win.show(); win.raise(); confirm.ask("flathub", info) }  // requirement 16.3.4
        function onPermsNeeded(url) { win.show(); win.raise(); confirm.ask("perms", url) }      // requirement 16.6.3
        function onPlanConfirm(info) { win.show(); win.raise(); confirm.ask("plan", info) }       // requirement 16.3.5, 16.4.3
        function onSandboxSetupNeeded(info) { win.show(); win.raise(); confirm.ask("sandboxSetup", info) }  // requirement 17.10
    }
    function closeWindow() { if (hasTray) win.hide(); else requestQuit() }    // requirement 1.7.1
    function requestQuit() {        // requirement 1.7.3: ask first while something installs
        if (backend.installing) { win.show(); win.raise(); confirm.ask("quit", {}) } else Qt.quit()
    }
    Shortcut { sequence: Qt.platform.os === "osx" ? StandardKey.Quit : "Alt+Q"; context: Qt.ApplicationShortcut; onActivated: win.requestQuit() }
    function showDetail(url) { detailUrl = url }
    function openDeepLink(url) { view = "sources"; addSourceDialog.openWith(url) }      // appkata://add/<url>

    HeaderBar {
        id: headerBar
        width: parent.width; z: 10
        window: win
        view: win.view
        onViewSelected: v => { if (v !== win.view) win.detailUrl = ""; win.view = v }
        onAbout: about.open()
        onInstallSelf: selfInstallDialog.openWith(backend.selfInstallOffer)
        onSettings: settingsDialog.show()
        onCloseWindow: win.closeWindow()
        onQuit: win.requestQuit()
    }
    Item {
        id: body
        anchors.top: headerBar.bottom; anchors.bottom: parent.bottom; width: parent.width
        AppsView {
            id: appsView
            anchors.fill: parent; visible: win.view === "apps"
            selected: win.detailUrl; rightInset: win.detailOpen ? detailPanel.width : 0
            onOpenApp: url => win.showDetail(url)
            onConfirmUninstall: url => confirm.ask("uninstall", url)
            onBrowse: win.view = "catalog"
        }
        CatalogView {
            id: catalogView
            anchors.fill: parent; visible: win.view === "catalog"
            selected: win.detailUrl; rightInset: win.detailOpen ? detailPanel.width : 0
            onOpenApp: url => win.showDetail(url)
            onAddSource: addSourceDialog.openWith("")
            onAddTrust: { win.view = "sources"; addTrustDialog.openWith("") }
        }
        SourcesView {
            id: sourcesView
            anchors.fill: parent; visible: win.view === "sources"
            onAddSource: addSourceDialog.openWith("")
            onExplore: exploreDialog.openWith("", "")
            onRemoveSource: s => removeSourceDialog.openFor(s)
            onAddTrust: addTrustDialog.openWith("")
            onSourceSettings: url => sourceSettingsDialog.openFor(url, false)
            onConfirmAction: (k, x) => confirm.ask(k, x)
        }
        AuditView {
            id: auditView
            anchors.fill: parent; visible: win.view === "audit"
        }
        AppDetail {
            id: detailPanel
            visible: win.detailOpen
            x: parent.width - width; width: 450; height: parent.height
            url: win.detailOpen ? win.detailUrl : ""
            onClosed: win.detailUrl = ""
            onReview: url => reviewDialog.openFor(url)
            onOpenSource: url => { win.detailUrl = ""; win.view = "sources"; sourcesView.showSource(url) }     // requirement 2.9.5
            onConfirmRemoveVersion: (url, v) => confirm.ask("removeVersion", { url: url, version: v })
            onPickTag: t => { win.view = "catalog"; backend.selectTag(t) }
            onOpenTrust: id => { win.detailUrl = ""; win.view = "sources"; sourcesView.trustPanel.select(id) }     // requirement 2.9.5
            onConfirmUninstall: url => confirm.ask("uninstall", url)
            onInstallOptions: url => installDialog.openWith(backend.planFor(url), true)
            onOpenSandbox: url => sandboxDialog.openFor(url)
            onShowLaunchCommand: url => launchCommandDialog.openFor(url)
        }
    }
    LaunchCommandDialog { id: launchCommandDialog }
    ReviewDialog { id: reviewDialog }
    AddSourceDialog { id: addSourceDialog }
    RemoveSourceDialog { id: removeSourceDialog }
    AddTrustDialog { id: addTrustDialog }
    SandboxDialog { id: sandboxDialog; onSaved: url => installDialog.sandboxSaved(url) }
    InstallDialog { id: installDialog; onOpenSandbox: (url, tpl) => sandboxDialog.openWith(url, tpl) }
    Connections { target: backend; function onInstallPlan(p) { installDialog.openWith(p, false) } }
    ExploreDialog { id: exploreDialog; onAddRequested: (url, link) => addSourceDialog.openWith(url, link) }
    ConfirmDialog { id: confirm }
    SelfInstallDialog { id: selfInstallDialog }
    Timer {     // first start of a downloaded AppImage (requirement 2.11.3.1)
        interval: 600; running: !tourMode; repeat: false
        onTriggered: { const o = backend.selfInstallOffer; if (o && o.ask) selfInstallDialog.openWith(o) }
    }
    SettingsDialog { id: settingsDialog; onConfirmAction: (k, x) => confirm.ask(k, x) }
    SourceSettingsDialog { id: sourceSettingsDialog }
    Toast { id: toast; z: 20 }
    Popup {
        id: about
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 440; padding: 28
        Overlay.modal: Rectangle { color: Theme.scrim }
        background: Rectangle { radius: 20; color: Theme.surface; border.color: Theme.border }
        contentItem: Column {
            spacing: 10
            Row { spacing: 16
                Image { source: "assets/appkata.svg"; width: 64; height: 64; sourceSize: Qt.size(128, 128) }
                Column { anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    Text { text: "AppKata"; color: Theme.text; font.pixelSize: 22; font.bold: true }
                    Text { text: "Version " + appVersion; color: Theme.muted; font.pixelSize: 13 } } }
            Text { width: 384; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 13; topPadding: 6
                   text: "A FOSS app store built on git. Apps come from your Sources and from Trusts." }
            Grid {
                columns: 2; columnSpacing: 14; rowSpacing: 6; topPadding: 4
                Text { text: "License"; color: Theme.faint; font.pixelSize: 12 }
                Text { text: "GNU GPL, version 3 or later"; color: Theme.text; font.pixelSize: 12 }
                Text { text: "Project"; color: Theme.faint; font.pixelSize: 12 }
                Text { text: backend.selfUrl.replace("https://", ""); color: Theme.accent; font.pixelSize: 12; font.bold: true
                       MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally(backend.selfUrl) } }
                Text { text: "Runs on"; color: Theme.faint; font.pixelSize: 12 }
                Text { text: "Linux, macOS, and Windows 10 and later"; color: Theme.text; font.pixelSize: 12 }
                Text { text: "Built with"; color: Theme.faint; font.pixelSize: 12 }
                Text { text: "Python and Qt (PySide6)"; color: Theme.text; font.pixelSize: 12 }
            }
            Row { spacing: 8; topPadding: 8
                FButton { text: "Check for updates"; icon: "sync"; onClicked: { about.close(); backend.sync() } }
                FButton { text: "Close"; primary: true; onClicked: about.close() } }
        }
    }
    ResizeHandles { window: win }

    // --- hooks for the screenshot tour (tour.py) -------------------------------------
    // the keys of the step that were read, so the tour can tell a setting nothing applied (review 3,
    // R3-28: U02's audit filter was read nowhere); a review's settings as "reviewSet.<key>"
    property var tourKeysRead: ({})
    function tourWatched(step) {
        const seen = tourKeysRead
        const watch = (o, at) => new Proxy(o, { get: (t, k) => {
            if (typeof k !== "string") return t[k]
            seen[at + k] = true
            return k === "reviewSet" && t[k] ? watch(t[k], "reviewSet.") : t[k]
        } })
        return watch(step, "")
    }
    function tourKeys() { const keys = Object.keys(tourKeysRead); tourKeysRead = ({}); return keys }
    function tour(step) {
        step = tourWatched(step)
        headerBar.menu.close(); detailPanel.menu.close(); sourcesView.sourceMenu.close(); sourcesView.trustsPopup.close()
        catalogView.tagsPopup.close(); sourcesView.trustPanel.hoverInfo = null
        about.close()
        backend.demoSelfUpdated(!!step.selfUpdated)
        backend.demoMsvcrt(step.msvcrt || "")
        backend.demoSelfInstall(step.selfInstall ? backend.locations.home + "/Downloads/AppKata-" + appVersion + "-x86_64.AppImage" : "")
        backend.demoChannels(!!step.channels)          // DEV ONLY: package channels from the demo file (requirement 16)
        backend.demoSandbox(step.sandboxDemo || "")    // DEV ONLY: force a sandbox state the offscreen tour can't show (17)
        for (const d of [reviewDialog, addSourceDialog, removeSourceDialog, addTrustDialog, confirm, settingsDialog, exploreDialog, installDialog,
                         sourceSettingsDialog, addSourceDialog.settingsDialog, selfInstallDialog, sandboxDialog]) d.close()
        catalogView.allTagsPopup.close()
        backend.demoClearBusy()
        for (const u in (step.busy || {})) backend.demoBusy(u, step.busy[u])
        sourcesView.highlightUrl = step.highlightSource || ""
        Theme.mode = step.theme || themeOverride || "dark"
        if (step.view) view = step.view
        auditView.kind = step.auditFilter || ""             // the Audit's kind filter (U02: Apps)
        detailUrl = step.detail || ""
        detailPanel.pencilHover = !!step.pencilHover
        detailPanel.demoVersionTip = step.versionTip === undefined ? -1 : step.versionTip
        appsView.hoverTrash = step.hoverTrash || ""
        backend.setSearch(step.search || "")
        sourcesView.trustPanel.select(step.trust === undefined ? -1 : step.trust)
        if (step.expanded !== undefined) detailPanel.expanded = step.expanded
    }
    // the tour: whether a screen is still waiting on the network (it takes the shot when not)
    function tourBusy() { return addSourceDialog.checking || exploreDialog.searching }
    function tourPopups(step) {
        step = tourWatched(step)
        if (step.appMenu) headerBar.menu.open()
        if (step.review) { reviewDialog.openFor(step.review); if (step.reviewSet) {
            const s = step.reviewSet
            if (s.version !== undefined) { reviewDialog.version = s.version; reviewDialog.loadVersion() }
            if (s.tags) reviewDialog.tags = s.tags
            if (s.trust !== undefined) reviewDialog.trustValue = s.trust
            if (s.rating !== undefined) reviewDialog.ratingValue = s.rating
            if (s.text !== undefined) reviewDialog.editor.text = s.text
            if (s.autoCommit !== undefined) { reviewDialog.autoCommit = s.autoCommit; reviewDialog.autoPush = s.autoPush }
            if (s.result) reviewDialog.result = s.result } }
        if (step.addSource) addSourceDialog.openWith(step.addSource)
        if (step.installPlan) installDialog.openWith(backend.planFor(step.installPlan), false)
        if (step.installOptions) installDialog.openWith(backend.planFor(step.installOptions), true)
        if (step.about) about.open()
        if (step.selfInstall) selfInstallDialog.openWith(backend.selfInstallOffer)
        if (step.settings) { settingsDialog.show(); settingsDialog.scrollTo(step.settings) }
        if (step.explore) { exploreDialog.openWith(step.explore[1], step.explore[0]); exploreDialog.demoTip = step.explore[2] === undefined ? -1 : step.explore[2] }
        if (step.versionsMore) detailPanel.versionsShown += 5
        if (step.scrollDetail !== undefined) detailPanel.scrollTo(step.scrollDetail)
        if (step.sandbox) { sandboxDialog.openFor(step.sandbox); if (step.sandboxScroll) sandboxDialog.scrollTo(step.sandboxScroll) }
        if (step.removeSource) removeSourceDialog.openFor(backend.sourceItems.find(s => s.url === step.removeSource))
        if (step.sourceMenu) {
            const i = backend.sourceItems.findIndex(s => s.url === step.sourceMenu)
            sourcesView.openMenu(backend.sourceItems[i], tourAnchor(sourcesView, i))
        }
        if (step.trustsHover) {
            const i = backend.sourceItems.findIndex(s => s.url === step.trustsHover)
            sourcesView.trustsHoverUrl = step.trustsHover
            sourcesView.showTrusts(backend.sourceItems[i], tourAnchor(sourcesView, i, true))
        }
        if (step.signerHover) sourcesView.trustPanel.hoverInfo = step.signerHover
        if (step.tagsHover) catalogView.showTagsFor(step.tagsHover)
        if (step.allTags) catalogView.allTagsPopup.open()
        if (step.sourceSettings) sourceSettingsDialog.openFor(step.sourceSettings, false, step.sourceSettingsSet)
        if (step.addSourceSettings) addSourceDialog.settingsDialog.openFor(addSourceDialog.p ? addSourceDialog.p.url : step.addSource, true, step.sourceSettingsSet)
        if (step.confirmOver === "settings") { settingsDialog.show(); settingsDialog.scrollTo("accounts") }
        if (step.confirm) confirm.ask(step.confirm[0], step.confirm[1])
    }
    function tourSignerHover(trustId, i) { sourcesView.trustPanel.showSigner(trustId, i) }
    // anchors for popups the tour opens: a row's ⋯ button, a row's "In N trusts" pill, a tile's › button
    function tourAnchor(view, i, pill) { return findChild(view, pill ? "inTrusts" : "dots", i) }
    function tourTileAnchor(a) { return findChild(catalogView, "more", backend.catalogItems.indexOf(a)) }
    function findChild(root, id, index) {
        let n = -1, found = null
        function walk(item) {
            if (found) return
            for (let k = 0; k < item.children.length; k++) {
                const c = item.children[k]
                if (c.objectName === id) { n++; if (n === index) { found = c; return } }
                walk(c)
            }
        }
        walk(root)
        return found || root
    }
}
