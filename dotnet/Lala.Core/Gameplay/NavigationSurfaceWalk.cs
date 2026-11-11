using Lala.Core.World;

namespace Lala.Core.Gameplay;

/// <summary>Continuous surface and directed-connection validation for rounded XY
/// reports. Every triangle crossing is checked, including overlapping other floors.</summary>
internal static class NavigationSurfaceWalk
{
    internal static double Validate(PreviewNavigationMesh mesh,IReadOnlyList<int> corridor,NavigationPoint from,NavigationPoint to,CancellationToken token)
    {
        const double eps=1e-7;
        var spans=new List<(int Face,double Lo,double Hi)>();var cuts=new SortedSet<double>{0,1};
        double minX=Math.Min(from.X,to.X)-eps,maxX=Math.Max(from.X,to.X)+eps,minZ=Math.Min(from.Z,to.Z)-eps,maxZ=Math.Max(from.Z,to.Z)+eps;
        for(int i=0;i<mesh.Faces.Count;i++)
        {
            token.ThrowIfCancellationRequested();var tri=mesh.Faces[i];double lo=0,hi=1;
            if(Math.Max(tri.A.X,Math.Max(tri.B.X,tri.C.X))<minX||Math.Min(tri.A.X,Math.Min(tri.B.X,tri.C.X))>maxX
                ||Math.Max(tri.A.Z,Math.Max(tri.B.Z,tri.C.Z))<minZ||Math.Min(tri.A.Z,Math.Min(tri.B.Z,tri.C.Z))>maxZ)continue;
            double sign=NavigationFunnel.Area(tri.A,tri.B,tri.C)>0?1:-1;
            foreach(var (a,b) in new[]{(tri.A,tri.B),(tri.B,tri.C),(tri.C,tri.A)})
            {
                double s=sign*NavigationFunnel.Area(a,b,from),e=sign*NavigationFunnel.Area(a,b,to),d=e-s;
                if(s< -eps&&e< -eps){lo=2;break;}
                if(d>eps)lo=Math.Max(lo,(-eps-s)/d);else if(d< -eps)hi=Math.Min(hi,(-eps-s)/d);
            }
            lo=Math.Clamp(lo,0,2);hi=Math.Clamp(hi,0,1);
            if(lo>hi+eps||lo>1)continue;
            spans.Add((i,lo,hi));cuts.Add(Math.Clamp(lo,0,1));cuts.Add(hi);
        }
        var allowed=corridor.ToHashSet();var points=cuts.ToArray();HashSet<int>? reachable=null;double distance=0;double? priorHeight=null;
        double Height(int face,double t)
        {
            var p=new NavigationPoint(from.X+(to.X-from.X)*t,0,from.Z+(to.Z-from.Z)*t);var tri=mesh.Faces[face];
            double area=NavigationMesh.Area(tri.A,tri.B,tri.C),a=NavigationMesh.Area(p,tri.B,tri.C)/area,b=NavigationMesh.Area(tri.A,p,tri.C)/area;
            return a*tri.A.Y+b*tri.B.Y+(1-a-b)*tri.C.Y;
        }
        for(int i=1;i<points.Length;i++)
        {
            token.ThrowIfCancellationRequested();double lo=points[i-1],hi=points[i];if(hi-lo<1e-9)continue;
            double mid=(lo+hi)/2;var hits=spans.Where(s=>s.Lo<=mid&&s.Hi>=mid).Select(s=>s.Face).ToArray();
            if(hits.Length==0)throw new NavigationException("移動步伐離開導航網格。");
            var heights=hits.Select(f=>Height(f,mid)).ToArray();
            bool Ambiguous(double t){var values=hits.Select(f=>Height(f,t)).ToArray();return values.Max()-values.Min()>1e-4;}
            if(heights.Max()-heights.Min()>1e-4||Ambiguous(lo)||Ambiguous(hi))throw new NavigationException("此路段包含重疊樓層，無法僅由平面座標確定路線。");
            var candidates=hits.Where(f=>allowed.Contains(f)&&mesh.Walkable.Contains(f)).ToHashSet();
            if(candidates.Count==0)throw new NavigationException("整數移動步伐離開可行走走廊。");
            if(reachable is not null)
            {
                // Allow zero-length face crossings at a shared vertex only along
                // actual directed mesh connections touching this exact boundary.
                var boundary=spans.Where(s=>s.Lo<=lo+eps&&s.Hi>=lo-eps&&allowed.Contains(s.Face)).Select(s=>s.Face).ToHashSet();
                var queue=new Queue<int>(reachable);var visited=new HashSet<int>(reachable);
                while(queue.TryDequeue(out int f))foreach(int n in mesh.Adjacency[f].Keys)
                    if(boundary.Contains(n)&&visited.Add(n))queue.Enqueue(n);
                candidates.IntersectWith(visited);
                if(candidates.Count==0)throw new NavigationException("此移動步伐跨越未連接或方向禁止的導航面。");
            }
            int chosen=candidates.First();double h0=Height(chosen,lo),h1=Height(chosen,hi);
            if(priorHeight is {} last&&Math.Abs(last-h0)>1e-3)throw new NavigationException("導航面高度不連續，不能直接跨越。");
            distance+=NavigationPoint.Distance(new(from.X+(to.X-from.X)*lo,h0,from.Z+(to.Z-from.Z)*lo),new(from.X+(to.X-from.X)*hi,h1,from.Z+(to.Z-from.Z)*hi));
            priorHeight=h1;reachable=candidates;
        }
        if(reachable is null)throw new NavigationException("無法確認移動面。");
        return distance;
    }
}
