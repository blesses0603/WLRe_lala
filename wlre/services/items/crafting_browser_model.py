"""Read-only craft browser: explicit unknowns, own-house evidence and bag counts."""
from wlre.storage.paths import favorites_file,legacy_favorites_file
import json
from pathlib import Path
from wlre.services.items.crafting import RECIPES
from wlre.services.items.catalog import item_display_name as item_name
from wlre.services.items.combat_resources import available


def room_known(state):return bool(state.get('player',{}).get('role_id') and state.get('furniture',{}).get('ready') and state.get('furniture',{}).get('owner')==state.get('player',{}).get('role_id'))

def owned_counts(state,item_id):
    inventory=state.get('inventory',{});bag=None
    if inventory.get('ready') and inventory.get('reliable'):
        bag=sum(v['count'] for v in inventory.get('items',{}).values() if v['item_id']==item_id)
    placed=stored=None
    if room_known(state):
        items=state['furniture'].get('items',{}).values()
        placed=sum(v.get('status')==0 for v in items if v['item_id']==item_id)
        stored=sum(v.get('status')==1 for v in items if v['item_id']==item_id)
    queued=sum(v['count']*RECIPES.get(str(item_id),{}).get('output',1) for v in state.get('crafting',{}).get('queue',{}).values() if v['item_id']==item_id)
    return {'bag':bag,'placed':placed,'stored':stored,'queued':queued}

def tool_status(state,tool_id):
    counts=owned_counts(state,tool_id)
    if counts['placed'] is None:return '待同步'
    if counts['placed']:return '已擺放'
    if counts['stored']:return '保管中'
    if counts['bag']:return '在背包'
    return '未擺放'

def material_rows(state,recipe,count):
    inventory=state.get('inventory',{});ready=inventory.get('ready') and inventory.get('reliable');rows=[]
    for material in recipe['materials']:
        sid=material['item_id'];owned=owned_counts(state,sid)
        usable=sum(available(inventory,index) for index,item in inventory.get('items',{}).items() if item['item_id']==sid and not item.get('locked') and not item.get('enhance_level') and not item.get('magic_spar') and not item.get('beat_level')) if ready else None
        required=material['count']*count
        rows.append({'item_id':sid,'name':item_name(sid),'required':required,'usable':usable,**owned})
    return rows

def availability(state,recipe,count=1):
    if recipe.get('open_used',0)!=0:return '鎖定','此製作物目前尚未開放'
    if recipe['design_id']:return '鎖定','圖紙解鎖狀態尚未同步'
    if recipe['time_id'] or recipe['limit_kind']:return '鎖定','活動／次數條件尚未確認'
    status=tool_status(state,recipe['tool_id'])
    if status!='已擺放':return '設備不足',item_name(recipe['tool_id'])+'：'+status
    materials=material_rows(state,recipe,count)
    if any(v['usable'] is None for v in materials):return '待同步','背包材料尚未同步'
    if any(v['usable']<v['required'] for v in materials):return '缺材料','背包可用材料不足'
    return '可製作','設備與背包材料已確認；仍需伺服器接受'

class Favorites:
    limit=100
    def __init__(self,path=None):
        self.path=Path(path) if path else favorites_file()
        self.ids=[];self.load_error=None
        try:
            from wlre.storage.atomic import file_lock
            if path is None and not self.path.exists() and legacy_favorites_file().exists():
                from wlre.storage.atomic import write_json
                with file_lock(self.path):
                    if not self.path.exists():
                        old=Favorites(legacy_favorites_file())
                        if old.load_error:raise ValueError(old.load_error)
                        write_json(self.path,{'version':1,'items':old.ids})
            if not self.path.exists():raise FileNotFoundError
            with file_lock(self.path):data=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or data.get('version',1)!=1 or not isinstance(data.get('items',[]),list):raise ValueError('收藏格式錯誤')
            values=data.get('items',[])
            self.ids=list(dict.fromkeys(int(v) for v in values if str(v) in RECIPES))[:self.limit]
        except FileNotFoundError:pass
        except (ValueError,TypeError,OSError) as exc:self.load_error=str(exc)
    def toggle(self,item_id):
        if str(item_id) not in RECIPES:raise ValueError('配方不存在')
        from wlre.storage.atomic import file_lock,write_json
        enable=item_id not in self.ids
        with file_lock(self.path):
            current=Favorites(self.path)
            if current.load_error:raise ValueError('收藏檔案無法讀取，未覆寫原檔')
            ids=current.ids
            updated=(ids if item_id in ids else ids+[item_id]) if enable else [v for v in ids if v!=item_id]
            if len(updated)>self.limit:raise ValueError('我的最愛最多 100 項')
            write_json(self.path,{'version':1,'items':updated})
            self.ids=updated
