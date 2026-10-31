import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: editor
    property var topology: ({nodes:[],cables:[]})
    property int selectedIndex: 0
    property bool busy: false
    property var cable: topology.cables[selectedIndex] || ({a:'head',b:'worker2',a_port:0,b_port:0})
    signal selected(int index)
    signal portSelected(int index,string side,int port)
    function t(source) { let language=manager.language; return manager.translate(source) }
    function nodeName(id) { for(let n of topology.nodes) if(n.id===id) return n.name; return id }
    function number(id) { return topology.nodes.findIndex(n=>n.id===id)+1 }
    implicitHeight: 142
    radius: 12; color: "#ffffff"; border.color: "#cbdabd"
    ColumnLayout {
        anchors { fill: parent; margins: 12 }
        spacing: 9
        RowLayout {
            Layout.fillWidth: true; spacing: 7
            Text { text: editor.t("Кабели"); font.pixelSize: 13; font.weight: Font.DemiBold; color: "#344d2d" }
            Item { Layout.fillWidth: true }
            Repeater {
                model: editor.topology.cables
                SceneButton {
                    required property var modelData
                    required property int index
                    objectName: "selectCable_"+index
                    text: editor.number(modelData.a)+" ↔ "+editor.number(modelData.b)
                    chosen: editor.selectedIndex===index
                    onClicked: editor.selected(index)
                    Accessible.name: editor.nodeName(modelData.a)+" ↔ "+editor.nodeName(modelData.b)
                    ToolTip.visible: hovered; ToolTip.delay: 400
                    ToolTip.text: Accessible.name
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
                Text { Layout.fillWidth: true; text: editor.nodeName(editor.cable.a); elide: Text.ElideRight; font.pixelSize: 12; color: "#617159" }
                SelectionBox {
                    objectName: "cableA_"+editor.selectedIndex
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    model: [editor.t("Порт 0 · ближе к Ethernet"),editor.t("Порт 1 · крайний")]
                    currentIndex: editor.cable.a_port; enabled: !editor.busy
                    onActivated: editor.portSelected(editor.selectedIndex,'a',currentIndex)
                    Accessible.name: editor.t("Порт первого конца кабеля")
                }
            }
            Text { text: "↔"; color: "#6f8461"; Layout.topMargin: 19 }
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 5
                Text { Layout.fillWidth: true; text: editor.nodeName(editor.cable.b); elide: Text.ElideRight; font.pixelSize: 12; color: "#617159" }
                SelectionBox {
                    objectName: "cableB_"+editor.selectedIndex
                    Layout.fillWidth: true; Layout.minimumWidth: 0
                    model: [editor.t("Порт 0 · ближе к Ethernet"),editor.t("Порт 1 · крайний")]
                    currentIndex: editor.cable.b_port; enabled: !editor.busy
                    onActivated: editor.portSelected(editor.selectedIndex,'b',currentIndex)
                    Accessible.name: editor.t("Порт второго конца кабеля")
                }
            }
        }
    }
}
