import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    implicitHeight: 42
    implicitWidth: 180
    leftPadding: 12; rightPadding: 30
    font.pixelSize: 13
    contentItem: Text {
        text: control.displayText; font: control.font
        color: control.enabled ? "#26392d" : "#899086"
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Text {
        x: control.width-width-12; y: (control.height-height)/2
        text: "⌄"; font.pixelSize: 18; color: "#62735d"
    }
    background: Rectangle {
        radius: 8; color: control.enabled ? (control.hovered ? "#f6f9f2" : "#ffffff") : "#edf0e9"
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? "#527937" : control.hovered ? "#b1c3a5" : "#d6dfd0"
    }
    delegate: ItemDelegate {
        required property var model
        required property int index
        width: control.width-2; height: 40
        highlighted: control.highlightedIndex===index
        contentItem: Text {
            text: control.textRole ? model[control.textRole] : model.modelData
            color: "#26392d"; font: control.font; elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle { radius: 6; color: parent.highlighted ? "#e5f1d6" : "#ffffff" }
    }
    popup: Popup {
        y: control.height+4; width: control.width; padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight+8,300)
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle { color: "#ffffff"; radius: 9; border.color: "#c5d2bc" }
    }
}
