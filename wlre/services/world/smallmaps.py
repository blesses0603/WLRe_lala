"""Original SmallMap2D images and the UIMain.lua 1024-pixel projection."""
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
    def __init__(self,path=None):
        from wlre.services.world.runtime_1275 import baseline_revision, resource_dir
        self.revision=baseline_revision()
        self.coordinates=None if self.revision=='1275' else Coordinates()
        if self.revision=='1275' and path is None:
            self.path=resource_dir()/'smallmaps_1275.zip'
        else:
            self.path=Path(path) if path else RESOURCE_ROOT.joinpath('smallmaps.zip')
        self.images=[]
        self.archive_entries=set()
        self.entries={}
        if not self.path.is_file():
            if self.revision=='1275' and path is None:
                # No old 1262 fallback for uninstalled 1275 map art.
                return
            raise FileNotFoundError(self.path)
        if self.revision=='1275':
            from wlre.services.world.visuals_1275 import verify_private_cache
            verify_private_cache(self.path,'smallmaps')
        with zipfile.ZipFile(self.path) as z:
            self.images=json.loads(z.read('image_index.json'))
            self.archive_entries=set(z.namelist())
        self.entries={int(x['name'].rsplit('_',1)[1]):x.get('entry',x['name']+'.png') for x in self.images}

    def has_image(self, logical_map):
        try:
            if self.revision=='1275':
                from wlre.services.world.runtime_1275 import active_runtime
                stage=active_runtime().stages[parse_map_id(logical_map)]
                model_id=stage['model_id']
                return self.entries.get(model_id) in self.archive_entries
            _,model,_=self.coordinates.mapping(logical_map)
        except (NavigationError,ValueError,KeyError,OSError):
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
        if self.revision=='1275':
            raise NavigationError('1275 小地圖可唯讀檢視，但投影座標／導航原點尚未驗證')
        stage,scene,origin=self.coordinates.mapping(logical_map)
        return Projection(stage,origin),scene

    def for_model(self,model,logical_map=None):
        if self.revision=='1275':
            raise NavigationError('1275 小地圖已更新，但尚未驗證座標投影與導航原點')
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
