import QtQuick
import QtQuick.Controls.Basic
import "../../src/appkata/qml"

// A window holding the two dialogs the sandbox is chosen in, for tests/test_dialog_contract.py:
// the real QML, driven offscreen against a real Backend, so what the dialogs send is what the
// backend is tested with (the dialogs' own logic -- customized, widened, touched -- included).
ApplicationWindow {
    width: 1920; height: 1040; visible: true      // the design point (requirement 5.2.1)
    SandboxDialog { objectName: "sandbox" }
    InstallDialog { objectName: "install" }
}
