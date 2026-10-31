import QtQuick
import QtQuick.Controls

Button {
    id: control
    property bool chosen: false
    hoverEnabled: true
    implicitHeight: 36; implicitWidth: Math.max(36,contentItem.implicitWidth+20)
    font.pixelSize: 11; font.weight: Font.Medium
    Accessible.name: text
    contentItem: Text { text: control.text; font: control.font; color: control.enabled ? "#3b5037" : "#8c9785"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    background: Rectangle { color: !control.enabled ? "#eef1ea" : control.down ? "#d6e9c0" : control.chosen ? "#e1efce" : control.hovered ? "#eef5e5" : "#fdfefb"; radius: 7; border.width: control.activeFocus ? 2 : 1; border.color: control.activeFocus ? "#527937" : control.chosen ? "#a3c37f" : "#d6dfd0" }
    ToolTip.visible: hovered; ToolTip.delay: 450; ToolTip.text: Accessible.name
}
