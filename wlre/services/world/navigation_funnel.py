"""Bounded planar portal funnel with independent corridor containment checks.

Only flat, same-height triangle corridors are supported. No dynamic clearance
or equivalence to the client's nonplanar unwrapping is claimed.
"""
import math
from wlre.services.world.navigation import NavigationError

EPS=1e-7


def area(a,b,c):
    return (c[0]-a[0])*(b[2]-a[2])-(b[0]-a[0])*(c[2]-a[2])


def covered(a,b,triangles):
    """Clip segment to each convex triangle; union must cover its full length."""
    intervals=[]
    for triangle in triangles:
        orientation=1 if area(*triangle)>0 else -1
        lo,hi=0.,1.
        for p,q in zip(triangle,triangle[1:]+triangle[:1]):
            start=orientation*area(p,q,a);end=orientation*area(p,q,b)
            if start < -EPS and end < -EPS:break
            delta=end-start
            if delta>EPS:lo=max(lo,(-EPS-start)/delta)
            elif delta < -EPS:hi=min(hi,(-EPS-start)/delta)
            if lo>hi+EPS:break
        else:
            if lo<=hi+EPS:intervals.append((max(0.,lo),min(1.,hi)))
    reach=0.
    for lo,hi in sorted(intervals):
        if lo>reach+EPS:return False
        reach=max(reach,hi)
        if reach>=1-EPS:return True
    return False


def smooth_corridor(triangles,start,end):
    if not triangles or len(triangles)>512:raise NavigationError('平滑路徑走廊超出上限。')
    points=[v for t in triangles for v in t]+[start,end]
    if any(len(p)!=3 or any(not math.isfinite(float(v)) for v in p) for p in points):
        raise NavigationError('無效的平滑路徑座標。')
    if max(p[1] for p in points)-min(p[1] for p in points)>EPS:
        raise NavigationError('非水平走廊尚未驗證，不能套用平面平滑。')
    if any(abs(area(*triangle))<=EPS for triangle in triangles):
        raise NavigationError('退化三角形不能用於平滑。')
    if not covered(start,start,[triangles[0]]) or not covered(end,end,[triangles[-1]]):
        raise NavigationError('平滑端點不在指定走廊端面。')
    portals=[(tuple(start),tuple(start))]
    for first,second in zip(triangles,triangles[1:]):
        shared=set(map(tuple,first))&set(map(tuple,second))
        if len(shared)!=2:raise NavigationError('平滑走廊沒有唯一共用邊。')
        a,b=sorted(shared)
        center1=tuple(sum(p[i] for p in first)/3 for i in range(3))
        center2=tuple(sum(p[i] for p in second)/3 for i in range(3))
        # Reverse cross product: the left endpoint has the smaller signed area.
        portals.append((a,b) if area(center1,center2,a)<area(center1,center2,b) else (b,a))
    portals.append((tuple(end),tuple(end)))
    apex=left=right=tuple(start);ai=li=ri=0;result=[apex];i=1;steps=0
    while i<len(portals):
        steps+=1
        if steps>4*len(portals)*len(portals):raise NavigationError('平滑走廊未收斂。')
        nl,nr=portals[i]
        if area(apex,right,nr)<=0:
            if apex==right or area(apex,left,nr)>0:right=nr;ri=i
            else:
                if result[-1]!=left:result.append(left)
                apex=left;ai=li;left=right=apex;li=ri=ai;i=ai+1;continue
        if area(apex,left,nl)>=0:
            if apex==left or area(apex,right,nl)<0:left=nl;li=i
            else:
                if result[-1]!=right:result.append(right)
                apex=right;ai=ri;left=right=apex;li=ri=ai;i=ai+1;continue
        i+=1
    if result[-1]!=tuple(end):result.append(tuple(end))
    if any(not covered(a,b,triangles) for a,b in zip(result,result[1:])):
        raise NavigationError('平滑路徑離開已驗證走廊。')
    return result
