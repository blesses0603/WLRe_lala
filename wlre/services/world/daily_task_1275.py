"""依照官方 Lua DailyTaskData / AwardData 嚴格解析 1275，僅供離線驗證。"""
import struct


class Reader:
    def __init__(self, data):
        if not isinstance(data, bytes):
            raise ValueError("DailyTaskData_C 須為 bytes")
        self.data = data
        self.pos = 0

    def read(self, fmt):
        size = struct.calcsize("<" + fmt)
        if self.pos + size > len(self.data):
            raise ValueError("DailyTaskData_C 資料截斷")
        value = struct.unpack_from("<" + fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def u8(self):
        return self.read("B")

    def u16(self):
        return self.read("H")

    def u32(self):
        return self.read("I")

    def i32(self):
        return self.read("i")


def parse_daily_tasks(data):
    """Count/group integrity only; never send daily-task completion packets."""
    r = Reader(data)
    group_count = r.i32()
    if not 0 <= group_count <= 1000:
        raise ValueError("每日任務群組數量不合理")
    groups, group_ids = [], set()
    for _ in range(group_count):
        row = {"mission_kind": r.u8(), "refresh_kind": r.u8(), "group": r.u8()}
        if row["refresh_kind"] not in (1, 2) or row["group"] in group_ids:
            raise ValueError("每日任務群組重複或更新週期不合法")
        groups.append(row)
        group_ids.add(row["group"])
    task_count = r.i32()
    if not 0 <= task_count <= 50000:
        raise ValueError("每日任務筆數不合理")
    rows, keys = [], set()
    for _ in range(task_count):
        row = {"index": r.u16(), "group": r.u8(), "id": r.u8(),
               "mission_name_text_id": r.u32(), "condition_kind": r.u8(),
               "condition_params": [r.u16() for _ in range(3)],
               "function_kind": r.u8(), "function_arg1": r.u8(), "function_arg2": r.u8(),
               "awards": [{"kind": r.u8(), "id": r.u32(), "value": r.u32()} for _ in range(2)]}
        key = (row["group"], row["index"])
        if key in keys:
            raise ValueError("每日任務索引重複")
        keys.add(key)
        rows.append(row)
    if r.pos != len(data):
        raise ValueError("每日任務表有未解析資料")
    return {"group_count": len(groups), "task_count": len(rows),
            "groups": groups, "tasks": rows,
            "missing_group_ids": sorted({row["group"] for row in rows} - group_ids)}
