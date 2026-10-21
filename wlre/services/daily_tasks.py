"""Official 1262 daily/weekly task state, without fabricated task definitions.

Lua evidence: Logic/Activity.lua DailyTask, Protocols/Protocols_124.lua.
The game owns task progress and reset timing. This module never invents a
completion, triggers a paid condition, or sends packets without known data.
"""
from wlre.network.wire import Packet, ProtocolError, Reader


TASK_ERRORS = {
    1: "條件未完成", 2: "超過群組數量", 3: "索引超過",
    4: "無任務資料", 5: "設定標記失敗", 6: "檢查給獎失敗",
    7: "給獎失敗", 8: "已領取", 9: "無條件種類",
    10: "不在活動期間", 11: "積分不足", 12: "付費獎勵未授權",
    13: "獎勵資料種類無效", 14: "獎勵資料數量為零",
    15: "背包空間不足",
}


def defaults():
    return {
        "ready": False,
        "groups_ready": False,
        "daily_group": None,
        "weekly_group": None,
        "daily_value": None,
        "weekly_value": None,
        "daily_progress": [],
        "weekly_progress": [],
        "daily_done_mark": 0,
        "daily_reward_mark": 0,
        "daily_event_reward_a": 0,
        "daily_event_reward_b": 0,
        "weekly_done_mark": [],
        "weekly_reward_mark": 0,
        "weekly_event_reward_a": 0,
        "weekly_event_reward_b": 0,
        "daily_event_active": False,
        "weekly_event_active": False,
        "last_notice": "",
    }


def _read_marks(reader):
    result = {
        "daily_value": reader.u8(),
        "weekly_value": reader.u8(),
        "daily_done_mark": reader.u8(),
        "daily_reward_mark": reader.u8(),
        "daily_event_reward_a": reader.u8(),
        "daily_event_reward_b": reader.u8(),
        "weekly_done_mark": [reader.u8(), reader.u8()],
        "weekly_reward_mark": reader.u8(),
        "weekly_event_reward_a": reader.u8(),
        "weekly_event_reward_b": reader.u8(),
    }
    return result


def decode_daily_tasks(packet):
    """S124-1/2/3 are exact layouts; reward bodies are intentionally opaque."""
    if packet.main != 124 or packet.sub not in (1, 2, 3, 4, 5):
        return None
    reader = Reader(packet.payload)
    if packet.sub == 1:
        daily_value = reader.u8()
        weekly_value = reader.u8()
        daily_progress = [reader.u8() for _ in range(8)]
        weekly_progress = [reader.u8() for _ in range(12)]
        marks = {
            "daily_value": daily_value,
            "weekly_value": weekly_value,
            "daily_progress": daily_progress,
            "weekly_progress": weekly_progress,
            "daily_done_mark": reader.u8(),
            "daily_reward_mark": reader.u8(),
            "daily_event_reward_a": reader.u8(),
            "daily_event_reward_b": reader.u8(),
            "weekly_done_mark": [reader.u8(), reader.u8()],
            "weekly_reward_mark": reader.u8(),
            "weekly_event_reward_a": reader.u8(),
            "weekly_event_reward_b": reader.u8(),
            "daily_event_active": bool(reader.u8()),
            "weekly_event_active": bool(reader.u8()),
        }
        reader.end()
        return {"type": "daily_task_snapshot", **marks}
    if packet.sub == 2:
        groups = {"daily_group": reader.u8(), "weekly_group": reader.u8()}
        reader.end()
        return {"type": "daily_task_groups", **groups}
    if packet.sub == 3:
        change = reader.u8()
        if change == 1:
            marks = _read_marks(reader)
            reader.end()
            return {"type": "daily_task_marks", **marks}
        if change == 2:
            count, task_id, cycle = reader.u8(), reader.u8(), reader.u8()
            reader.end()
            if cycle not in (1, 2):
                return {"type": "daily_task_unknown_update", "kind": change}
            return {
                "type": "daily_task_progress",
                "cycle": cycle,
                "task_id": task_id,
                "count": count,
            }
        reader.take(reader.remaining)
        return {"type": "daily_task_unknown_update", "kind": change}
    if packet.sub == 4:
        # Success notifications contain award records and/or event-specific
        # extension data. Do not infer which claim was acknowledged by receipt.
        kind = reader.u8()
        reader.take(reader.remaining)
        return {"type": "daily_task_reward_notice", "kind": kind}
    code = reader.u8()
    reader.end()
    return {"type": "daily_task_error", "code": code,
            "message": TASK_ERRORS.get(code, "未知每日任務錯誤")}


def apply_daily_tasks(state, event):
    data = state.daily_tasks
    kind = event["type"]
    if kind == "daily_task_snapshot":
        data.update({key: value for key, value in event.items() if key != "type"})
        data["ready"] = True
        data["last_notice"] = "每日／每週進度已由伺服器同步"
    elif kind == "daily_task_groups":
        data["daily_group"] = event["daily_group"]
        data["weekly_group"] = event["weekly_group"]
        data["groups_ready"] = True
    elif kind == "daily_task_marks":
        data.update({key: value for key, value in event.items() if key != "type"})
    elif kind == "daily_task_progress" and data["ready"]:
        counts = data["daily_progress"] if event["cycle"] == 1 else data["weekly_progress"]
        task_id = event["task_id"]
        if 1 <= task_id <= len(counts):
            counts[task_id - 1] = event["count"]
    elif kind == "daily_task_error":
        data["last_notice"] = "伺服器回報：" + event["message"]
    elif kind == "daily_task_reward_notice":
        data["last_notice"] = "收到獎勵通知；實際完成狀態以伺服器標記為準"


def _has_flag(flag, task_id):
    """Lua CheckFlag/CheckFlags are one-indexed little-endian bitsets."""
    if type(task_id) is not int or task_id < 1:
        return False
    if isinstance(flag, list):
        if task_id > 8 * len(flag):
            return False
        flag = flag[(task_id - 1) // 8]
    elif task_id > 8:
        return False
    return bool(flag & (1 << ((task_id - 1) % 8)))


def claimable_task_indices(state, catalog, *, verified=False):
    """Read-only planning. Never send unverified C124 or guess a threshold.

    Catalog: iterable of explicit 1262 records with
    index, id, group, cycle (1 day/2 week), and goal.
    The caller must independently verify that the catalog belongs to 1262.
    """
    data = state.get("daily_tasks", {})
    if not verified or not data.get("ready") or not data.get("groups_ready"):
        return ()
    result = []
    for task in catalog:
        if not isinstance(task, dict):
            continue
        cycle, task_id = task.get("cycle"), task.get("id")
        index, group, goal = task.get("index"), task.get("group"), task.get("goal")
        if cycle not in (1, 2) or type(task_id) is not int:
            continue
        if type(index) is not int or not 1 <= index <= 65535:
            continue
        if type(group) is not int or group != data.get("daily_group" if cycle == 1 else "weekly_group"):
            continue
        if type(goal) is not int or goal <= 0:
            continue
        counts = data.get("daily_progress" if cycle == 1 else "weekly_progress", [])
        if not 1 <= task_id <= len(counts):
            continue
        mark = data.get("daily_done_mark" if cycle == 1 else "weekly_done_mark")
        if type(counts[task_id - 1]) is int and counts[task_id - 1] >= goal and not _has_flag(mark, task_id):
            result.append(index)
    return tuple(dict.fromkeys(result))
