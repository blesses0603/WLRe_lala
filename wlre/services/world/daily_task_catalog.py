"""DailyTask/DailyTaskReward schemas from the official Lua, version agnostic."""
from wlre.services.world.daily_task_1275 import Reader, parse_daily_tasks

TABLES=('DailyTaskData_C','DailyTaskRewardData_C')


def parse_rewards(raw):
    r=Reader(raw);count=r.i32()
    if not 0<count<=1000:raise ValueError('活躍寶箱筆數無效')
    rows=[];ids=set();marks=set()
    for _ in range(count):
        row=dict(id=r.u16(),kind=r.u8(),value=r.u32(),mark=r.u32())
        row['awards']=[dict(kind=r.u8(),id=r.u32(),value=r.u32()) for _ in range(4)]
        key=(row['kind'],row['mark'])
        if (not row['id'] or (row['kind'],row['id']) in ids or row['kind'] not in (1,2,3,4)
                or not 1<=row['mark']<=8 or key in marks or not row['value']):
            raise ValueError('活躍寶箱索引或標記無效／重複')
        ids.add((row['kind'],row['id']));marks.add(key);rows.append(row)
    if r.pos!=len(raw):raise ValueError('活躍寶箱長度不符')
    return rows


def goal(row):
    kind=row['condition_kind'];p=row['condition_params']
    if kind in (3,5):return 1
    if kind in (1,2,4,7,8,12,14,16,18,19,20):return p[0]
    if kind in (6,9,10,11,15,17):return p[1]
    if kind==13:
        if p[0] in (1,6):return p[1]
        if p[0] in (2,3,4,5):return p[2]
    return None


def bind_catalog(tasks,rewards,texts,items):
    groups={g['group']:g for g in tasks['groups']}
    rows=[];indices=set();slots=set()
    for raw in tasks['tasks']:
        group=groups.get(raw['group'])
        if group is None:raise ValueError('任務缺少同版群組')
        if group['mission_kind']!=1:continue  # Shiny Pass is a different protocol.
        cycle=group['refresh_kind'];key=(raw['group'],raw['id'])
        if (not raw['index'] or raw['index'] in indices or key in slots
                or not 1<=raw['id']<=(8 if cycle==1 else 12)):
            raise ValueError('任務索引或進度格位無效／重複')
        name=texts.get(raw['mission_name_text_id'])
        if not isinstance(name,str) or not name.strip():raise ValueError('任務缺少同版名稱')
        for award in raw['awards']:
            if award['kind'] in (10,11) and award['id'] not in items:
                raise ValueError('任務獎勵缺少同版物品')
        rows.append({**raw,'name':name,'cycle':cycle,'goal':goal(raw)})
        indices.add(raw['index']);slots.add(key)
    if not rows:raise ValueError('沒有每日／每週任務')
    for row in rewards:
        for award in row['awards']:
            if award['kind'] in (10,11) and award['id'] not in items:
                raise ValueError('寶箱獎勵缺少同版物品')
    return dict(tasks=rows,rewards=rewards)


def load_verified_catalog(manifest,bundle_root,loader,root,identity,texts,items):
    """Verify current manifest entries, persist and reparse the exact SQLite rows."""
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.world.catalog_adapters import SourceContract
    from wlre.services.world.official_catalog_pipeline import AssetBinding
    from wlre.services.world.unity_textasset import extract_textasset
    from wlre.services.world.resource_database import record_inventory,read_catalog_tables
    from pathlib import Path
    payloads={}
    for table in TABLES:
        asset='Assets/ResourcesBuild/Data/'+table+'.bytes'
        plan=build_update_plan(manifest,asset_paths=(asset,),cache_root=bundle_root)
        if not plan.entries or any(r.action!='cached' for r in plan.entries):
            raise ValueError('每日任務 Bundle 尚未同步')
        paths=tuple(r.spec.cache_path(bundle_root) for r in plan.entries)
        if any(not _verified_file(p,r.spec) for p,r in zip(paths,plan.entries)):
            raise ValueError('每日任務 Bundle 校驗失敗')
        binding=AssetBinding(asset,SourceContract('scenes',table,'stage-new-76-v1',
                            '0'*64,'DataPackage',manifest.spec.package_version))
        payloads['tables/'+table+'.bytes']=extract_textasset(binding,paths,loader=loader)
    # Reject invalid data before writing the current identity to SQLite.
    bind_catalog(parse_daily_tasks(payloads['tables/DailyTaskData_C.bytes']),
                 parse_rewards(payloads['tables/DailyTaskRewardData_C.bytes']),texts,items)
    database=Path(root)/'derived_catalogs'/'resource_inventory.sqlite3'
    database.parent.mkdir(parents=True,exist_ok=True)
    record_inventory(database,identity.key,payloads,identity=identity)
    parsed=read_catalog_tables(database,identity.key,('daily_tasks','daily_rewards'))
    result=bind_catalog(parsed['daily_tasks'],parsed['daily_rewards'],texts,items)
    import hashlib
    result['sources']={name:hashlib.sha256(raw).hexdigest() for name,raw in payloads.items()}
    return result
