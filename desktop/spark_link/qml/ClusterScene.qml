import QtQuick
import QtQuick3D
import QtQuick.Controls
import QtQuick.Layouts
import SparkLink 1.0

Item {
    id: scene
    property var nodes: []
    property var topology: ({nodes: [], cables: []})
    property var orientations: []
    property int selectedNode: 0
    property bool editing: false
    property int activeCable: -1
    property real yaw: 18
    property real pitch: 25
    property real zoom: 1
    property int deviceCount: nodes.length
    function resetView() {
        zoom=1
        yaw=deviceCount===3 ? 0 : 18
        pitch=deviceCount===3 ? 32 : 25
    }
    onDeviceCountChanged: resetView()
    signal selected(int node, int port)
    function t(source) { let language=manager.language; return manager.translate(source) }
    function verticalFor(index) { return scene.orientations[index]===true }
    function anchorFor(index,port) {
        let p=positionFor(index)
        let anchor=manager.portAnchor(port,verticalFor(index))
        return Qt.vector3d(p.x+anchor[0],p.y+anchor[1],p.z+anchor[2])
    }
    function positionFor(index) {
        if (nodes.length === 3) return index === 0 ? Qt.vector3d(-155,0,50) : index === 1 ? Qt.vector3d(155,0,50) : Qt.vector3d(0,0,-200)
        return Qt.vector3d(index === 0 ? -140 : 140,0,0)
    }
    function nodeIndex(id) { for (let i=0;i<topology.nodes.length;i++) if(topology.nodes[i].id===id) return i; return 0 }
    function portsFor(index) {
        let result=[]
        if (!topology.nodes[index]) return result
        let id=topology.nodes[index].id
        for(let c of topology.cables) { if(c.a===id) result.push(c.a_port); if(c.b===id) result.push(c.b_port) }
        return result
    }
    function activeFor(index) {
        let result=[]; let n=nodes[index]
        if (!n || !n.interfaces) return result
        for(let port=0;port<2;port++) {
            let iface=n.interfaces['enp1s0f'+port+'np'+port]
            if(iface && iface.carrier) result.push(port)
        }
        return result
    }
    View3D {
        id: view
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#e9eee4"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            aoEnabled: true
            aoStrength: 28
            aoDistance: 9
            tonemapMode: SceneEnvironment.TonemapModeAces
        }
        PerspectiveCamera {
            id: camera
            property real distance: scene.zoom*Math.max(scene.nodes.length===3 ? 930 : 570, (scene.nodes.length===3 ? 1660 : 940)/(scene.width/Math.max(1,scene.height)))
            position: Qt.vector3d(0,(scene.nodes.length===3 ? 100 : 20)+distance*Math.sin(scene.pitch*Math.PI/180),distance*Math.cos(scene.pitch*Math.PI/180))
            eulerRotation.x: -scene.pitch; clipFar: 4000; fieldOfView: 34
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-48,-35,0); brightness: 1; ambientColor: "#94978b"; castsShadow: true; shadowFactor: 28; shadowMapQuality: Light.ShadowMapQualityVeryHigh; shadowMapFar: 1200; shadowBias: 3 }
        DirectionalLight { eulerRotation: Qt.vector3d(-25,130,0); brightness: 0.45; color: "#f3f4ee" }
        Node {
            id: rig
            eulerRotation.y: scene.yaw
            Model { source: "#Rectangle"; eulerRotation.x: -90; y: -25.4; scale: Qt.vector3d(40,40,40); materials: PrincipledMaterial { baseColor: "#e9eee4"; roughness: 1 } receivesShadows: true }
            Repeater3D {
                model: 3
                SparkDevice {
                    required property int index
                    deviceIndex: index
                    visible: index < scene.nodes.length
                    position: scene.positionFor(index)
                    selected: scene.selectedNode === index
                    ports: scene.portsFor(index)
                    activePorts: scene.activeFor(index)
                    online: scene.nodes[index] ? scene.nodes[index].online : false
                    vertical: scene.verticalFor(index)
                }
            }
            Repeater3D {
                model: 3
                Model {
                    id: cableModel
                    required property int index
                    visible: index < scene.topology.cables.length
                    property var cable: scene.topology.cables[index] || ({a:'head',b:'worker2',a_port:0,b_port:0})
                    property int ai: scene.nodeIndex(cable.a)
                    property int bi: scene.nodeIndex(cable.b)
                    property vector3d a: scene.positionFor(ai)
                    property vector3d b: scene.positionFor(bi)
                    property bool linked: scene.activeFor(ai).indexOf(cable.a_port)>=0 && scene.activeFor(bi).indexOf(cable.b_port)>=0
                    geometry: CableGeometry {
                        start: scene.anchorFor(cableModel.ai,cableModel.cable.a_port)
                        end: scene.anchorFor(cableModel.bi,cableModel.cable.b_port)
                    }
                    materials: PrincipledMaterial { baseColor: scene.editing && scene.activeCable===cableModel.index ? "#66853d" : cableModel.linked ? "#303c31" : "#7c8277"; roughness: 0.78 }
                    castsShadows: true
                }
            }
        }
    }
    Repeater {
        model: scene.nodes.length
        Rectangle {
            required property int index
            z: 1
            property vector3d projected: {
                let angle=scene.yaw; let pitch=scene.pitch; let zoom=scene.zoom; let w=scene.width; let h=scene.height
                let p=scene.positionFor(index)
                return view.mapFrom3DScene(rig.mapPositionToScene(Qt.vector3d(p.x,scene.verticalFor(index) ? 145 : 49,p.z)))
            }
            x: {
                let value=Math.max(6,Math.min(scene.width-width-6,projected.x-width/2))
                if(scene.nodes.length===3 && index===0) return Math.min(value,scene.width/2-width-8)
                if(scene.nodes.length===3 && index===1) return Math.max(value,scene.width/2+8)
                return value
            }
            y: scene.nodes.length===3 && index===2 ? 72 : projected.y-24
            width: Math.max(nameLabel.implicitWidth,statusLabel.implicitWidth)+24; height: scene.nodes[index].online ? 28 : 44; radius: 8
            color: scene.selectedNode===index ? "#e0f1c9" : scene.nodes[index].online ? "#fdfefb" : "#f5f2e9"
            border.color: scene.selectedNode===index ? "#a5c77d" : "#d3dccb"
            border.width: activeFocus ? 2 : 1
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: nameLabel.text
            Accessible.onPressAction: scene.selected(index,-1)
            Keys.onReturnPressed: scene.selected(index,-1)
            Keys.onSpacePressed: scene.selected(index,-1)
            Column {
                anchors.centerIn: parent; spacing: 3
                Text { id: nameLabel; anchors.horizontalCenter: parent.horizontalCenter; text: (index+1)+" · "+scene.nodes[index].name; font.pixelSize: 11; font.weight: Font.Medium; color: "#385230" }
                Text { id: statusLabel; anchors.horizontalCenter: parent.horizontalCenter; visible: !scene.nodes[index].online; text: visible ? scene.t("Не подключён") : ""; font.pixelSize: 10; color: "#796c4c" }
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: scene.selected(index,-1) }
        }
    }
    MouseArea {
        anchors.fill: parent
        property real previousX
        property real downX
        property real previousY
        property real downY
        onPressed: function(mouse) { previousX=downX=mouse.x; previousY=downY=mouse.y }
        onPositionChanged: function(mouse) { if(pressed) { scene.yaw += (mouse.x-previousX)*0.25; scene.pitch=Math.max(8,Math.min(85,scene.pitch+(mouse.y-previousY)*0.18)); previousX=mouse.x; previousY=mouse.y } }
        onWheel: function(wheel) { scene.zoom=Math.max(0.6,Math.min(1.6,scene.zoom*(wheel.angleDelta.y>0 ? 0.9 : 1.1))); wheel.accepted=true }
        onClicked: function(mouse) {
            if(Math.abs(mouse.x-downX)+Math.abs(mouse.y-downY)>5) return
            let hit=view.pick(mouse.x,mouse.y)
            if(hit.objectHit && hit.objectHit.deviceIndex !== undefined) scene.selected(hit.objectHit.deviceIndex, hit.objectHit.portIndex)
        }
        onDoubleClicked: scene.resetView()
    }
    Rectangle {
        anchors { left: parent.left; bottom: parent.bottom; margins: 16 }
        visible: scene.width>760
        width: hint.implicitWidth+20; height: 30; radius: 8; color: "#fdfefb"
        Text { id: hint; anchors.centerIn: parent; text: scene.t("Поворот — мышью · масштаб — колёсиком"); font.pixelSize: 11; color: "#53634f" }
    }
    RowLayout {
        anchors { right: parent.right; bottom: parent.bottom; margins: 12 }
        spacing: 5
        SceneButton { objectName: "cameraRear"; text: scene.t("Сзади"); chosen: Math.abs(scene.yaw%360)<0.1 && scene.pitch===18; onClicked: { scene.yaw=0; scene.pitch=18 } }
        SceneButton { objectName: "cameraFront"; text: scene.t("Спереди"); chosen: Math.abs(scene.yaw%360)===180 && scene.pitch===18; onClicked: { scene.yaw=180; scene.pitch=18 } }
        SceneButton { objectName: "cameraTop"; text: scene.t("Сверху"); chosen: scene.pitch===85; onClicked: { scene.yaw=0; scene.pitch=85 } }
        SceneButton { text: "−"; Accessible.name: scene.t("Отдалить"); enabled: scene.zoom<1.6; onClicked: scene.zoom=Math.min(1.6,scene.zoom*1.15) }
        SceneButton { text: "+"; Accessible.name: scene.t("Приблизить"); enabled: scene.zoom>0.6; onClicked: scene.zoom=Math.max(0.6,scene.zoom/1.15) }
        SceneButton { objectName: "cameraReset"; text: "↺"; Accessible.name: scene.t("Сбросить вид"); onClicked: scene.resetView() }
    }
}
