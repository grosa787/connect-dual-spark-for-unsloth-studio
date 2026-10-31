"""Procedural native meshes: rounded chassis and physical cable tubes."""
import math
import struct
from PySide6.QtCore import Property, Signal, QByteArray
from PySide6.QtGui import QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry
from .cable_path import cable_points


def mesh(geometry, vertices, uv=False):
    geometry.clear()
    stride = 8 if uv else 6
    geometry.setStride(stride * 4)
    geometry.setVertexData(QByteArray(struct.pack('<' + 'f' * len(vertices), *vertices)))
    geometry.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
    geometry.addAttribute(QQuick3DGeometry.Attribute.Semantic.PositionSemantic, 0, QQuick3DGeometry.Attribute.ComponentType.F32Type)
    geometry.addAttribute(QQuick3DGeometry.Attribute.Semantic.NormalSemantic, 12, QQuick3DGeometry.Attribute.ComponentType.F32Type)
    if uv:
        geometry.addAttribute(QQuick3DGeometry.Attribute.Semantic.TexCoord0Semantic, 24, QQuick3DGeometry.Attribute.ComponentType.F32Type)
    positions = [vertices[i:i+3] for i in range(0,len(vertices),stride)]
    geometry.setBounds(QVector3D(*(min(p[i] for p in positions) for i in range(3))),
                       QVector3D(*(max(p[i] for p in positions) for i in range(3))))
    geometry.update()


class RoundedBox(QQuick3DGeometry):
    dimensionsChanged = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._width = self._height = self._depth = 100.0
        self._radius = 8.0
        self._flat = False
        self.rebuild()

    def dimension(name, changed):
        def get(self): return getattr(self, '_'+name)
        def set(self, value):
            value = max(0.01, float(value))
            if getattr(self, '_'+name) == value: return
            setattr(self, '_'+name, value)
            self.rebuild()
            self.dimensionsChanged.emit()
        return Property(float, get, set, notify=changed)

    width = dimension('width', dimensionsChanged)
    height = dimension('height', dimensionsChanged)
    depth = dimension('depth', dimensionsChanged)
    radius = dimension('radius', dimensionsChanged)
    def get_flat(self): return self._flat
    def set_flat(self, value):
        if self._flat == value: return
        self._flat = value
        self.rebuild()
        self.dimensionsChanged.emit()
    flat = Property(bool, get_flat, set_flat, notify=dimensionsChanged)

    def rebuild(self):
        if self._flat:
            self.rebuild_panel()
            return
        vertices = []
        half = [self._width/2, self._height/2, self._depth/2]
        radius = min(self._radius, *half)
        faces = [((1,0,0),(0,1,0),(0,0,1)),((-1,0,0),(0,0,1),(0,1,0)),
                 ((0,1,0),(0,0,1),(1,0,0)),((0,-1,0),(1,0,0),(0,0,1)),
                 ((0,0,1),(1,0,0),(0,1,0)),((0,0,-1),(0,1,0),(1,0,0))]
        def vertex(n, u, v, a, b):
            p = [half[k]*n[k] + a*u[k] + b*v[k] for k in range(3)]
            core = [max(-half[k]+radius, min(half[k]-radius, x)) for k,x in enumerate(p)]
            offset = [p[k]-core[k] for k in range(3)]
            length = math.sqrt(sum(x*x for x in offset))
            normal = [x/length for x in offset]
            hu = sum(abs(u[k])*half[k] for k in range(3))
            hv = sum(abs(v[k])*half[k] for k in range(3))
            return [core[k]+normal[k]*radius for k in range(3)] + normal + [a/(2*hu)+0.5,b/(2*hv)+0.5]
        def coordinates(h):
            # Concentrate triangles around the fillets; scale never flattens a corner.
            low = [-h + radius*i/5 for i in range(6)]
            return sorted(set(low + [0.0] + [-x for x in low]))
        for n,u,v in faces:
            us = coordinates(sum(abs(u[k])*half[k] for k in range(3)))
            vs = coordinates(sum(abs(v[k])*half[k] for k in range(3)))
            for i in range(len(us)-1):
                for j in range(len(vs)-1):
                    points = [vertex(n,u,v,us[a],vs[b])
                              for a,b in [(i,j),(i+1,j),(i+1,j+1),(i,j+1)]]
                    for index in (0,1,2,0,2,3): vertices.extend(points[index])
        mesh(self, vertices, uv=True)

    def rebuild_panel(self):
        """An extruded rounded rectangle: corner radius independent of thickness."""
        hx,hy,hz = self._width/2,self._height/2,self._depth/2
        r = min(self._radius,hx,hy)
        ring = []
        for cx,cy,angle in ((hx-r,hy-r,0),(-hx+r,hy-r,90),
                            (-hx+r,-hy+r,180),(hx-r,-hy+r,270)):
            for i in range(9):
                a = math.radians(angle+i*90/8)
                nx,ny = math.cos(a),math.sin(a)
                ring.append((cx+r*nx,cy+r*ny,nx,ny))
        vertices = []
        def point(p,z,n): return [p[0],p[1],z,*n,p[0]/(2*hx)+0.5,p[1]/(2*hy)+0.5]
        for i,p in enumerate(ring):
            q = ring[(i+1)%len(ring)]
            for z,n,order in ((hz,(0,0,1),(p,q)),(-hz,(0,0,-1),(q,p))):
                for v in ((0,0),*order): vertices.extend(point(v,z,n))
            for v,z in ((p,-hz),(q,-hz),(q,hz),(p,-hz),(q,hz),(p,hz)):
                vertices.extend(point(v,z,(v[2],v[3],0)))
        mesh(self,vertices,uv=True)


class Cable(QQuick3DGeometry):
    pointsChanged = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self._start, self._end = QVector3D(-100,0,0), QVector3D(100,0,0)
        self.rebuild()
    def get_start(self): return self._start
    def set_start(self, value):
        if self._start==value: return
        self._start = value
        self.rebuild()
        self.pointsChanged.emit()
    def get_end(self): return self._end
    def set_end(self, value):
        if self._end==value: return
        self._end = value
        self.rebuild()
        self.pointsChanged.emit()
    start = Property(QVector3D, get_start, set_start, notify=pointsChanged)
    end = Property(QVector3D, get_end, set_end, notify=pointsChanged)
    def rebuild(self):
        points=[QVector3D(*p) for p in cable_points(self._start.toTuple(),self._end.toTuple())]
        rings = []
        for i,p in enumerate(points):
            tangent=(points[min(i+1,len(points)-1)]-points[max(i-1,0)]).normalized()
            right = QVector3D.crossProduct(tangent, QVector3D(0,1,0)).normalized()
            up = QVector3D.crossProduct(right, tangent).normalized()
            ring = []
            for j in range(13):
                angle = j*math.tau/12
                normal = math.cos(angle)*right + math.sin(angle)*up
                q = p + normal*3.2
                ring.append([q.x(),q.y(),q.z(),normal.x(),normal.y(),normal.z()])
            rings.append(ring)
        vertices = []
        for i in range(len(rings)-1):
            for j in range(12):
                for a,b in ((i,j),(i+1,j),(i+1,j+1),(i,j),(i+1,j+1),(i,j+1)):
                    vertices.extend(rings[a][b])
        mesh(self, vertices)
