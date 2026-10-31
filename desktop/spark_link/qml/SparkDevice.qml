import QtQuick
import QtQuick3D
import SparkLink 1.0

// Original procedural illustration. Dimensions are millimetres: 150 × 150 × 50.5.
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
        y: unit.vertical ? 49.75 : 0
        eulerRotation.z: unit.vertical ? 90 : 0
        PrincipledMaterial { id: gold; baseColor: "#bdae87"; metalness: 0.22; roughness: 0.42 }
        PrincipledMaterial { id: edgeGold; baseColor: "#d0c09a"; metalness: 0.3; roughness: 0.34 }
        PrincipledMaterial { id: graphite; baseColor: "#191d1b"; roughness: 0.68 }
        PrincipledMaterial { id: steel; baseColor: "#939b96"; metalness: 0.78; roughness: 0.3 }
        PrincipledMaterial {
            id: foam
            baseColorMap: Texture { source: "../assets/metal-foam.svg" }
            roughness: 0.86; metalness: 0.24
        }
        // Smooth folded lid and side walls, with a distinct lower seam.
        Model {
            geometry: RoundedBox { width: 150; height: 48; depth: 150; radius: 3.5 }
            y: 1.25; materials: gold; pickable: true
            property int deviceIndex: unit.deviceIndex
            property int portIndex: -1
        }
        Model { geometry: RoundedBox { width: 148; height: 1.6; depth: 148; radius: 0.7 } y: -21.7; materials: graphite }
        Model { geometry: RoundedBox { width: 149; height: 2.4; depth: 149; radius: 1.1 } y: -20.3; materials: gold }
        // Porous metal is on the vertical faces, never a grid on the lid.
        Model { geometry: RoundedBox { flat: true; width: 147; height: 43; depth: 1.8; radius: 3 } y: 1; z: -74.4; materials: foam }
        Model { geometry: RoundedBox { flat: true; width: 147; height: 43; depth: 1.8; radius: 3 } y: 1; z: 74.4; materials: foam }
        Repeater3D {
            model: 2
            Node {
                required property int index
                x: index===0 ? -59 : 59; y: 1; z: -75.6
                Model { geometry: RoundedBox { flat: true; width: 9.5; height: 35; depth: 2; radius: 4.5 } materials: edgeGold }
                Model { geometry: RoundedBox { flat: true; width: 4.3; height: 27; depth: 1.2; radius: 2.1 } z: -1.1; materials: graphite }
                Model { geometry: RoundedBox { flat: true; width: 3.1; height: 22; depth: 0.5; radius: 1.5 } y: 1; z: -1.8; materials: gold }
                Model { source: "#Cube"; y: -12; z: -2; scale: Qt.vector3d(0.034,0.014,0.009); materials: steel }
            }
        }
        Model {
            source: "#Rectangle"; x: -47; y: 6; z: -75.5; eulerRotation.y: 180
            scale: Qt.vector3d(0.15,0.28,1)
            materials: PrincipledMaterial {
                baseColorMap: Texture { source: "../assets/device-mark.svg" }
                alphaMode: PrincipledMaterial.Blend; roughness: 0.8
            }
        }
        // Four rubber feet, also rotated with the physical case.
        Repeater3D {
            model: 4
            Model {
                required property int index
                geometry: RoundedBox { width: 13; height: 2.5; depth: 13; radius: 1.2 }
                x: index%2===0 ? -57 : 57; y: -24; z: index<2 ? -57 : 57
                materials: graphite
            }
        }
        // Rear I/O: power, four USB-C, HDMI, Ethernet, two physical QSFP cages.
        Model { geometry: RoundedBox { flat: true; width: 137; height: 20.5; depth: 2; radius: 7 } y: -10.4; z: 75.7; materials: edgeGold }
        Model { geometry: RoundedBox { flat: true; width: 2.4; height: 11; depth: 1; radius: 0.49 } x: -62; y: -10; z: 77; materials: steel }
        Repeater3D {
            model: 4
            Node {
                required property int index
                x: -54+index*7.2; y: -10; z: 77
                Model { geometry: RoundedBox { flat: true; width: 3.3; height: 10; depth: 1.2; radius: 1.6 } materials: steel }
                Model { geometry: RoundedBox { flat: true; width: 2; height: 8.3; depth: 0.5; radius: 1 } z: 0.8; materials: graphite }
                Model { source: "#Cube"; z: 1.15; scale: Qt.vector3d(0.003,0.06,0.004); materials: gold }
            }
        }
        Model { geometry: RoundedBox { flat: true; width: 15; height: 6; depth: 1; radius: 0.49 } x: -17; y: -11; z: 77; materials: steel }
        Model { geometry: RoundedBox { flat: true; width: 12.8; height: 4; depth: 0.6; radius: 0.29 } x: -17; y: -11; z: 77.7; materials: graphite }
        Model { source: "#Cube"; x: 2; y: -11; z: 77; scale: Qt.vector3d(0.133,0.122,0.02); materials: steel }
        Model { source: "#Cube"; x: 2; y: -11.6; z: 78.2; scale: Qt.vector3d(0.11,0.09,0.008); materials: graphite }
        Model { source: "#Cube"; x: 2; y: -5; z: 77; scale: Qt.vector3d(0.07,0.03,0.02); materials: graphite }
        Repeater3D {
            model: 8
            Model { required property int index; source: "#Cube"; x: -1.5+index; y: -14.6; z: 78.7; scale: Qt.vector3d(0.004,0.015,0.003); materials: gold }
        }
        Repeater3D {
            model: 2
            Node {
                id: cage
                required property int index
                x: 28+index*24; y: -11; z: 77
                Model {
                    geometry: RoundedBox { flat: true; width: 22; height: 13; depth: 3; radius: 0.8 }
                    materials: steel; pickable: true
                    property int deviceIndex: unit.deviceIndex
                    property int portIndex: cage.index
                }
                Model {
                    source: "#Cube"; z: 1.8; scale: Qt.vector3d(0.19,0.1,0.008)
                    materials: graphite; pickable: true
                    property int deviceIndex: unit.deviceIndex
                    property int portIndex: cage.index
                }
                Model {
                    visible: unit.ports.indexOf(cage.index)>=0
                    geometry: RoundedBox { width: 18; height: 9; depth: 17; radius: 0.9 } z: 6.5
                    materials: steel; pickable: true
                    property int deviceIndex: unit.deviceIndex
                    property int portIndex: cage.index
                }
                Model {
                    visible: unit.ports.indexOf(cage.index)>=0
                    geometry: RoundedBox { width: 15; height: 7; depth: 10; radius: 1.2 } z: 14
                    materials: graphite; pickable: true
                    property int deviceIndex: unit.deviceIndex
                    property int portIndex: cage.index
                }
                Model {
                    source: "#Cube"; x: -8; y: -8; z: 1; scale: Qt.vector3d(0.024,0.011,0.01)
                    materials: PrincipledMaterial { baseColor: unit.activePorts.indexOf(cage.index)>=0 ? "#acdf57" : "#3e4940"; emissiveFactor: unit.activePorts.indexOf(cage.index)>=0 ? Qt.vector3d(0.35,0.5,0.06) : Qt.vector3d(0,0,0) }
                }
                Model {
                    visible: unit.selected && unit.ports.indexOf(cage.index)>=0
                    source: "#Cube"; y: 7.2; z: 2; scale: Qt.vector3d(0.21,0.009,0.015)
                    materials: PrincipledMaterial { baseColor: "#b5e866"; roughness: 0.7 }
                }
            }
        }
    }
}
