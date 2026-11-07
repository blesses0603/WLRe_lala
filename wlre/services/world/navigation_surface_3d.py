"""Bounded 3-D point-surface containment; never grants actor/movement authority."""
import math


def _dot(a,b):return sum(x*y for x,y in zip(a,b))
def _sub(a,b):return tuple(x-y for x,y in zip(a,b))


def segment_on_surface(a,b,triangles,*,plane_tolerance=1e-5):
    """World-unit coordinates; plane band plus barycentric clipping, not X/Z projection.

    1e-5 is a numerical allowance for pinned native float output, not terrain
    flattening or actor clearance. Reject unsupported/degenerate geometry.
    """
    if not 0<plane_tolerance<=1e-5 or not 1<=len(triangles)<=512:raise ValueError('Surface bound')
    points=[a,b]+[p for tri in triangles for p in tri]
    if any(len(tri)!=3 for tri in triangles) or any(len(p)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in points):
        raise ValueError('Invalid surface point')
    intervals=[]
    for tri in triangles:
        base,u,v=tri[0],_sub(tri[1],tri[0]),_sub(tri[2],tri[0])
        normal=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        norm=math.sqrt(_dot(normal,normal));uu,uv,vv=_dot(u,u),_dot(u,v),_dot(v,v);den=uu*vv-uv*uv
        if norm<=1e-12 or den<=1e-20:raise ValueError('Degenerate 3-D triangle')
        ends=[]
        for point in (a,b):
            q=_sub(point,base);qu,qv=_dot(q,u),_dot(q,v)
            s=(vv*qu-uv*qv)/den;t=(uu*qv-uv*qu)/den
            ends.append((_dot(normal,q)/norm,s,t,1-s-t))
        lo,hi=0.,1.
        # Every condition is a linear inequality f(t)>=0.
        limits=[(plane_tolerance-ends[0][0],plane_tolerance-ends[1][0]),
                (plane_tolerance+ends[0][0],plane_tolerance+ends[1][0])]
        # Express lateral allowance in world units, not a scale-dependent
        # fixed barycentric epsilon (native float endpoints lie near portals).
        bands=(plane_tolerance*math.sqrt(vv)/norm,
               plane_tolerance*math.sqrt(uu)/norm,
               plane_tolerance*math.sqrt(_dot(_sub(u,v),_sub(u,v)))/norm)
        limits.extend((ends[0][i]+band,ends[1][i]+band) for i,band in zip((1,2,3),bands))
        for start,end in limits:
            if start<0 and end<0:break
            delta=end-start
            if delta>0:lo=max(lo,-start/delta)
            elif delta<0:hi=min(hi,-start/delta)
            if lo>hi:break
        else:
            if lo<=hi:intervals.append((max(0.,lo),min(1.,hi)))
    reach=0.
    for lo,hi in sorted(intervals):
        if lo>reach+1e-8:return False
        reach=max(reach,hi)
        if reach>=1-1e-8:return True
    return False
