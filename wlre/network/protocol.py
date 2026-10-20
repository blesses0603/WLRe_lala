"""Layouts transcribed from uploaded Lua; no execution of game Lua."""
from wlre.paths import RESOURCE_ROOT
import json
from wlre.network.wire import Packet, Reader, Writer, ProtocolError
from wlre.network.layouts import role_list, world_player, battle_unit
from wlre.network.live_data import decode_live
from wlre.network.social_protocol import decode_social
from wlre.services.social.chat import decode_chat
from wlre.services.social.guild import decode_guild
from wlre.services.items.recovery import decode_recovery
from wlre.core.activity import decode_activity
from wlre.services.items.crafting import decode_crafting
from wlre.services.items.room_storage import decode_storage
from wlre.network.expedition import decode_expedition
from wlre.network.instances import decode_instances
from wlre.network.npc_dialogue import decode_effect as decode_npc_effect

ENUMS = json.loads(RESOURCE_ROOT.joinpath("enums.json").read_text(encoding="utf-8"))
ATTR_NAMES = {v: k for k, v in ENUMS["EAttribute"].items()}
SKILL_NAMES = {v: k for k, v in ENUMS["ESkill"].items()}


def login(account, password, login_kind, platform, language):
    # ASCII is unambiguous. Lua's native WriteStrToChar encoding for non-ASCII
    # is not yet independently verified; do not silently guess it.
    try:
        account, password = account.encode("ascii"), password.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProtocolError("non-ASCII account/password encoding is unverified") from exc
    if not account or not password:
        raise ProtocolError("empty credentials")
    w = Writer().u8(login_kind).u8(0).u8(platform).u8(language)
    w.u8(len(account)).raw(account).u8(len(password)).raw(password)
    return Packet(63, 7, w.build())


def select_role(index):
    if index not in (1, 2):
        raise ProtocolError("role index must be 1 or 2")
    return Packet(63, 2, Writer().u8(index).build())


def walk(x, y):
    return Packet(6, 1, Writer().u16(x).u16(y).build())


def attack(col, row, target_col, target_row, skill_id):
    if skill_id not in ENUMS["ESkill"].values():
        raise ProtocolError("unknown built-in action ID")
    w = Writer().u8(col).u8(row).u8(target_col).u8(target_row)
    w.u16(skill_id).u8(0).u8(0).u8(0)
    return Packet(50, 1, w.build())


def cast_skill(col,row,target_col,target_row,skill_id):
    return Packet(50,1,Writer().u8(col).u8(row).u8(target_col).u8(target_row).u16(skill_id).u8(0).u8(0).u8(0).build())

def use_battle_item(col,row,target_col,target_row,item_id,index):
    return Packet(50,2,Writer().u8(col).u8(row).u8(target_col).u8(target_row).u16(item_id).u8(0).u8(0).u8(index).u8(0).build())

def use_field_item(item_id,index,npc_index):
    return Packet(23,15,Writer().u8(index).u16(item_id).u32(1).u8(npc_index).build())


def decode(packet, local_role_id=None):
    chat=decode_chat(packet,local_role_id)
    if chat is not None:return chat
    extra=(decode_instances(packet) or decode_storage(packet) or decode_expedition(packet) or decode_recovery(packet)
           or decode_guild(packet) or decode_activity(packet) or decode_crafting(packet))
    if extra is not None:return extra
    r = Reader(packet.payload)
    key = (packet.main, packet.sub)
    event = {"main": packet.main, "sub": packet.sub}
    geometry_changes = {(62,1):'furniture_added', (62,2):'furniture_removed',
                        (62,3):'furniture_moved', (62,4):'furniture_snapshot',
                        (62,64):'house_floor_changed', (65,13):'pillar_changed',
                        (23,74):'bath_exit_obstacle_toggle', (23,76):'seat_exit_obstacle_toggle',
                        (62,70):'bed_exit_obstacle_toggle'}
    if key in geometry_changes:
        minimum = {(62,1):3,(62,2):2,(62,3):15,(62,4):4,(65,13):2,
                   (23,74):5,(23,76):4,(62,70):4}.get(key,0)
        r.take(minimum)
        r.take(r.remaining)
        if key==(23,76):event['clear_activity_role']=int.from_bytes(packet.payload[:4],'little')
        return dict(event,type='navigation_geometry_change',reason=geometry_changes[key],geometry_scope='house',
                    affects_geometry=not(key==(62,4) and len(packet.payload)==4),
                    payload_bytes=len(packet.payload),geometry_rebuilt=False,details_parsed=False)
    if decode_social(packet,r,event):
        r.end()
        return event
    if decode_live(packet,r,event):
        r.end()
        return event
    if key == (20,8):
        r.take(r.remaining)
        return dict(event,type='event_end')
    if packet.main==20 and packet.sub in (7,10,11,13,14,15,16,17):
        r.take(r.remaining)
        return dict(event,type='event_continue_permission',extension_bytes=len(packet.payload))
    if packet.main == 20 and packet.sub in (1,2,3,4,5,6):
        # Invalid effects remain blocking, without disconnecting the client.
        return dict(event,type='event_active',npc_effect=decode_npc_effect(packet.payload),
                    payload_bytes=len(packet.payload))
    if packet.main == 20 and packet.sub in (9,12,46,58,67,70):
        # These branches require event/UI processing in the original client.
        # Mark the server gate; do not auto-advance unsupported dialogue or choices.
        r.take(r.remaining)
        return dict(event, type='event_active')
    if key == (20,74):
        reason_code = r.u8()
        r.take(r.remaining)
        reason = {1:'超出事件互動範圍，請靠近後再嘗試；伺服器未接受直接換圖',
                  2:'伺服器找不到場景',3:'伺服器找不到場景 NPC',
                  4:'伺服器找不到場景 NPC 索引'}.get(reason_code, f'伺服器拒絕事件，原因代碼 {reason_code}')
        return dict(event, type='event_rejected', reason_code=reason_code, reason=reason)
    if key == (1, 23):
        event.update(type="heartbeat_request")
    elif key == (1, 11):
        event.update(type="initial_data_complete")
    elif key == (1, 4):
        # Server echoes account/password/saveAccount. Consume, never log them.
        event.update(type="account_identity", account_id=r.u32())
        for _ in range(3): r.take(r.u8())
    elif key == (63, 7):
        event.update(type="login_result", result=r.u8(), login_kind=r.u8())
    elif key == (63, 1):
        event.update(type="role_list_available", roles=role_list(r), parsed=True)
    elif key == (3, 1):
        event.update(type="world_player", player=world_player(r))
    elif key == (6,2):
        event.update(type='movement_stop',kind=r.u8())
    elif key in ((7,1),(12,1)):
        event.update(type='position_snapshot',role_id=r.u32(),scene=r.u16(),x=r.u16(),y=r.u16(),
                     source=f'S{packet.main}-{packet.sub}',same_stage_handler=packet.main==7)
        event['extension_bytes']=r.remaining
        r.take(r.remaining)
    elif key in ((11, 250), (11, 5)):
        event["type"] = "battle_start" if packet.sub == 250 else "battle_units"
        if packet.sub == 250:
            event.update(stage=r.u8(), fight_number=r.u8())
        event["units"] = [battle_unit(r) for _ in range(r.u8())]
    elif key == (51, 1):
        # 1262 FightManager.RevChangeAttrib reads fixed 7-byte records.
        # A partial record cannot be attributed safely to a battle unit.
        # Discard the entire malformed update rather than applying a
        # possibly incomplete HP/SP snapshot or closing the connection.
        if r.remaining % 7:
            return dict(event, type="battle_attribute_invalid",
                        payload_bytes=r.remaining, complete_records=r.remaining // 7,
                        trailing_bytes=r.remaining % 7)
        values = []
        while r.remaining:
            values.append({"col": r.u8(), "row": r.u8(), "kind": r.u8(), "value": r.u32()})
        event.update(type="battle_attribute_set", values=values)
    elif key == (52, 1):
        event.update(type="round_start", round=r.u16())
    elif key == (11, 1):
        event.update(type="battle_unit_exit", col=r.u8(), row=r.u8())
        # Actual capture has both 2-byte and 3-byte forms. Lua consumes only
        # col/row; keep the observed extra byte without assigning semantics.
        if r.remaining == 1: event["extension_byte"] = r.u8()
    elif key == (8, 4):
        # 1262 Protocols_008.lua: success notification has no payload.
        event.update(type='attribute_allocation_success')
    elif key in ((8, 1), (8, 2), (8, 3)):
        event["type"] = "attribute_set"
        if packet.sub == 1:
            event["entity"] = "self"
        elif packet.sub == 2:
            event.update(human_kind=r.u8(), index=r.u16())
            event["entity"] = f"follow:{event['index']}"
        else:
            event["entity"] = f"player:{r.u32()}"
        kind, sign, value, parameter = r.u8(), r.u8(), r.u32(), r.u32()
        event.update(kind=kind, attribute=ATTR_NAMES.get(kind, str(kind)), sign=sign,
                     value=-value if sign == 2 else value, parameter=parameter)
    elif key == (6, 1):
        event.update(type="walk", role_id=r.i32(), x=r.u16(), y=r.u16(), coordinates="raw")
    elif key == (11, 10):
        event.update(type="war_style", value=r.u8())
    elif key == (11, 12):
        event.update(type="winner", side=r.u8())
    elif key == (11, 0):
        event.update(type="fight_exit", role_id=r.u32(), index=r.u16())
    elif key == (50, 1):
        actions = []
        for _ in range(r.u8()):
            action = {"col": r.u8(), "row": r.u8(), "skill_id": r.u16(),
                      "skill_level": r.u8(), "fight_area": r.u8()}
            action["skill_name"] = SKILL_NAMES.get(action["skill_id"], "unknown")
            targets = []
            for _ in range(r.u8()):
                target = {"col": r.u8(), "row": r.u8(), "attack_result": r.u8(), "hit_action": r.u8()}
                attributes = []
                for _ in range(r.u8()):
                    kind, value, sign = r.u8(), r.u32(), r.u8()
                    attributes.append({"kind": kind, "attribute": ATTR_NAMES.get(kind, str(kind)),
                                       "value": value, "sign": sign})
                target["attributes"] = attributes
                targets.append(target)
            action["targets"] = targets
            actions.append(action)
        event.update(type="attack_result", actions=actions)
    else:
        # Unknown payloads may contain credentials, tokens or personal data.
        return dict(event, type="unimplemented", payload_bytes=len(packet.payload))
    r.end()
    return event


def decode_outbound_movement(packet):
    """Only decode public movement fields; never return login payload data."""
    if (packet.main,packet.sub)!=(6,1):return None
    r=Reader(packet.payload)
    event={'type':'movement_request','main':6,'sub':1,'x':r.u16(),'y':r.u16()}
    r.end()
    return event
