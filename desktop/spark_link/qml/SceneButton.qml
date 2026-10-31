import QtQuick
import QtQuick.Controls

Button {
    id: control
    implicitHeight: 32; implicitWidth: Math.max(32,contentItem.implicitWidth+20)
    font.pixelSize: 11; font.weight: Font.Medium
    Accessible.name: text
    contentItem: Text { text: control.text; font: control.font; color: "#3b5037"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    background: Rectangle { color: control.down ? "#d6e9c0" : control.hovered ? "#eef5e5" : "#fdfefb"; radius: 7; border.width: control.activeFocus ? 2 : 1; border.color: control.activeFocus ? "#527937" : "#d6dfd0" }
}
