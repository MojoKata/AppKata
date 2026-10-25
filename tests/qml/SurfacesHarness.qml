import QtQuick
import QtQuick.Controls.Basic
import "../../src/appkata/qml"

// The places requirement 17 tells the user most, for tests/test_sandbox_ui_surfaces.py (review 3,
// R3-2): App Detail, Settings > Sandbox, the uninstall confirmation and the review's sandbox line (F9),
// the real QML driven offscreen
// against a real Backend.
ApplicationWindow {
    width: 1100; height: 900; visible: true
    AppDetail { objectName: "detail"; width: 560; height: 880 }
    SettingsDialog { objectName: "settings" }
    ConfirmDialog { objectName: "confirm" }
    ReviewDialog { objectName: "review" }
    LaunchCommandDialog { objectName: "launchCommand" }
}
