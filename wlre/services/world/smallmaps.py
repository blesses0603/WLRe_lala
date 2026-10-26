"""SmallMap2D artwork and version-correct UIMain 1024-pixel projection.

All 550 bundled pixels were compared with official 1275 SmallMap2D PNGs and
are identical. The image bytes may be reused, but its 1262 *scene mapping*
must never be used while the verified 1275 runtime is selected.
"""
from wlre.paths import RESOURCE_ROOT
import io
import json
from pathlib import Path
import zipfile
from wlre.services.world.coordinates import Coordinates
from wlre.services.world.map_names import parse_map_id
from wlre.services.world.navigation import NavigationError, finite


class Projection:
    size=1024

    def __init__(self,stage,origin):
        width=6992 if stage['map_width']==65535 else stage['map_width']
        height=6992 if stage['map_height']==65535 else stage['map_height']
        if max(width,height)<=0:raise NavigationError('地圖尺寸無效，無法對齊小地圖。')
        self.rate=100*(self.size-24)/max(width,height)
        self.offset_x=stage['small_offset_x']
        self.offset_y=stage['small_offset_y']
        self.height=stage['offset_y']
        self.origin=origin

    def packet_to_pixel(self,x,y):
        finite(x,y)
        return x*0.01*self.rate+self.offset_x, self.size-((self.height-y)*0.01*self.rate+self.offset_y)

    def pixel_to_packet(self,u,v):
        finite(u,v)
        return (u-self.offset_x)/self.rate*100, self.height-(self.size-v-self.offset_y)/self.rate*100

    def navigation_to_pixel(self,x,z):
        finite(x,z)
        return ((x+self.origin[0])/1000*self.rate+self.offset_x,
                self.size-((z+self.origin[2])/1000*self.rate+self.offset_y))


class SmallMaps:
    def __init__(self,path=None,*,source_revision=None):
        if source_revision is None and path is None:
            from wlre.services.world.runtime_1275 import baseline_revision
            source_revision = baseline_revision()
        self.source_revision = str(source_revision or '1262')
        self.supports_navigation = self.source_revision != '1275'
        self.path=Path(path) if path else RESOURCE_ROOT.joinpath('smallmaps.zip')
        self.coordinates=Coordinates() if self.supports_navigation else None
        with zipfile.ZipFile(self.path) as z:
            self.images=json.loads(z.read('image_index.json'))
            self.archive_entries=set(z.namelist())
        self.entries={int(x['name'].rsplit('_',1)[1]):x.get('entry',x['name']+'.png') for x in self.images}

    def _stage_1275(self, logical_map):
        """Only verified current-game scene geometry, never 1262 lookups."""
        from wlre.services.world.runtime_1275 import active_runtime
        scene = parse_map_id(logical_map)
        runtime = active_runtime()
        stages = getattr(runtime, 'stages', None)
        if (getattr(runtime, 'revision', None) != 1275
                or not isinstance(stages, dict)):
            raise NavigationError('1275 官方場景尺寸尚未經完整校驗。')
        row = stages.get(scene)
        if not isinstance(row, dict) or type(row.get('model_id')) is not int:
            raise NavigationError('1275 官方場景尚未列出此場景的模型資料。')
        model = row['model_id']
        if not 1 <= model <= 65535 or self.entries.get(model) not in self.archive_entries:
            raise NavigationError('此 1275 場景沒有對應的已核對小地圖圖片。')
        width, height = row.get('map_width'), row.get('map_height')
        offset_x, offset_y = row.get('small_offset_x'), row.get('small_offset_y')
        if (any(type(v) is not int for v in (width, height, offset_x, offset_y))
                or not 1 <= width <= 65535 or not 1 <= height <= 65535
                or not 0 <= offset_x <= 1024 or not 0 <= offset_y <= 1024):
            raise NavigationError('1275 官方小地圖投影參數無效。')
        return row, 'M' + str(model).zfill(5)

    def has_image(self, logical_map):
        if self.source_revision == '1275':
            try:
                self._stage_1275(logical_map)
                return True
            except (NavigationError, ValueError, KeyError, TypeError, OSError):
                return False
        try:
            _,model,_=self.coordinates.mapping(logical_map)
        except (NavigationError,ValueError,KeyError):
            return False
        return self.entries.get(parse_map_id(model)) in self.archive_entries

    def image(self,model):
        from PIL import Image
        model=parse_map_id(model)
        if model not in self.entries:return None
        with zipfile.ZipFile(self.path) as z:
            blob=z.read(self.entries[model])
        with Image.open(io.BytesIO(blob)) as im:return im.convert('RGBA')

    def projection(self,logical_map):
        if self.source_revision == '1275':
            stage, model = self._stage_1275(logical_map)
            height = 6992 if stage['map_height'] == 65535 else stage['map_height']
            # Verified 1275 stage geometry, no 1262 navigation graph origin.
            return Projection({**stage, 'offset_y': height}, (0, 0, 0)), model
        stage,scene,origin=self.coordinates.mapping(logical_map)
        return Projection(stage,origin),scene

    def for_model(self,model,logical_map=None):
        if self.source_revision == '1275':
            raise NavigationError('1275 小地圖尚無經新版校驗的導航網格。')
        model=parse_map_id(model)
        if logical_map is not None:
            try:
                p,scene=self.projection(logical_map)
                if parse_map_id(scene)==model:return p
            except NavigationError:pass
        candidates=[(sid,stage) for sid,stage in self.coordinates.stages.items() if stage['model_id']==model]
        candidates.sort(key=lambda x:(int(x[0])!=model,int(x[0])))
        if not candidates:raise NavigationError('此場景沒有可用的小地圖比例資料。')
        return self.projection(candidates[0][0])[0]
