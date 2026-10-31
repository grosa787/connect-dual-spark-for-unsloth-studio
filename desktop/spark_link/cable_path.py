"""Original cable routes in millimetres; independent of Qt and networking."""

def _add(point,offset): return tuple(a+b for a,b in zip(point,offset))

def _segment(a,b,c,d,steps):
    return [tuple((1-t)**3*a[k]+3*(1-t)**2*t*b[k]+3*(1-t)*t*t*c[k]+t**3*d[k]
                  for k in range(3)) for t in (i/steps for i in range(steps+1))]

def cable_points(start,end):
    start,end=tuple(start),tuple(end)
    # Canonical order makes the same physical path independent of edge direction.
    reverse=start<end if abs(start[2]-end[2])<=100 else start[2]<end[2]
    a,d=(end,start) if reverse else (start,end)
    if abs(a[2]-d[2])<=100:
        points=_segment(a,_add(a,(0,8,135)),_add(d,(0,8,135)),d,36)
    else:
        # Longitudinal triangle edges go around the outer side of the forward
        # case, rather than bending back through its lid/side wall.
        outer=a[0]+(180 if a[0]>=0 else -180)
        level=max(a[1],d[1])+10
        p=(outer,level,a[2]+65); q=(outer,level,d[2]+45)
        dz=(p[2]-q[2])/3
        pieces=(_segment(a,_add(a,(0,8,75)),_add(p,(0,0,40)),p,18),
                _segment(p,_add(p,(0,0,-dz)),_add(q,(0,0,dz)),q,18),
                _segment(q,_add(q,(0,0,-30)),_add(d,(0,8,30)),d,18))
        points=pieces[0]+pieces[1][1:]+pieces[2][1:]
    return list(reversed(points)) if reverse else points
