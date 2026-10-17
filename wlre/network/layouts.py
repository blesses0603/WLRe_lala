"""1262 field layouts cross-checked against real login/battle captures."""
from wlre.network.wire import ProtocolError


def role_list(r):
    result = []
    while r.remaining:
        d = {"index": r.u8(), "name": r.unicode8(), "level": r.u8(), "element": r.u8(),
             "max_hp": r.u32(), "hp": r.u32(), "max_sp": r.u32(), "sp": r.u32(),
             "exp": r.i64(), "gold": r.u32(), "sex": r.u8(), "head": r.u8(),
             "palette1": r.u32(), "palette5": r.u32(), "degree": r.u8(), "job": r.u8(),
             "scene": r.u16(), "delete_time": r.read("d"), "locked": bool(r.u8())}
        if d["index"] not in (1, 2): raise ProtocolError("invalid role index")
        bonuses = {"core_hp": r.u32(), "core_sp": r.u32(), "emblem_hp": r.u32(), "emblem_sp": r.u32(),
                   "ride_hp": r.u16(), "star_hp": r.i32(), "star_sp": r.i32(),
                   "relation_hp": r.u32(), "relation_sp": r.u32()}
        d["bonuses"] = bonuses
        d["max_hp"] += sum(v for k, v in bonuses.items() if k.endswith("_hp"))
        d["max_sp"] += sum(v for k, v in bonuses.items() if k.endswith("_sp"))
        result.append(d)
    return result


def world_player(r):
    d = {"role_id": r.u32(), "sex": r.u8(), "scene": r.u16(), "x": r.u16(), "y": r.u16(),
         "face": r.u8(), "head": r.u8(), "body": r.u8(), "palette1": r.u32(), "palette5": r.u32(),
         "header_frame": r.u8(), "second_job_effect": bool(r.u8())}
    d["equips"] = [{"item_id": r.u16(), "design_id": r.u32()} for _ in range(r.u8())]
    d["name"] = r.unicode8()
    # Consume private namecard fields without putting them in event logs.
    r.take(8)  # area + birthday*3 + interests*3 + cardSetting
    r.unicode8()  # personal signature
    d["title_id"] = r.u16()
    return d


def battle_unit(r):
    d = {"war_style": r.u8(), "human_kind": r.u8(), "pid": r.u32(), "npc_index": r.u16(),
         "master_id": r.u32(), "col": r.u8(), "row": r.u8(), "max_hp": r.u32(),
         "max_sp": r.u16(), "hp": r.u32(), "sp": r.u16(), "level": r.u8(), "element": r.u8(),
         "degree": r.u8(), "job": r.u8(), "pet_model_id": r.u16(), "change_body_id": r.u16(),
         "sex": r.u8(), "head": r.u8(), "palette1": r.u32(), "palette5": r.u32(), "name": r.unicode8()}
    if not 1 <= d["col"] <= 4 or not 1 <= d["row"] <= 4:
        raise ProtocolError("invalid battle slot")
    d["equips"] = [{"item_id": r.u16(), "design_id": r.u32()} for _ in range(9)]
    return d
