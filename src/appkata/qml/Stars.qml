import QtQuick
import QtQuick.Shapes
import "."
import "Icons.js" as Icons

// Five stars filled to `value` (halves and fractions shown).
Row {
    id: root
    property real value: 0
    property real r: 5.2
    property color color: Theme.star
    spacing: r * 0.25
    Repeater {
        model: 5
        Item {
            width: root.r * 2; height: root.r * 2
            readonly property real fill: Math.max(0, Math.min(1, root.value - index))
            Shape {
                anchors.fill: parent
                ShapePath { strokeColor: "transparent"; fillColor: Theme.starOff; PathSvg { path: Icons.starPath(root.r, root.r, root.r) } }
            }
            Item {
                width: parent.width * parent.fill; height: parent.height; clip: true
                visible: parent.fill > 0          // a zero-width clip still draws its children
                Shape {
                    width: root.r * 2; height: root.r * 2
                    ShapePath { strokeColor: "transparent"; fillColor: root.color; PathSvg { path: Icons.starPath(root.r, root.r, root.r) } }
                }
            }
        }
    }
}
