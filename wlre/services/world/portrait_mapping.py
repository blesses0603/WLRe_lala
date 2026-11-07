"""Reviewed 1296 official portrait identifiers, independent of equipment icons.

UIPlayerInfo / Function.GetCharacterId select sex + headStyle. FollowNpcData
uses modeling > 0, otherwise NPC ID; NpcData then selects iconId/modelKind.
Only the independently reviewed NPC payload is accepted. No Lua executes.
"""
import hashlib
import struct
from wlre.services.world.itemdata_v1 import Reader
from wlre.services.parser_diagnostics import diagnosed
from wlre.services.world.normal_attack_catalog import NPC_SHA256

# Define.lua CHARACTER_DATAS, protected by the existing reviewed source digest.
CHARACTERS = {(2, 0): 1, (2, 1): 2, (1, 0): 3, (4, 2): 4, (4, 1): 5,
              (3, 0): 6, (3, 1): 7, (4, 4): 8, (4, 5): 9, (4, 0): 10,
              (4, 6): 11, (3, 2): 12, (3, 3): 13, (4, 7): 14, (4, 3): 15}
DATA_VERSION = '1296_2026_11_04_13_34_19_13'
MAIN_VERSION = '1296_2026_11_04_13_36_07_72'


@diagnosed('portrait-npc-reviewed-1296')
def parse_npc_portraits(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != NPC_SHA256:
        raise ValueError('夥伴頭像資料格式尚未驗證')
    reader = Reader(raw)
    count = reader.u32()
    if not 0 < count <= 20000:
        raise ValueError('夥伴頭像筆數超過上限')
    result = {}
    for _ in range(count):
        reader.utf16(allow_empty=True)
        reader.utf16(allow_empty=True)
        fields = reader.take(203)
        ident = struct.unpack_from('<H', fields, 1)[0]
        model_kind = fields[5]
        icon = struct.unpack_from('<H', fields, 6)[0]
        palettes = struct.unpack_from('<4I', fields, 8)
        if not ident or ident in result or any(p > 999999999 for p in palettes):
            raise ValueError('夥伴頭像識別或配色資料不符')
        if icon:
            result[ident] = {'icon': f'{icon:04d}_{model_kind}' if model_kind else str(icon),
                             'palettes': {i + 1: value for i, value in enumerate(palettes)}}
    if reader.pos != len(raw):
        raise ValueError('夥伴頭像資料尾端不符')
    return result
