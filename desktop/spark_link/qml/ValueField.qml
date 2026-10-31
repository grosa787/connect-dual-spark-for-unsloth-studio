import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ColumnLayout {
    id: control
    property string label: ""
    property string value: ""
    property string placeholder: ""
    property bool editable: true
    property bool numeric: false
    signal committed(string text)
    spacing: 6
    Layout.minimumWidth: 0
    Text { Layout.fillWidth:true; text:control.label; font.pixelSize:12; color:"#52654b"; wrapMode:Text.WordWrap }
    TextField {
        Layout.fillWidth:true; implicitHeight:40
        text:control.value; placeholderText:control.placeholder; readOnly:!control.editable
        font.pixelSize:14; selectByMouse:true
        horizontalAlignment:control.numeric ? TextInput.AlignRight : TextInput.AlignLeft
        inputMethodHints:control.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
        Accessible.name:control.label
        onEditingFinished:if(control.editable) control.committed(text)
        background:Rectangle { color:control.editable ? "white" : "#eff3e9"; radius:8; border.width:parent.activeFocus ? 2 : 1; border.color:parent.activeFocus ? "#799f4e" : "#d4decb" }
    }
}
