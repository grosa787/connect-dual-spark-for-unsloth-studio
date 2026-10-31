import QtQuick
import QtQuick.Controls

RadioButton {
    id: control
    spacing: 9; leftPadding: 4; rightPadding: 4
    indicator: Rectangle {
        width: 18; height: 18; radius: 9
        x: control.leftPadding; y: (control.height-height)/2
        color: "#ffffff"; border.width: control.activeFocus ? 2 : 1
        border.color: control.checked || control.activeFocus ? "#648b43" : "#b7c6ad"
        Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; visible: control.checked; color: "#719f42" }
    }
    contentItem: Text {
        text: control.text; font: control.font; color: "#344a31"
        leftPadding: control.indicator.width+control.spacing
        verticalAlignment: Text.AlignVCenter
    }
}
