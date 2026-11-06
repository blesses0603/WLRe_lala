"""Reviewed official NPC/ItemData inputs for normal attacks and capture.

The NPC layout is pinned to reviewed bytes, not extrapolated to future formats.
"""
from collections.abc import Mapping
from wlre.services.parser_diagnostics import diagnosed
import hashlib
import struct
from wlre.services.world.itemdata_v1 import Reader, parse_itemdata

NPC_SHA256 = 'edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c'


@diagnosed('normal-npc-reviewed-1296')
def parse_npcs(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest()!=NPC_SHA256:
        raise ValueError('NPC 普攻資料格式尚未驗證')
    reader=Reader(raw)
    count=reader.u32()
    if not 0<count<=20000:raise ValueError('Invalid NPC count')
    rows={}
    for _ in range(count):
        name=reader.utf16(allow_empty=True)
        reader.utf16(allow_empty=True)
        fields=reader.take(203)
        ident=struct.unpack_from('<H',fields,1)[0]
        if not ident or str(ident) in rows:raise ValueError('Invalid or duplicate NPC ID')
        rows[str(ident)]={'kind':fields[106],'bodyType':fields[27],
            'normalAttackKind':fields[114],'canCatch':fields[26]==0}
    if reader.pos!=len(raw):raise ValueError('Unexpected NPC trailing bytes')
    return rows


def build_catalog(npc_raw,item_raw):
    from wlre.services.world.itemdata_v1 import ITEMDATA_1296_SHA256
    if hashlib.sha256(item_raw).hexdigest()!=ITEMDATA_1296_SHA256:
        raise ValueError('物品普攻資料格式尚未驗證')
    items=parse_itemdata(item_raw)
    return {'npcs':parse_npcs(npc_raw),
            'items':{str(k):v['kind'] for k,v in items.items()},
            # FightManager.SendAttack: CatchNet uses attributes[1].value - 100.
            'catch_nets':{str(k):v['attributes'][0]['value']-100
                          for k,v in items.items() if v['special']==140}}


def _source():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    return getattr(runtime,'normal_attack_catalog',None)


class CurrentNormalData(Mapping):
    def snapshot(self):
        return _source() or {'items':{},'npcs':{},'catch_nets':{}}
    def __getitem__(self,key):return self.snapshot()[key]
    def __iter__(self):return iter(self.snapshot())
    def __len__(self):return len(self.snapshot())
