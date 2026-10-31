import QtQuick
import QtQuick.Controls
Button {
    id: control
    property bool primary: false
    hoverEnabled: true
    leftPadding: 16; rightPadding: 16
    implicitHeight: 44
    implicitWidth: Math.max(110, contentItem.implicitWidth+32)
    font.pixelSize: 14
    font.weight: Font.DemiBold
    Accessible.name: text
    contentItem: Text { id: label; text: control.text; font: control.font; elide: Text.ElideRight; color: control.enabled ? "#203024" : "#7d8878"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    ToolTip.visible: hovered && label.truncated
    ToolTip.text: text; ToolTip.delay: 450
    background: Rectangle { radius: 10; color: !control.enabled ? "#e7ebe2" : control.primary ? (control.down ? "#9bce53" : control.hovered ? "#c2ef82" : "#b5e866") : (control.down ? "#dfeacf" : control.hovered ? "#edf2e6" : "#ffffff"); border.width: control.activeFocus ? 2 : 1; border.color: control.activeFocus ? "#456c32" : control.primary && control.enabled ? "#a3d55f" : "#d4decf" }
}
