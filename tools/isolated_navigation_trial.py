"""Reversible, isolated official navigation preview experiment; no game transport."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sqlite3
import sys

SEED='resource_catalog_seed.sqlite3'
LEGACY=('navigation_data.zip','graph_origins.json','stage_coordinates.json')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def restore(workspace):
    workspace=Path(workspace).resolve()
    saved=json.loads((workspace/'isolation.json').read_text())
    target=workspace/'source/wlre/resources'/SEED
    held=workspace/'quarantine'/SEED
    if saved['seed_sha256']!=digest(held):raise ValueError('Quarantine checksum mismatch')
    if held.is_symlink() or not target.parent.resolve().is_relative_to(workspace):raise ValueError('Unsafe restore path')
    with held.open('rb') as original, target.open('xb') as output:
        shutil.copyfileobj(original,output)
    return dict(restored=str(target),sha256=digest(target),original_installation_modified=False)


def prepare(destination,snapshot):
    source=Path(__file__).resolve().parents[1];destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Use a new isolated directory')
    if destination.is_relative_to(source):raise ValueError('Isolation must be outside the source checkout')
    seed=source/'wlre/resources'/SEED;before=digest(seed)
    from wlre.storage.full_resource_seed import verify_seed
    verify_seed(seed)
    destination.mkdir(parents=True)
    # Only tracked source/assets, never user data, credentials or .git.
    names=subprocess.check_output(['git','ls-files','-z'],cwd=source).decode().split('\0')
    for name in names:
        rel=Path(name)
        if not name or rel.parts[0] not in ('wlre','tools','android_app'):continue
        original=source/rel
        if original.is_symlink():raise ValueError('Symlink source unsupported')
        target=destination/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(original,target)
    # Include this reviewed working-tree diagnostic before its local commit.
    shutil.copyfile(__file__,destination/'source/tools'/Path(__file__).name)
    copied_seed=destination/'source/wlre/resources'/SEED
    if not copied_seed.exists():
        # Android provisions the pinned seed rather than tracking it in Git.
        shutil.copyfile(seed,copied_seed)
    if digest(copied_seed)!=before:raise ValueError('Copied seed differs from verified original')
    (destination/'quarantine').mkdir()
    shutil.move(destination/'source/wlre/resources'/SEED,destination/'quarantine'/SEED)
    if any((destination/'source/wlre/resources'/name).exists() for name in LEGACY):raise ValueError('Unexpected legacy loose file')
    (destination/'snapshot').mkdir()
    for name in ('current-identity.json','current-stages.json'):
        shutil.copyfile(Path(snapshot)/name,destination/'snapshot'/name)
    record=dict(original_source=str(source),seed_sha256=before,isolated_resources=list(LEGACY),
                source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
                tool_sha256=digest(__file__),snapshot_sha256={n:digest(destination/'snapshot'/n) for n in ('current-identity.json','current-stages.json')})
    (destination/'isolation.json').write_text(json.dumps(record,indent=2))
    if digest(seed)!=before:raise AssertionError('Original seed changed')
    return record


def worker(workspace,download,cache_dir):
    workspace=Path(workspace).resolve();record=json.loads((workspace/'isolation.json').read_text())
    denied=[]
    from urllib.parse import urlsplit
    import socket
    proxies=set()
    if download:
        proxy=os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
        if proxy:
            parsed=urlsplit(proxy)
            for row in socket.getaddrinfo(parsed.hostname,parsed.port or 80,type=socket.SOCK_STREAM):
                proxies.add((row[4][0],row[4][1]))
    def audit(event,args):
        if event in ('open','sqlite3.connect') and args and isinstance(args[0],(str,bytes,os.PathLike)):
            name=os.fsdecode(args[0])
            if name.startswith('file:'):
                from urllib.request import url2pathname
                name=url2pathname(urlsplit(name).path)
            path=Path(name).resolve()
            if (path.name in (SEED,)+LEGACY or path.is_relative_to(Path(record['original_source'])) or path.is_relative_to(workspace/'quarantine')):
                denied.append(dict(event=event,path=str(path)));raise PermissionError('Isolated legacy/source access denied')
        if event=='urllib.Request':
            target=urlsplit(args[0])
            if not download or target.scheme!='https' or target.hostname not in ('wlreftpsrc.chinesegamer.net','wlreftp.chinesegamer.net'):
                raise PermissionError('Only official HTTPS resources allowed')
        if event=='socket.connect':
            address=args[1]
            if not download or not isinstance(address,tuple) or (address[1]!=443 and address[:2] not in proxies):
                raise PermissionError('Trial forbids game/non-HTTPS connections')
    sys.addaudithook(audit)
    from dataclasses import replace
    from unittest.mock import patch
    from wlre.services.world.catalog_identity import OfficialCatalogIdentity,PackageRevision
    from wlre.services.world.navigation_preview import PreviewRepository,NavigationError
    from wlre.services.world.navigation_database import database_path,import_cache,load_cache
    from wlre.services.world.navigation_sync import sync_model
    saved=json.loads((workspace/'snapshot/current-identity.json').read_text())
    identity=OfficialCatalogIdentity(saved['data_ver'],saved['exe_version'],tuple(PackageRevision(**p) for p in saved['packages']))
    stages={int(k):v for k,v in json.loads((workspace/'snapshot/current-stages.json').read_text()).items()}
    root=workspace/'data/official_sync';repo=PreviewRepository(identity,stages,root=root)
    rows=[]
    def rejected(name,action):
        try:action()
        except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:rows.append(dict(case=name,status='rejected',error=str(error)));return
        raise AssertionError('Expected rejection: '+name)
    rejected('cold_start_without_navigation_database',lambda:repo.load(10001))
    for model in (10001,12050):
        if download:
            sync_model(identity,model,root=root)
            method='official_https_bundles_verified_and_extracted'
        else:
            raw=(Path(cache_dir)/f'M{model}-astar-cache.zip').read_bytes()
            import_cache(database_path(root),identity.key,model,raw,{'source':'reviewed historical extracted official cache','fresh_download':False})
            method='historical_extracted_cache_no_download'
        mesh,origin=repo.load(model)
        a=next(iter(sorted(mesh.walkable)));b=next(iter(sorted(mesh.adjacency[a])),a)
        logical=next(k for k,v in stages.items() if v['model_id']==model)
        offset=6992 if stages[logical]['map_height']==65535 else stages[logical]['map_height']
        def packet(node):
            point=mesh.centers[node];return ((point[0]+origin[0])/10,offset-(point[2]+origin[2])/10)
        route=repo.route(logical,packet(a),packet(b))
        if route['can_send_packets'] is not False or route['live_movement_verified'] is not False:raise AssertionError('Movement authority leaked')
        rows.append(dict(case='general_map_preview',model=model,logical_map=logical,method=method,route=route))
    old=load_cache(database_path(root),identity.key,10001)
    if download:
        def transfer_failed(*args,**kwargs):raise OSError('controlled bundle transfer failure')
        rejected('bundle_transfer_failure',lambda:sync_model(identity,10001,root=root,fetch=transfer_failed))
    def unavailable():raise OSError('controlled offline/version observation failure')
    rejected('download_failure',lambda:sync_model(identity,10001,root=root,observe=unavailable))
    if load_cache(database_path(root),identity.key,10001)!=old:raise AssertionError('Failure replaced usable snapshot')
    changed=replace(identity,data_ver='0.0.0')
    rejected('new_version_cannot_use_old_database',lambda:PreviewRepository(changed,stages,root=root).load(10001))
    # A changed version is also rejected before downloading anything.
    snapshot={'data_ver':identity.data_ver,'exe_version':identity.exe_version,'packages':{p.name:p.full_version for p in identity.packages}}
    with patch('wlre.services.official_resource_sync.validate_snapshot',side_effect=lambda x:x):
        rejected('version_change_before_download',lambda:sync_model(changed,10001,root=root,observe=lambda:snapshot))
    db=database_path(root);held=db.with_suffix('.isolated')
    db.rename(held)
    try:rejected('missing_database_after_restart',lambda:PreviewRepository(identity,stages,root=root).load(10001))
    finally:held.rename(db)
    PreviewRepository(identity,stages,root=root).load(10001)
    from types import SimpleNamespace
    from wlre.core.state import State
    from wlre.services.world.movement import Movement
    from wlre.network.wire import ProtocolError
    state=State();state.player=dict(role_id=1,scene=logical)
    start=packet(a);end=packet(b);state.confirm_location(logical,*start,'S3-1')
    movement=Movement(SimpleNamespace(route=lambda *args,**kwargs:route),object())
    try:movement.start(state,*end,0)
    except ProtocolError as error:
        if '僅供預覽' not in str(error):raise
    else:raise AssertionError('Actual preview unexpectedly authorized movement')
    if movement.active or movement.tick(state,1) or state.local_movement:raise AssertionError('Movement output leaked')
    rows.append(dict(case='actual_preview_denied_by_production_movement_guard',status='rejected',packets=0))
    if denied:raise AssertionError('Preview attempted legacy fallback: '+str(denied))
    from wlre.storage.bundled_database import load_bundled_bytes
    for name in LEGACY:
        rejected('legacy_read_control_'+name,lambda name=name:load_bundled_bytes(name))
    # Record the standard seed contract separately: the normal whole-app
    # packaging/startup selfcheck is not relaxed by this preview experiment.
    from wlre.storage.full_resource_seed import verify_seed
    rejected('normal_seed_selfcheck_still_blocks_missing_seed',lambda:verify_seed(workspace/'source/wlre/resources'/SEED))
    return dict(rows=rows,catalog_key=identity.key,legacy_reads_during_preview=0,
                enforcement_controls=denied,can_send_packets=False,live_movement_verified=False,
                full_application_startup_verified=False,fresh_download=download,
                limitations=['Historical supplied identity/stages snapshot; not complete cold boot of all app data.',
                            'Point route preview does not verify actor collision, grounding or live movement.',
                            'No official client or game server session; HTTPS-only network guard.'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--snapshot',type=Path)
    p.add_argument('--download',action='store_true');p.add_argument('--cache-dir',type=Path)
    p.add_argument('--restore',action='store_true');p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args()
    if a.restore:print(json.dumps(restore(a.workspace)));return
    if a.worker:
        report=worker(a.workspace,a.download,a.cache_dir)
        (a.workspace/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='rows'}));return
    if a.snapshot is None or (not a.download and a.cache_dir is None):p.error('Provide --snapshot and either --download or --cache-dir')
    workspace=a.workspace.resolve();record=prepare(workspace,a.snapshot)
    env={**os.environ,'LOCALAPPDATA':str(workspace/'data'),'KIVY_HOME':str(workspace/'kivy'),
         'PYTHONPATH':str(workspace/'source'),'PYTHONDONTWRITEBYTECODE':'1','WLRE_DISABLE_AUTO_CATALOG':'1'}
    command=[sys.executable,'-B',str(workspace/'source/tools/isolated_navigation_trial.py'),'--worker','--workspace',str(workspace)]
    command+=['--download'] if a.download else ['--cache-dir',str(a.cache_dir.resolve())]
    result=subprocess.run(command,cwd=workspace/'source',env=env,timeout=240)
    if digest(Path(record['original_source'])/'wlre/resources'/SEED)!=record['seed_sha256']:raise AssertionError('Original seed changed')
    if result.returncode:raise SystemExit(result.returncode)


if __name__=='__main__':main()
