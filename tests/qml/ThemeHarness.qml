import QtQuick
import QtQuick.Controls.Basic
import "../../src/appkata/qml"

// Settings, for tests/test_theme_shown.py: the theme shown is set the way Main.qml and the tour set
// it, and the Theme row is read back.
ApplicationWindow {
    width: 1920; height: 1040; visible: true      // the design point (requirement 5.2.1)
    function showTheme(m) { Theme.mode = m }
    SettingsDialog { objectName: "settings" }
}
