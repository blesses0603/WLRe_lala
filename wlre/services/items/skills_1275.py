"""Strict SkillData_C reader for the verified 1275 DataCatalog.

Field order follows Lua/Data/SkillData.lua SkillData.New from the official
client.  Parsing alone cannot prove live combat packet compatibility.
"""
from wlre.network.wire import Reader, ProtocolError

# Every stored field is consumed in Lua order.  Unused Spare fields are still
# read, so a changed binary layout cannot be silently accepted.
FIELDS = (
    ("Name", "u32"), ("Sort", "u16"), ("Kind", "u8"),
    ("ID", "u16"), ("ReduceSP", "u16"), ("ReduceHP", "u8"),
    ("Element", "u8"), ("AtkKind", "u16"), ("FightWay", "u8"),
    ("Grade", "u8"), ("FightArea", "u8"), ("VariableA", "u16"),
    ("VariableB", "u16"), ("VariableC", "u8"), ("VariableD", "u16"),
    ("Round", "u8"), ("HitStatus", "u16"), ("InitSkillPot", "u8"),
    ("PreSkillId", "u16"), ("NextSkillId", "u16"),
    *((("Spare" + str(i)), "u16") for i in range(1, 11)),
    ("Desc", "u32"), ("HitID", "u16"), ("Key", "u16"),
    ("TargetKind", "u8"), ("GId", "u16"), ("CornerTag", "u8"),
    ("StatusId", "u16"), ("Duration", "u8"),
    *((("WeaponKind" + str(i)), "u8") for i in range(1, 6)),
    ("LvLimit", "u8"), ("Discolor", "u8"), ("HitBackId", "u16"),
    *((("RangeKind" + str(i)), "u8") for i in range(1, 5)),
    *((("SpareByte" + str(i)), "u8") for i in range(1, 6)),
    ("SoundKey", "u16"),
    *((("SpareWord" + str(i)), "u16") for i in range(2, 6)),
    *((("SpareInt" + str(i)), "u32") for i in range(1, 6)),
    ("KindSort", "u8"), ("MotionKind", "u8"),
    ("SPSkillTextureId", "u8"), ("TargetNPCID", "u16"),
    ("CostItemID", "u16"), ("CostItemCount", "u16"),
)


def parse_skills_1275(raw, texts):
    if not isinstance(raw, bytes) or not isinstance(texts, dict):
        raise ProtocolError("1275 技能資料來源型別錯誤")
    reader = Reader(raw)
    count = reader.i32()
    if not 1 <= count <= 10000:
        raise ProtocolError("1275 技能筆數不正確")
    skills, keys = {}, {}
    for _ in range(count):
        record = {name: getattr(reader, kind)() for name, kind in FIELDS}
        sid = record["ID"]
        if sid == 0 or str(sid) in skills:
            raise ProtocolError("1275 技能 ID 缺漏或重複")
        name = texts.get(record["Name"])
        record["name"] = name if isinstance(name, str) and name.strip() else "技能" + str(sid)
        skills[str(sid)] = record
        key = record["Key"]
        if key:
            # Official Data.OnLoadSkillData assigns skillDataByKey[Key] on
            # every row; later records replace earlier rows for duplicate Key.
            keys[str(key)] = sid
    reader.end()
    return {"source_revision": 1275, "skills": skills, "keys": keys}


def activate_1275_skills(runtime):
    """Update existing shared combat skill dictionaries after source validation.

    This only replaces static skill definitions, not live combat commands or
    actor state.  Historical 1262 tests use an explicit test revision.
    """
    if getattr(runtime, "revision", None) != 1275:
        raise ValueError("拒絕將非1275技能資料當成新版")
    source = getattr(runtime, "skill_catalog", None)
    if not isinstance(source, dict) or source.get("source_revision") != 1275:
        raise ValueError("缺少1275已驗證的技能資料")
    skills, keys = source.get("skills"), source.get("keys")
    if not isinstance(skills, dict) or not skills or not isinstance(keys, dict):
        raise ValueError("1275技能索引格式錯誤")
    for sid, row in skills.items():
        if (not isinstance(sid, str) or not sid.isdecimal()
                or not isinstance(row, dict) or row.get("ID") != int(sid)
                or not isinstance(row.get("name"), str)
                or any(k not in row for k in ("Kind", "KindSort", "TargetKind",
                    "WeaponKind1", "WeaponKind2", "WeaponKind3", "WeaponKind4",
                    "WeaponKind5", "CostItemID", "CostItemCount"))):
            raise ValueError("1275技能資料含不完整的戰鬥欄位")
    known_keys = {str(v["Key"]) for v in skills.values() if v["Key"]}
    if any(str(key) not in known_keys or str(skill_id) not in skills
           for key, skill_id in keys.items()):
        raise ValueError("1275技能按鍵索引與技能表不一致")
    from wlre.services.items.catalog import CAT
    # Mutable dictionaries are intentionally updated in place to retain
    # UI/import references made before the version check window closes.
    CAT["skills"].clear()
    CAT["skills"].update(skills)
    CAT["keys"].clear()
    CAT["keys"].update(keys)
    return len(skills)
