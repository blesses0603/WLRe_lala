"""副本與協力的背景作業衝突判定。

enabled / auto_continue 表示設定或待命意圖，不代表當前有互斥封包。
只有尚待伺服器處理或結果不明的作業需要鎖住房間操作；
戰鬥、事件、角色/房間權限由原來的專屬 Guard 繼續驗證。
"""
from collections.abc import Mapping

PENDING = (
    ("maintenance", "pending", "修理／整理等待回覆"),
    ("maintenance", "uncertain", "修理／整理結果不明"),
    ("expedition", "pending", "遠征等待回覆"),
    ("expedition", "uncertain", "遠征結果不明"),
    ("alchemy", "pending", "煉金等待回覆"),
    ("alchemy", "uncertain", "煉金結果不明"),
    ("crafting", "pending", "製作等待回覆"),
    ("crafting", "uncertain", "製作結果不明"),
)


def _data(source, key):
    if isinstance(source, Mapping):
        value = source.get(key)
    else:
        value = getattr(source, key, None)
    return value if isinstance(value, Mapping) else {}


def instance_background_blockers(source):
    """Same conservative pending/uncertain checks for State and UI snapshots."""
    return tuple(message for name, key, message in PENDING
                 if _data(source, name).get(key))
