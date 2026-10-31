import QtQuick
import QtQuick3D
import SparkLink 1.0

Node {
    id: unit
    property int deviceIndex: 0
    property bool selected: false
    property var ports: []
    property var activePorts: []
    property bool online: false
    property bool vertical: false
    Node {
        id: chassis
        y: unit.vertical ? 44 : 0
        eulerRotation.z: unit.vertical ? 90 : 0
    PrincipledMaterial { id: gold; baseColor: "#c9b78b"; metalness: 0.3; roughness: 0.34 }
    PrincipledMaterial { id: edgeGold; baseColor: "#dbc79b"; metalness: 0.35; roughness: 0.29 }
    PrincipledMaterial { id: graphite; baseColor: "#232724"; roughness: 0.65 }
    PrincipledMaterial { id: steel; baseColor: "#77817a"; metalness: 0.8; roughness: 0.26 }
    Model {
        geometry: RoundedBox {}
        scale: Qt.vector3d(1.5, 0.49, 1.5)
        materials: gold
        pickable: true
        property int deviceIndex: unit.deviceIndex
        property int portIndex: -1
        castsShadows: true
    }
    Model { source: "#Cube"; y: 24.5; scale: Qt.vector3d(1.31,0.012,1.31); materials: graphite }
    // A machined perforated gold lid. Real geometry catches the scene lights.
    Repeater3D {
        model: 21
        Node {
            required property int index
            z: -62 + index*6.2
            Model { source: "#Cube"; y: 25.4; scale: Qt.vector3d(1.29,0.012,0.014); materials: edgeGold }
        }
    }
    Repeater3D {
        model: 21
        Node {
            required property int index
            x: -62 + index*6.2
            Model { source: "#Cube"; y: 25.5; scale: Qt.vector3d(0.014,0.012,1.29); materials: gold }
        }
    }
    // Rear I/O panel, USB, HDMI, RJ45, and the two selectable QSFP cages.
    Model { geometry: RoundedBox {} z: 74.4; scale: Qt.vector3d(1.3,0.29,0.015); materials: graphite }
    Repeater3D {
        model: 4
        Model { required property int index; source: "#Cube"; x: -53+index*12; z: 75.5; y: 0; scale: Qt.vector3d(0.065,0.045,0.015); materials: steel }
    }
    Model { source: "#Cube"; x: 1; z: 75.6; scale: Qt.vector3d(0.125,0.105,0.018); materials: steel }
    Repeater3D {
        model: 2
        Node {
            id: cage
            required property int index
            x: 28+index*24
            z: 75.5
            Model {
                source: "#Cube"; scale: Qt.vector3d(0.205,0.145,0.034)
                materials: PrincipledMaterial { baseColor: unit.ports.indexOf(cage.index)>=0 ? "#9bcf59" : "#8b9087"; metalness: 0.7; roughness: 0.25 }
                pickable: true
                property int deviceIndex: unit.deviceIndex
                property int portIndex: cage.index
            }
            Model { source: "#Cube"; z: 2; scale: Qt.vector3d(0.166,0.104,0.018); materials: graphite }
            Model {
                visible: unit.ports.indexOf(cage.index)>=0
                source: "#Cube"; z: 10; scale: Qt.vector3d(0.168,0.094,0.18)
                materials: PrincipledMaterial { baseColor: "#444d41"; metalness: 0.5; roughness: 0.36 }
            }
            Model {
                source: "#Sphere"; x: -8; y: -9; z: 3; scale: Qt.vector3d(0.022,0.022,0.022)
                materials: PrincipledMaterial { baseColor: unit.activePorts.indexOf(cage.index)>=0 ? "#8bc34a" : "#50574e"; emissiveFactor: unit.activePorts.indexOf(cage.index)>=0 ? Qt.vector3d(0.3,0.6,0.05) : Qt.vector3d(0,0,0) }
            }
        }
    }
    Repeater3D {
        model: 17
        Node {
            required property int index
            x: -60+index*7.5
            Model { source: "#Cube"; y: -10; z: -74.6; scale: Qt.vector3d(0.032,0.12,0.012); materials: graphite }
        }
    }
    }
    // Orientation does not change the ground plane or physical port IDs.
    Model {
        source: "#Cylinder"; y: -28; scale: Qt.vector3d(unit.vertical ? 0.6 : 1.23,0.015,unit.vertical ? 1.6 : 1.23)
        materials: PrincipledMaterial { baseColor: unit.selected ? "#b5e866" : "#d6ded0"; roughness: 0.9 }
        receivesShadows: true
    }
}
