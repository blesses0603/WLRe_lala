"""Deterministic owned UnityFS fixtures joining extraction to all ten raw tables.

Use installed UnityPy==1.25.4 and lz4==4.4.5 on PYTHONPATH. No network,
game installation, class database, private paths, or candidate generator is used.
Both SerializedFile.save and BundleFile.save are the genuine UnityPy writers.
"""

from pathlib import Path
import base64
import gzip
import hashlib
import importlib.util
import json
import struct
import sys

import UnityPy
import lz4


HERE = Path(__file__).resolve().parent
OUT = HERE / "Fixtures"
TESTS = HERE.parent.parent
SOURCE = TESTS / "Catalogs/RuntimeCandidate/Fixtures/runtime-candidate.json.gz"
SOURCE_SHA256 = "d9e7d7c81118b6643ed8dfc49335188fc92b140d5dc70152d60b7afd9ad02348"
CAB = "CAB-runtime-flow"
EXTERNAL = "archive:/CAB-runtime-flow/CAB-runtime-flow"
TABLES = (
    "Eve", "ItemData_C", "TalkData_C", "TextData_C", "SmithData_C",
    "ScenesData_C", "AdventureData_C", "AdventureLvData_C", "NpcData_C",
    "NpcCareerData_C",
)
DAILY_TABLES = ("DailyTaskData_C", "DailyTaskRewardData_C")
INSTANCE_TABLES = ("DungeonData_C", "CooperateEventData_C")
PACKAGE_VERSION = "1286_2026_10_29_13_42_37_94"


def daily_payloads(*, text_id=10, task_item=123, reward_item=99):
    """Original version-agnostic daily/weekly rows, joined to the ten-table fixture."""
    p = lambda fmt, *values: struct.pack("<" + fmt, *values)
    award = lambda kind, item, value: p("BII", kind, item, value)
    tasks = p("i", 2) + p("BBB", 1, 1, 1) + p("BBB", 1, 2, 2) + p("i", 2)
    tasks += p("HBBIBHHHBBB", 1, 1, 1, text_id, 1, 3, 0, 0, 2, 3, 4)
    tasks += award(10, task_item, 2) + award(1, 0, 5)
    tasks += p("HBBIBHHHBBB", 2, 2, 12, 30, 13, 2, 3, 7, 4, 5, 6)
    tasks += award(11, 20, 1) + award(0, 0, 0)
    rewards = p("i", 2)
    rewards += p("HBII", 1, 1, 10, 1) + award(10, reward_item, 3)
    rewards += award(1, 0, 7) + award(0, 0, 0) * 2
    rewards += p("HBII", 2, 2, 50, 8) + award(11, 20, 4) + award(0, 0, 0) * 3
    return dict(zip(DAILY_TABLES, (tasks, rewards)))


def check_daily(payloads, required):
    # Import only the actual parsers/binder, never another fixture generator or
    # runtime loader. These functions operate on the owned in-memory bytes only.
    root = TESTS.parent.parent
    sys.path.insert(0, str(root))
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        from wlre.services.world.daily_task_catalog import bind_catalog, parse_rewards
        from wlre.services.world.daily_task_1275 import parse_daily_tasks
        from wlre.services.expedition.data import parse_text_data
        from wlre.services.world.itemdata_v1 import parse_itemdata
        return bind_catalog(parse_daily_tasks(payloads[DAILY_TABLES[0]]),
                            parse_rewards(payloads[DAILY_TABLES[1]]),
                            parse_text_data(required["TextData_C"]),
                            parse_itemdata(required["ItemData_C"]))
    finally:
        sys.dont_write_bytecode = previous
        sys.path.pop(0)


def instance_payloads(*, map_id=500, text_id=10, reward_item=123,
                      reward_kind=10, event_id=7, dungeon_event_id=7,
                      duplicate_key=False, duplicate_map=False,
                      duplicate_event=False, empty_award_id=0):
    """Original rows, preserving the ten-table fixture's source bytes and IDs.

    Its existing scene has zero member bounds. Both rows bind successfully but
    correctly remain unsupported for creation; no fixture grants command authority.
    """
    p = lambda fmt, *values: struct.pack("<" + fmt, *values)
    award = lambda kind, item, value: p("BII", kind, item, value)

    def dungeon(identity, kind, variant, npc):
        row = p("HBBHIBBBHHHB", identity, kind, variant, map_id,
                999, 4, 5, 6, 101, 202, npc, 8)
        row += award(reward_kind, reward_item, 2) + award(1, 0, 3)
        row += award(0, empty_award_id, 0) + award(0, 0, 0) * 12
        row += award(11, 99, 4) + p("BBBB", 0x01, 0x80, 0x02, 0x40)
        return row

    rows = [dungeon(1, 1, 1, 0), dungeon(2, 2, 2, dungeon_event_id)]
    if duplicate_key:
        rows.append(rows[0])
    if duplicate_map:
        rows.append(dungeon(3, 1, 1, 0))
    event = p("BIHHBHHHHHHH", event_id, text_id, 303, 404, 5,
              601, 602, 603, 11, 22, 33, 44) + award(11, 20, 6)
    events = [event, event] if duplicate_event else [event]
    return {INSTANCE_TABLES[0]: p("i", len(rows)) + b"".join(rows),
            INSTANCE_TABLES[1]: p("i", len(events)) + b"".join(events)}


def check_instances(payloads, required):
    # Execute the genuine runtime binder and its production parsers on only
    # synthetic in-memory inputs. Do not import another fixture generator.
    root = TESTS.parent.parent
    sys.path.insert(0, str(root))
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        from wlre.services.world.instance_runtime import build_catalog
        inputs = {t: required[t] for t in ("ScenesData_C", "TextData_C", "ItemData_C")}
        return build_catalog({**inputs, **payloads}, "owned-instance-flow", PACKAGE_VERSION)
    finally:
        sys.dont_write_bytecode = previous
        sys.path.pop(0)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def asset_path(table):
    return "Assets/ResourcesBuild/Data/" + table + ".bytes"


def helpers():
    # This existing generator is main-guarded. Import only its structural helpers,
    # never the raw-table generator, which writes fixtures at import time.
    spec = importlib.util.spec_from_file_location(
        "owned_unity_structures", HERE.parent / "UnityTextAssets/generate_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def make_serialized(h, scripts, mappings, *, dependencies=(), externals=()):
    """Build owned objects, then read/rewrite them with the genuine writer.

    scripts maps stable path IDs to (exact name, untouched payload bytes).
    mappings is a sequence, deliberately preserving duplicate container paths.
    """
    container = h.string("runtime-flow") + h.p("ii", 0, len(mappings))
    for path, file_id, path_id in mappings:
        container += h.string(path) + h.p("iiiq", 0, 0, file_id, path_id)
    container += h.p("iiiqI", 0, 0, 0, 0, 0)
    container += h.string("runtime-flow") + h.p("i", len(dependencies))
    container += b"".join(h.string(dependency) for dependency in dependencies)
    container += h.p("iiii", 0, 0, 0, 0)
    objects = [(1, 0, container)] + [
        (path_id, 1, h.string(name) + h.string(payload))
        for path_id, (name, payload) in scripts.items()
    ]
    data = b""
    object_entries = []
    for path_id, type_id, content in objects:
        data = h.align(data, 8)
        object_entries.append((path_id, len(data), len(content), type_id))
        data += content
    data = h.align(data, 8)

    metadata = b"2021.3.45f2\0" + h.p("iBi", 19, 1, 2)
    for class_id, tree in ((142, h.BUNDLE), (49, h.TEXT)):
        metadata += h.p("iBh", class_id, 0, -1) + bytes(16) + h.tree(tree) + h.p("i", 0)
    metadata += h.p("i", len(objects))
    for entry in object_entries:
        metadata = h.align(metadata) + h.p("qqIi", *entry)
    metadata += h.p("ii", 0, len(externals))
    for external in externals:
        metadata += b"\0" + bytes(16) + h.p("i", 0) + external.encode() + b"\0"
    metadata += h.p("i", 0) + b"\0"
    offset = len(h.align(bytes(48) + metadata, 16))
    header = struct.pack(
        ">IIIIB3sIqqq", 0, 0, 22, 0, 0, bytes(3), len(metadata),
        offset + len(data), offset, 0,
    )
    initial = h.align(header + metadata, 16) + data
    file = next(iter(UnityPy.load(initial).files.values()))
    written = file.save()
    assert next(iter(UnityPy.load(written).files.values())).save() == written
    return written


def make_bundle(h, serialized):
    # Bootstrap a valid single-directory UnityFS only to construct the real writer
    # object. The retained bytes come from BundleFile.save, not this envelope.
    info = bytes(16) + struct.pack(
        ">iIIHiqqI", 1, len(serialized), len(serialized), 0,
        1, 0, len(serialized), 4,
    ) + CAB.encode() + b"\0"
    header = b"UnityFS\0" + struct.pack(">I", 8) + b"5.x.x\0" + b"2021.3.45f2\0"
    header += struct.pack(">qIII", 64 + len(info) + len(serialized), len(info), len(info), 0x40)
    initial = h.align(header, 16) + info + serialized
    file = next(iter(UnityPy.load(initial).files.values()))
    written = file.save("lz4hc")
    assert next(iter(UnityPy.load(written).files.values())).save("lz4hc") == written
    return written


def inspect_bundle(data, scripts, mappings, dependencies, externals):
    """Fresh independent-reader pass checks every raw script and container entry."""
    env = UnityPy.load(data)
    bundle = next(iter(env.files.values()))
    assert bundle.signature == "UnityFS" and bundle.version == 8
    assert list(bundle.files) == [CAB]
    serialized = bundle.files[CAB]
    assert serialized.header.version == 22 and serialized._enable_type_tree
    assert [t.class_id for t in serialized.types] == [142, 49]
    assert len(serialized.objects) == 1 + len(scripts)
    parsed = serialized.objects[1].read_typetree()
    actual_mappings = [
        (path, entry["asset"]["m_FileID"], entry["asset"]["m_PathID"])
        for path, entry in parsed["m_Container"]
    ]
    assert actual_mappings == mappings
    assert parsed["m_Dependencies"] == list(dependencies)
    assert [external.path for external in serialized.externals] == list(externals)
    verified_scripts = []
    for path_id, (name, payload) in scripts.items():
        obj = serialized.objects[path_id].read()
        decoded = obj.m_Script.encode("utf-8", "surrogateescape")
        assert obj.m_Name == name and decoded == payload
        verified_scripts.append({
            "path_id": path_id, "name": name,
            "bytes": len(decoded), "sha256": sha256(decoded),
        })
    # Verify UnityPy's ordinary container resolution as well as the lossless tree
    # representation above. External references are checked as a pair below.
    for path, file_id, path_id in mappings:
        if not file_id:
            obj = env.container[path].deref_parse_as_object()
            name, payload = scripts[path_id]
            assert obj.m_Name == name
            assert obj.m_Script.encode("utf-8", "surrogateescape") == payload
    return {
        "bytes": len(data), "sha256": sha256(data),
        "serialized_sha256": sha256(serialized.save()),
        "unityfs_version": bundle.version, "unity_version": serialized.unity_version,
        "serialized_version": serialized.header.version,
        "unityfs_flags": int(bundle.dataflags), "directory": CAB,
        "classes": [t.class_id for t in serialized.types],
        "tree_nodes": [len(list(t.node.traverse())) for t in serialized.types],
        "dependencies": list(dependencies), "externals": list(externals),
        "container": [
            {"path": path, "file_id": file_id, "path_id": path_id}
            for path, file_id, path_id in mappings
        ],
        "scripts": verified_scripts,
    }


def main():
    assert UnityPy.__version__ == "1.25.4"
    assert lz4.__version__ == "4.4.5"
    source_bytes = SOURCE.read_bytes()
    assert sha256(source_bytes) == SOURCE_SHA256, "Raw fixture changed; review before repinning"
    case = json.loads(gzip.decompress(source_bytes))[0]
    assert case["id"] == 0 and case["name"] == "all-ten-duplicate-products"
    assert case["error"] is None and tuple(case["inputs"]) == TABLES
    payloads = {table: base64.b64decode(case["inputs"][table], validate=True) for table in TABLES}
    for table, payload in payloads.items():
        assert sha256(payload) == case["expected"]["hashes"][table]
    # Preserve IDs even when a fixture contains only a subset of the tables.
    path_ids = {table: index + 2 for index, table in enumerate(TABLES)}
    all_scripts = {path_ids[t]: (t, payloads[t]) for t in TABLES}
    all_mappings = [(asset_path(t), 0, path_ids[t]) for t in TABLES]
    h = helpers()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {}
    bundle_bytes = {}

    def retain(name, scripts, mappings, dependencies=(), externals=()):
        serialized = make_serialized(h, scripts, mappings, dependencies=dependencies, externals=externals)
        data = make_bundle(h, serialized)
        observed = inspect_bundle(data, scripts, mappings, dependencies, externals)
        (OUT / name).write_bytes(data)
        files[name] = observed
        bundle_bytes[name] = data

    retain("all-ten.bundle", all_scripts, all_mappings)
    # Valid synthetic one-row layout, deliberately NOT the reviewed production digest.
    skill = bytearray(125); struct.pack_into("<H", skill, 7, 1)
    retain("optional-skill.bundle", {2: ("SkillData_C", struct.pack("<I", 1) + skill)},
           [(asset_path("SkillData_C"), 0, 2)])
    daily_ids = {table: len(TABLES) + 2 + index for index, table in enumerate(DAILY_TABLES)}
    daily_mappings = [(asset_path(t), 0, daily_ids[t]) for t in DAILY_TABLES]
    daily_valid = daily_payloads()
    daily_expected = check_daily(daily_valid, payloads)
    assert [row["name"] for row in daily_expected["tasks"]] == ["任務", "  場景😀  "]
    assert [row["cycle"] for row in daily_expected["tasks"]] == [1, 2]
    assert [row["goal"] for row in daily_expected["tasks"]] == [3, 7]
    daily_scripts = {daily_ids[t]: (t, daily_valid[t]) for t in DAILY_TABLES}
    retain("optional-daily.bundle", daily_scripts, daily_mappings)
    retain("all-ten-daily.bundle", {**all_scripts, **daily_scripts}, all_mappings + daily_mappings)
    daily_invalid = {
        "missing-text": daily_payloads(text_id=999),
        "missing-task-item": daily_payloads(task_item=999),
        "missing-reward-item": daily_payloads(reward_item=999),
        "malformed-task": {**daily_valid, DAILY_TABLES[0]: daily_valid[DAILY_TABLES[0]][:-1]},
        "malformed-reward": {**daily_valid, DAILY_TABLES[1]: daily_valid[DAILY_TABLES[1]][:-1]},
    }
    daily_errors = {}
    for name, invalid in daily_invalid.items():
        try:
            check_daily(invalid, payloads)
        except ValueError as error:
            daily_errors[name] = str(error)
        else:
            raise AssertionError("Invalid synthetic daily fixture was accepted: " + name)
        retain("optional-daily-" + name + ".bundle",
               {daily_ids[t]: (t, invalid[t]) for t in DAILY_TABLES}, daily_mappings)
    retain("optional-daily-missing-task-path.bundle", daily_scripts, daily_mappings[1:])
    retain("optional-daily-missing-reward-path.bundle", daily_scripts, daily_mappings[:1])
    instance_ids = {table: len(TABLES) + len(DAILY_TABLES) + 2 + index
                    for index, table in enumerate(INSTANCE_TABLES)}
    instance_mappings = [(asset_path(t), 0, instance_ids[t]) for t in INSTANCE_TABLES]
    instance_valid = instance_payloads()
    instance_expected = check_instances(instance_valid, payloads)
    assert [row["name"] for row in instance_expected["records"]] == ["  場景😀  ", "任務"]
    assert [row["creation_supported"] for row in instance_expected["records"]] == [False, False]
    assert instance_expected["records"][0]["awards"] == [[1, 10, 123, 2], [2, 1, 0, 3], [16, 11, 99, 4]]
    assert instance_expected["records"][1]["cooperative_event"]["id"] == 7
    instance_scripts = {instance_ids[t]: (t, instance_valid[t]) for t in INSTANCE_TABLES}
    retain("optional-instances.bundle", instance_scripts, instance_mappings)
    retain("all-ten-instances.bundle", {**all_scripts, **instance_scripts}, all_mappings + instance_mappings)
    retain("all-ten-daily-instances.bundle", {**all_scripts, **daily_scripts, **instance_scripts},
           all_mappings + daily_mappings + instance_mappings)
    instance_invalid = {
        "missing-text": instance_payloads(text_id=999),
        "missing-map": instance_payloads(map_id=999),
        "missing-item": instance_payloads(reward_item=999),
        "missing-kind11-item": instance_payloads(reward_kind=11, reward_item=999),
        "missing-event": instance_payloads(dungeon_event_id=8),
        "duplicate-key": instance_payloads(duplicate_key=True),
        "duplicate-main-map": instance_payloads(duplicate_map=True),
        "duplicate-event": instance_payloads(duplicate_event=True),
        "zero-event": instance_payloads(event_id=0),
        "invalid-empty-award": instance_payloads(empty_award_id=123),
        "malformed-dungeon": {**instance_valid, INSTANCE_TABLES[0]: instance_valid[INSTANCE_TABLES[0]][:-1]},
        "malformed-event": {**instance_valid, INSTANCE_TABLES[1]: instance_valid[INSTANCE_TABLES[1]][:-1]},
    }
    instance_errors = {}
    for name, invalid in instance_invalid.items():
        try:
            check_instances(invalid, payloads)
        except ValueError as error:
            instance_errors[name] = str(error)
        else:
            raise AssertionError("Invalid synthetic instance fixture was accepted: " + name)
        retain("optional-instances-" + name + ".bundle",
               {instance_ids[t]: (t, invalid[t]) for t in INSTANCE_TABLES}, instance_mappings)
    retain("optional-instances-missing-dungeon-path.bundle", instance_scripts, instance_mappings[1:])
    retain("optional-instances-missing-event-path.bundle", instance_scripts, instance_mappings[:1])
    retain("split-root.bundle", {path_ids[t]: all_scripts[path_ids[t]] for t in TABLES[:6]},
           all_mappings[:6], dependencies=("split-dependency.bundle",))
    retain("split-dependency.bundle", {path_ids[t]: all_scripts[path_ids[t]] for t in TABLES[6:]},
           all_mappings[6:])
    # Missing only a container entry: the valid underlying TextAsset is retained.
    retain("missing-path.bundle", all_scripts, all_mappings[:-1])
    retain("duplicate-path.bundle", all_scripts, all_mappings + [all_mappings[-1]])
    malformed = dict(all_scripts)
    malformed[path_ids[TABLES[-1]]] = (TABLES[-1], payloads[TABLES[-1]][:-1])
    retain("late-invalid.bundle", malformed, all_mappings)
    retain("unrelated-duplicate.bundle", {path_ids["Eve"]: all_scripts[path_ids["Eve"]]},
           [all_mappings[0]])

    # Both files deliberately reuse the same CAB directory. Correct resolution
    # requires the full bundle/directory tuple, never basename matching.
    external_mappings = all_mappings[:-1] + [(asset_path(TABLES[-1]), 1, path_ids[TABLES[-1]])]
    retain("external-root.bundle", {key: value for key, value in all_scripts.items() if key != path_ids[TABLES[-1]]},
           external_mappings, dependencies=("external-target.bundle",), externals=(EXTERNAL,))
    retain("external-target.bundle", {path_ids[TABLES[-1]]: all_scripts[path_ids[TABLES[-1]]]}, [])
    root = next(iter(UnityPy.load(bundle_bytes["external-root.bundle"]).files.values())).files[CAB]
    target = next(iter(UnityPy.load(bundle_bytes["external-target.bundle"]).files.values())).files[CAB]
    # Bind only this already parsed owned target to the fresh reader's isolated
    # parent file dictionary. UnityPy normally resolves by basename; this check
    # validates the real external PPtr and payload, not the stricter Core policy.
    # Never let the independent reader probe the filesystem or a network source.
    pointer = root.objects[1].read().m_Container[-1][1].asset
    assert pointer.assetsfile.externals[0].path == EXTERNAL
    pointer.assetsfile.parent.files = {CAB: target}
    obj = pointer.deref_parse_as_object()
    assert obj.m_Name == TABLES[-1]
    assert obj.m_Script.encode("utf-8", "surrogateescape") == payloads[TABLES[-1]]

    # Each requested script is below 16 MiB, and the entire SerializedFile is
    # below 64 MiB, but their combined extracted bytes exceed the flow's 32 MiB
    # limit. Raw-table parsing must not run on the deliberately padded records.
    padded_size = (34 * 1024 * 1024 + 9) // 10
    padded = {path_ids[t]: (t, payloads[t].ljust(padded_size, b"\0")) for t in TABLES}
    retain("aggregate-overflow.bundle", padded, all_mappings)

    evidence = {
        "schema": "owned-runtime-flow-v1",
        "ownership": "Original synthetic table fixtures only; no game data, user data, private paths, network, or class database.",
        "writers": ["UnityPy 1.25.4 SerializedFile.save", "UnityPy 1.25.4 BundleFile.save('lz4hc')"],
        "packages": {"UnityPy": UnityPy.__version__, "lz4": lz4.__version__},
        "compression_writer": "lz4 4.4.5 raw block through UnityPy",
        "verification": "Fresh UnityPy reader validates all container entries, duplicate entries, names, raw payloads, and explicit in-memory external target resolution. Both writer round trips are stable.",
        "input": {
            "file": "Catalogs/RuntimeCandidate/Fixtures/runtime-candidate.json.gz",
            "sha256": SOURCE_SHA256, "case_id": case["id"], "case_name": case["name"],
        },
        "tables": [
            {"table": t, "asset_path": asset_path(t), "name": t, "path_id": path_ids[t],
             "bytes": len(payloads[t]), "sha256": sha256(payloads[t])}
            for t in TABLES
        ],
        "daily": {
            "ownership": "Original synthetic daily and weekly rows. Text and item references are independently parsed from the retained all-ten payloads.",
            "tables": [
                {"table": t, "asset_path": asset_path(t), "name": t, "path_id": daily_ids[t],
                 "bytes": len(daily_valid[t]), "sha256": sha256(daily_valid[t])}
                for t in DAILY_TABLES
            ],
            "expected": daily_expected,
            "invalid_python_errors": daily_errors,
        },
        "instances": {
            "ownership": "Original main and cooperative rows. Exact production instance parsers and world.instance_runtime.build_catalog bind unchanged retained scene, text and item bytes. Both rows deliberately have creation_supported=false.",
            "python_sources": ["wlre/services/instance_catalog.py", "wlre/services/world/instance_runtime.py"],
            "tables": [
                {"table": t, "asset_path": asset_path(t), "name": t, "path_id": instance_ids[t],
                 "bytes": len(instance_valid[t]), "sha256": sha256(instance_valid[t])}
                for t in INSTANCE_TABLES
            ],
            "expected": instance_expected,
            "invalid_python_errors": instance_errors,
        },
        "scenarios": {
            "all-ten": {"asset_bundle": {t: "all-ten.bundle" for t in TABLES}},
            "split": {
                "asset_bundle": {t: "split-root.bundle" if t in TABLES[:6] else "split-dependency.bundle" for t in TABLES},
                "bundle_dependencies": {"split-root.bundle": ["split-dependency.bundle"], "split-dependency.bundle": []},
            },
            "missing-path": {"table": TABLES[-1], "change": "Container entry omitted; underlying TextAsset is still present and valid."},
            "duplicate-path": {"table": TABLES[-1], "change": "Two identical exact container mappings point to the same local TextAsset."},
            "late-invalid": {"table": TABLES[-1], "change": "Last raw table byte removed; UnityFS, SerializedFile, container, name, and TextAsset bytes remain valid."},
            "aggregate-overflow": {
                "script_bytes_each": padded_size, "script_bytes_total": padded_size * len(TABLES),
                "change": "All ten original payloads zero-padded past the 32 MiB aggregate extraction budget; each script remains below 16 MiB. Do not parse padded raw-table bytes.",
            },
            "unrelated-duplicate": {"table": "Eve", "change": "Separate bundle supplies a duplicate exact Eve path. Include only in its declared dependency closure, never every acquired bundle."},
            "external": {
                "asset_bundle": {t: "external-root.bundle" for t in TABLES},
                "bundle_dependencies": {"external-root.bundle": ["external-target.bundle"], "external-target.bundle": []},
                "binding": {
                    "source": {"bundle": "external-root.bundle", "directory": CAB},
                    "external_path": EXTERNAL,
                    "target": {"bundle": "external-target.bundle", "directory": CAB},
                },
                "table": TABLES[-1],
            },
        },
        "files": files,
    }
    (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({name: {"bytes": entry["bytes"], "sha256": entry["sha256"]} for name, entry in files.items()}, indent=2))


if __name__ == "__main__":
    main()
