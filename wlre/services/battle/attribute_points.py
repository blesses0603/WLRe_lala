"""1262 Lua-based player attribute allocation, with fail-closed validation.

Source: Lua/Logic/Attribute.lua (Send_AddPlayerAttribute);
Lua/UI/Logic/UIAttributesPoint.lua; Lua/Common/Define.lua.
Server response: Lua/Logic/Protocols/Protocols_008.lua.
No client-side mutation of authoritative stats is permitted.
"""
import time

from wlre.network.wire import Packet, ProtocolError, Writer

# Original EAttribute values from Lua/Common/Define.lua.
FIELDS = (("int", 27, "智力 INT"), ("str", 28, "力量 STR"),
          ("con", 29, "體質 CON"), ("agi", 30, "敏捷 AGI"),
          ("wis", 33, "智慧 WIS"))
KEYS = tuple(key for key, _, _ in FIELDS)
KINDS = {kind: key for key, kind, _ in FIELDS}
MAX_BASE_ATTRIBUTE = 602  # MaxLimitAttrPot, before potential bonus.


def defaults():
    return {"pending": False, "acknowledged": False, "uncertain": False,
            "expected": None, "sent_at": None, "status": ""}


def baseline(stats):
    """Only server-synchronized S5-3 stats form a valid spending baseline."""
    if not isinstance(stats, dict):
        raise ProtocolError("角色能力尚未同步")
    result = {}
    for key in (*KEYS, "attribute_potential"):
        value = stats.get(key)
        if type(value) is not int or value < 0:
            raise ProtocolError("角色五項能力與剩餘點數尚未完整同步")
        result[key] = value
    return result


def allocation(stats, increments, expected_baseline):
    """Return (packet, authoritative expected stats) without altering stats."""
    values = baseline(stats)
    if values != expected_baseline:
        raise ProtocolError("角色能力已變更，請重新檢視後再配點")
    if not isinstance(increments, dict) or set(increments) - set(KEYS):
        raise ProtocolError("包含未知能力欄位")
    count = sum(increments.values()) if all(type(v) is int and v >= 0 for v in increments.values()) else -1
    if count <= 0:
        raise ProtocolError("請至少分配 1 點，且不得輸入負數")
    if count > values["attribute_potential"]:
        raise ProtocolError("超過剩餘可分配能力點數")
    # Lua allows bonus potential to extend the effective cap. This stricter
    # base-only limit is intentional until potential-energy calculation is wired.
    for key in KEYS:
        if values[key] + increments.get(key, 0) > MAX_BASE_ATTRIBUTE:
            raise ProtocolError("能力已達基礎上限 602；潛能加成尚待驗證")
    entries = [(kind, increments.get(key, 0)) for key, kind, _ in FIELDS
               if increments.get(key, 0)]
    w = Writer().u8(0).u8(len(entries))
    for kind, amount in entries:
        w.u8(kind).u32(amount)
    expected = {key: values[key] + increments.get(key, 0) for key in KEYS}
    expected["attribute_potential"] = values["attribute_potential"] - count
    return Packet(8, 1, w.build()), expected


def begin(state, expected, now=None):
    info = state.attribute_allocation
    if info["pending"] or info["uncertain"]:
        raise ProtocolError("前次配點結果尚未確認，請勿重複送出；必要時重新登入")
    info.update(pending=True, acknowledged=False, uncertain=False,
                expected=expected, sent_at=time.monotonic() if now is None else now,
                status="配點要求已送出，等待伺服器更新")


def apply_event(state, event):
    info = state.attribute_allocation
    if not info["pending"]:
        return
    if event["type"] == "attribute_allocation_success":
        info["acknowledged"] = True
        info["status"] = "伺服器已回覆成功，等待能力值同步"
    if event["type"] not in ("attribute_allocation_success", "attribute_set", "player_combat_data"):
        return
    current = state.knowledge.get("player", {}).get("stats", {})
    expected = info.get("expected") or {}
    if info["acknowledged"] and all(current.get(k) == v for k, v in expected.items()):
        info.update(pending=False, acknowledged=False, expected=None,
                    sent_at=None, status="配點成功，能力值已同步")


def expire(state, now=None, timeout=12):
    """Unknown results must block repeat spending, not imply server failure."""
    info = state.attribute_allocation
    when = info.get("sent_at")
    if not info["pending"] or when is None:
        return False
    if (time.monotonic() if now is None else now) - when < timeout:
        return False
    info.update(pending=False, uncertain=True,
                status="配點結果無法確認，請重新登入同步後再操作")
    return True
