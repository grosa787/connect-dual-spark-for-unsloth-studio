import QtQuick
import QtQuick.Controls
Button {
    id: control
    property bool primary: false
    implicitHeight: 44
    implicitWidth: Math.max(110, contentItem.implicitWidth+32)
    font.pixelSize: 14
    font.weight: Font.DemiBold
    Accessible.name: text
    contentItem: Text { text: control.text; font: control.font; color: control.enabled ? "#203024" : "#889383"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    background: Rectangle { radius: 10; color: !control.enabled ? "#e7ebe2" : control.down ? "#9bce53" : control.primary ? (control.hovered ? "#c2ef82" : "#b5e866") : (control.hovered ? "#edf2e6" : "#ffffff"); border.width: control.activeFocus ? 2 : 1; border.color: control.activeFocus ? "#456c32" : control.primary ? "#a3d55f" : "#d4decf"; Behavior on color { ColorAnimation { duration: 120 } } }
}
