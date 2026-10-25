pragma Singleton
import QtQuick

// Design tokens, the same as the mockups' (screenshots/src/render.js THEMES).
QtObject {
    id: t
    property string mode: "system"          // "system" | "dark" | "light"
    // The time "ago" texts and the Audit's days are worked out from: a binding that reads it is
    // worked out again as it ticks. The one place QML reads the time (review 3, R3-29: a binding
    // that read Date.now() kept its first answer, so the header said "Synced just now" for hours)
    property double now: Date.now()
    property Timer clock: Timer { interval: 30000; running: true; repeat: true; onTriggered: t.now = Date.now() }
    readonly property bool dark: mode === "dark"
        || (mode !== "light" && Qt.styleHints.colorScheme !== Qt.ColorScheme.Light)

    readonly property color bg: dark ? "#15171e" : "#f5f6fa"
    readonly property color side: dark ? "#1a1c24" : "#eff1f6"
    readonly property color surface: dark ? "#1f222b" : "#ffffff"
    readonly property color raised: dark ? "#262a35" : "#ffffff"
    readonly property color hover: dark ? "#2f3442" : "#f3f4f8"
    readonly property color border: dark ? "#2c303c" : "#e4e7ef"
    readonly property color borderStrong: dark ? "#3a3f4d" : "#d4d8e3"
    readonly property color text: dark ? "#eceef4" : "#1b1f2b"
    readonly property color muted: dark ? "#9aa0b3" : "#6a7084"
    readonly property color faint: dark ? "#686d80" : "#a0a6b6"
    readonly property color accent: dark ? "#8089ff" : "#5a67f2"
    readonly property color accentSoft: dark ? "#2a2d52" : "#eceefe"
    readonly property color ok: dark ? "#34d399" : "#0f9f6c"
    readonly property color okSoft: dark ? "#133a2d" : "#e2f6ed"
    readonly property color warn: dark ? "#fbbf24" : "#c26a04"
    readonly property color warnSoft: dark ? "#3a2e12" : "#fdf1dc"
    readonly property color err: dark ? "#fb7185" : "#e0445a"
    readonly property color errSoft: dark ? "#3d1a22" : "#fde8eb"
    readonly property color track: dark ? "#2c303c" : "#eceef4"
    readonly property color illusA: dark ? "#222739" : "#edf2ff"
    readonly property color illusB: dark ? "#2a2442" : "#f5eeff"
    readonly property color input: dark ? "#1a1d25" : "#f7f8fb"
    readonly property color segOn: dark ? "#343847" : "#ffffff"
    readonly property color tipBg: dark ? "#eceef4" : "#1b1f2b"
    readonly property color tipFg: dark ? "#1b1f2b" : "#ffffff"
    readonly property color star: dark ? "#fbbf24" : "#e0a106"
    readonly property color starOff: dark ? "#3a3f4d" : "#dfe2ea"
    readonly property color scrim: dark ? Qt.rgba(0.04, 0.05, 0.08, 0.55) : Qt.rgba(0.04, 0.05, 0.08, 0.32)
    readonly property string mono: Qt.platform.os === "windows" ? "Consolas" : "DejaVu Sans Mono"
    readonly property var warnTags: ["spyware", "malware", "ads", "tracking", "knownvuln"]

    function mb(n) { return n >= 1e8 ? Math.round(n / 1e6) + " MB" : (n / 1e6).toFixed(1) + " MB" }
    // an install in progress (requirement 4.8.1): "Downloading 45%", "Verifying…", "Waiting"
    function busyLabel(b) {
        if (!b) return ""
        if (b.phase === "Downloading") return "Downloading" + (b.total ? " " + Math.floor(b.progress * 100) + "%" : "…")
        return b.phase === "Waiting" ? "Waiting" : b.phase + "…"
    }
    function busyDetail(b) {
        if (!b || b.phase !== "Downloading") return b && b.phase === "Waiting" ? "Starts after the install in progress" : ""
        return (b.total ? mb(b.got) + " of " + mb(b.total) : mb(b.got)) + (b.speed > 0 ? " · " + mb(b.speed) + "/s" : "")
    }
    function alpha(c, a) { const q = Qt.color(c); return Qt.rgba(q.r, q.g, q.b, a) }
    function fileUrl(p) {
        if (!p) return ""
        if (p.startsWith("file:") || p.startsWith("qrc:")) return p
        return /^[A-Za-z]:/.test(p) ? "file:///" + p.replace(/\\/g, "/") : "file://" + p      // C:\… on Windows
    }
    function localPath(u) {         // a file dialog's URL as a path for this OS
        let s = decodeURIComponent(u.toString()).replace(/^file:\/\//, "")
        return /^\/[A-Za-z]:/.test(s) ? s.slice(1).replace(/\//g, "\\") : s
    }
    function shortDate(iso) {
        if (!iso) return ""
        const d = new Date(iso)
        return isNaN(d) ? "" : d.toLocaleDateString(Qt.locale("en_US"), "MMM d")
    }
    function ago(iso) {
        if (!iso) return "never"
        const s = (t.now - new Date(iso).getTime()) / 1000
        if (s < 90) return "just now"
        if (s < 3600) return Math.round(s / 60) + " min ago"
        if (s < 86400 * 2) return Math.round(s / 3600) + " h ago"
        return Math.round(s / 86400) + " days ago"
    }
}
