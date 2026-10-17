"""Offline geometry queries in serialized vertices_b_int3 coordinates.

Connectivity is reconstructed from identical 3-D triangle edges. Original graph
flags, off-mesh links, runtime cuts and network-coordinate conversion are not
applied. This module never sends movement commands.
"""
from wlre.paths import RESOURCE_ROOT
import heapq
import json
import math
from pathlib import Path
import zipfile
from wlre.services.world.map_names import model_label, parse_map_id


class NavigationError(ValueError):
    pass


def finite(*values):
    if not all(math.isfinite(float(x)) for x in values):
        raise NavigationError('座標必須是有限數值。')


class Repository:
    def __init__(self, path=None):
        self.path = Path(path) if path else RESOURCE_ROOT.joinpath('navigation_data.zip')
        with zipfile.ZipFile(self.path) as z:
            self.catalog = json.loads(z.read('catalog.json'))
        for row in self.catalog:row['display_name']=model_label(row['id'])
        self.scenes = {r['id']: r for r in self.catalog}

    @staticmethod
    def normalize(scene):
        s = str(scene).strip().upper()
        if '(' in s or '（' in s:s=str(parse_map_id(s))
        return 'M' + s.zfill(5) if s.isdigit() else s

    def load(self, scene):
        sid = self.normalize(scene)
        row = self.scenes.get(sid)
        if not row:
            raise NavigationError('找不到場景資源：' + sid)
        if not row['entry']:
            raise NavigationError(sid + ' 尚未識別到同類 A* 導航圖。')
        with zipfile.ZipFile(self.path) as z:
            mesh = Mesh(json.loads(z.read(row['entry'])))
        mesh.scene_id = sid
        return mesh


class Mesh:
    def __init__(self, data):
        self.scene_id = None
        self.faces = []
        self.metadata = []
        self.centers = []
        self.adjacency = {}
        edges = {}
        for tile in data['tiles']:
            vertices = tile['vertices_b_int3']
            for k, indices in enumerate(tile['triangles']):
                tri = tuple(tuple(vertices[i]) for i in indices)
                if len(tri) != 3 or any(len(v) != 3 for v in tri):
                    raise NavigationError('無效的三角形資料。')
                for v in tri:
                    finite(*v)
                if abs(self.area(*tri)) < 1e-9:
                    continue  # Vertical/degenerate projection cannot support XZ queries.
                face = len(self.faces)
                self.faces.append(tri)
                self.metadata.append(tile.get('node_metadata', [None]*len(tile['triangles']))[k])
                self.centers.append(tuple(sum(v[c] for v in tri)/3 for c in range(3)))
                self.adjacency[face] = {}
                for a, b in ((tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])):
                    edge = tuple(sorted((a,b)))
                    edges.setdefault(edge, []).append(face)
        self.nonmanifold_edges = 0
        for edge, faces in edges.items():
            if len(faces) == 2:
                a,b = faces
                midpoint = tuple((edge[0][c]+edge[1][c])/2 for c in range(3))
                self.adjacency[a][b] = midpoint
                self.adjacency[b][a] = midpoint
            elif len(faces)>2:
                self.nonmanifold_edges += 1  # Ambiguous edges are not joined.

    @staticmethod
    def area(a,b,c):
        return (b[0]-a[0])*(c[2]-a[2])-(b[2]-a[2])*(c[0]-a[0])

    def locate(self, x, z, height=None):
        finite(x,z, *([] if height is None else [height]))
        p = (float(x),0,float(z))
        hits = []
        for face, tri in enumerate(self.faces):
            a,b,c = tri
            total = self.area(a,b,c)
            u,v = self.area(p,b,c)/total, self.area(a,p,c)/total
            w = 1-u-v
            if min(u,v,w) >= -1e-8:
                y = u*a[1]+v*b[1]+w*c[1]
                hits.append((face,(p[0],y,p[2])))
        if not hits:
            raise NavigationError('指定位置在導航面之外；不會自動吸附到邊界。')
        if height is not None:
            return min(hits,key=lambda h:abs(h[1][1]-height))
        if max(h[1][1] for h in hits)-min(h[1][1] for h in hits)>1e-5:
            raise NavigationError('此 X/Z 有多個高度的導航面，請指定高度。')
        return hits[0]

    def route(self, start, end, start_height=None, end_height=None):
        source,sp = self.locate(*start,height=start_height)
        target,tp = self.locate(*end,height=end_height)
        frontier = [(math.dist(self.centers[source],self.centers[target]),0,source)]
        costs, parent = {source:0}, {}
        while frontier:
            _, cost, current = heapq.heappop(frontier)
            if cost != costs.get(current):
                continue
            if current == target:
                break
            for neighbor in self.adjacency[current]:
                candidate = cost + math.dist(self.centers[current],self.centers[neighbor])
                if candidate < costs.get(neighbor,float('inf')):
                    costs[neighbor] = candidate
                    parent[neighbor] = current
                    h = math.dist(self.centers[neighbor],self.centers[target])
                    heapq.heappush(frontier,(candidate+h,candidate,neighbor))
        else:
            raise NavigationError('兩點之間沒有可由共享邊連通的離線幾何路徑。')
        faces = [target]
        while faces[-1] != source:
            faces.append(parent[faces[-1]])
        faces.reverse()
        points = [sp]
        for a,b in zip(faces,faces[1:]):
            point = self.adjacency[a][b]
            if point != points[-1]:points.append(point)
        if tp != points[-1]:points.append(tp)
        return {'scene_resource':self.scene_id,'coordinate_space':'navcache_vertices_b_int3',
                'network_coordinates_verified':False,'connectivity':'reconstructed_shared_edges',
                'runtime_obstacles_applied':False,'original_node_flags_applied':False,
                'points':points,'faces':faces,'length':sum(math.dist(a,b) for a,b in zip(points,points[1:]))}
