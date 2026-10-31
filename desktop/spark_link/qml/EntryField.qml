import QtQuick
import QtQuick.Controls

TextField {
    id: control
    implicitHeight: 42
    leftPadding: 12; rightPadding: 12
    color: "#26392d"; placeholderTextColor: "#798573"
    selectionColor: "#cce6ac"; selectedTextColor: "#203024"
    font.pixelSize: 13
    background: Rectangle {
        radius: 8; color: control.enabled ? "#ffffff" : "#edf0e9"
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#527937" : "#d6dfd0"
    }
}
