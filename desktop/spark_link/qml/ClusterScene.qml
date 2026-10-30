import QtQuick
import QtQuick3D
import SparkLink 1.0

Item {
    id: scene
    property var nodes: []
    property var topology: ({nodes: [], cables: []})
    property int selectedNode: 0
    property bool editing: false
    property real yaw: -12
    signal selected(int node, int port)
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
            clearColor: "#e7edde"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            aoEnabled: true
            aoStrength: 20
            aoDistance: 6
        }
        PerspectiveCamera {
            id: camera
            property real distance: Math.max(scene.nodes.length===3 ? 800 : 540, (scene.nodes.length===3 ? 1200 : 940)/(scene.width/Math.max(1,scene.height)))
            position: Qt.vector3d(0,distance*0.485,distance*0.875)
            eulerRotation.x: -29; clipFar: 3000; fieldOfView: 34
        }
        DirectionalLight { eulerRotation: Qt.vector3d(-48,-35,0); brightness: 0.9; ambientColor: "#5b6652"; castsShadow: true; shadowFactor: 38; shadowMapQuality: Light.ShadowMapQualityVeryHigh; shadowMapFar: 1200; shadowBias: 1 }
        DirectionalLight { eulerRotation: Qt.vector3d(-20,130,0); brightness: 0.45; color: "#edf5e5" }
        Node {
            id: rig
            eulerRotation.y: scene.yaw
            Model { source: "#Rectangle"; eulerRotation.x: -90; y: -31; scale: Qt.vector3d(20,20,20); materials: PrincipledMaterial { baseColor: "#e7edde"; roughness: 1 } receivesShadows: true }
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
                        start: Qt.vector3d(cableModel.a.x+28+cableModel.cable.a_port*24, 0, cableModel.a.z+92)
                        end: Qt.vector3d(cableModel.b.x+28+cableModel.cable.b_port*24, 0, cableModel.b.z+92)
                    }
                    materials: PrincipledMaterial { baseColor: cableModel.linked ? "#42692f" : "#8c9783"; roughness: 0.6 }
                    castsShadows: true
                }
            }
        }
    }
    Repeater {
        model: scene.nodes.length
        Rectangle {
            required property int index
            property vector3d projected: {
                let angle=scene.yaw; let w=scene.width; let h=scene.height
                let p=scene.positionFor(index)
                return view.mapFrom3DScene(rig.mapPositionToScene(Qt.vector3d(p.x,43,p.z)))
            }
            x: projected.x-width/2; y: projected.y-24
            width: nameLabel.implicitWidth+20; height: 27; radius: 13
            color: scene.selectedNode===index ? "#dff0c8" : "#f6f8f0"
            border.color: "#c9d7bd"
            Text { id: nameLabel; anchors.centerIn: parent; text: (index+1)+" · "+scene.nodes[index].name; font.pixelSize: 11; color: "#385230" }
        }
    }
    MouseArea {
        anchors.fill: parent
        property real previousX
        property real downX
        onPressed: function(mouse) { previousX=mouse.x; downX=mouse.x }
        onPositionChanged: function(mouse) { if(pressed) { scene.yaw += (mouse.x-previousX)*0.25; previousX=mouse.x } }
        onClicked: function(mouse) {
            if(Math.abs(mouse.x-downX)>5) return
            let hit=view.pick(mouse.x,mouse.y)
            if(hit.objectHit && hit.objectHit.deviceIndex !== undefined) scene.selected(hit.objectHit.deviceIndex, hit.objectHit.portIndex)
        }
        onDoubleClicked: scene.yaw=-12
    }
    Rectangle {
        anchors { left: parent.left; bottom: parent.bottom; margins: 16 }
        width: hint.implicitWidth+24; height: 30; radius: 15; color: "#f6f8f1"
        Text { id: hint; anchors.centerIn: parent; text: scene.editing ? "Нажмите на разъём · потяните сцену для поворота" : "3D-вид · потяните для поворота"; font.pixelSize: 12; color: "#53634f" }
    }
}
