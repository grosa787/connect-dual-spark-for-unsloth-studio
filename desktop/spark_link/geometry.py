"""Procedural native meshes: rounded chassis and physical cable tubes."""
import math
import struct
from PySide6.QtCore import Property, Signal, QByteArray
from PySide6.QtGui import QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry


def mesh(geometry, vertices):
    geometry.clear()
    geometry.setStride(24)
    geometry.setVertexData(QByteArray(struct.pack('<' + 'f' * len(vertices), *vertices)))
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    geometry.addAttribute(QQuick3DGeometry.Attribute.Semantic.PositionSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.F32Type)
    geometry.addAttribute(QQuick3DGeometry.Attribute.Semantic.NormalSemantic, 12, QQuick3DGeometry.Attribute.ComponentType.F32Type)
    positions = [vertices[i:i+3] for i in range(0,len(vertices),6)]
    geometry.setBounds(QVector3D(*(min(p[i] for p in positions) for i in range(3))),
                       QVector3D(*(max(p[i] for p in positions) for i in range(3))))
    geometry.update()


class RoundedBox(QQuick3DGeometry):
    def __init__(self, parent=None):
        super().__init__(parent)
        vertices = []
        faces = [((1,0,0),(0,1,0),(0,0,1)),((-1,0,0),(0,0,1),(0,1,0)),
                 ((0,1,0),(0,0,1),(1,0,0)),((0,-1,0),(1,0,0),(0,0,1)),
                 ((0,0,1),(1,0,0),(0,1,0)),((0,0,-1),(0,1,0),(1,0,0))]
        steps = 12
        def vertex(n, u, v, a, b):
            p = [50*n[k] + a*u[k] + b*v[k] for k in range(3)]
            core = [max(-42, min(42, x)) for x in p]
            offset = [p[k]-core[k] for k in range(3)]
            length = math.sqrt(sum(x*x for x in offset))
            normal = [x/length for x in offset]
            return [core[k]+normal[k]*8 for k in range(3)] + normal
        for n,u,v in faces:
            for i in range(steps):
                for j in range(steps):
                    points = [vertex(n,u,v,-50+100*a/steps,-50+100*b/steps)
                              for a,b in [(i,j),(i+1,j),(i+1,j+1),(i,j+1)]]
                    for index in (0,1,2,0,2,3): vertices.extend(points[index])
        mesh(self, vertices)


class Cable(QQuick3DGeometry):
    pointsChanged = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._start, self._end = QVector3D(-100,0,0), QVector3D(100,0,0)
        self.rebuild()
    def get_start(self): return self._start
    def set_start(self, value):
        self._start = value
        self.rebuild()
        self.pointsChanged.emit()
    def get_end(self): return self._end
    def set_end(self, value):
        self._end = value
        self.rebuild()
        self.pointsChanged.emit()
    start = Property(QVector3D, get_start, set_start, notify=pointsChanged)
    end = Property(QVector3D, get_end, set_end, notify=pointsChanged)
    def rebuild(self):
        start, end = self._start, self._end
        c1, c2 = start + QVector3D(0,8,135), end + QVector3D(0,8,135)
        rings = []
        for i in range(37):
            t, s = i/36, 1-i/36
            p = s*s*s*start + 3*s*s*t*c1 + 3*s*t*t*c2 + t*t*t*end
            tangent = (3*s*s*(c1-start)+6*s*t*(c2-c1)+3*t*t*(end-c2)).normalized()
            right = QVector3D.crossProduct(tangent, QVector3D(0,1,0)).normalized()
            up = QVector3D.crossProduct(right, tangent).normalized()
            ring = []
            for j in range(9):
                angle = j*math.tau/8
                normal = math.cos(angle)*right + math.sin(angle)*up
                q = p + normal*3.2
                ring.append([q.x(),q.y(),q.z(),normal.x(),normal.y(),normal.z()])
            rings.append(ring)
        vertices = []
        for i in range(36):
            for j in range(8):
                for a,b in ((i,j),(i+1,j),(i+1,j+1),(i,j),(i+1,j+1),(i,j+1)):
                    vertices.extend(rings[a][b])
        mesh(self, vertices)
