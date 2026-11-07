"""Execute retained Python validation on synthetic metadata/bytes. No network or game assets.

Manifest inputs exercise the private post-parser seam, not proof of an official fetch.
No tests patch or replace production source fingerprints.
"""
import base64
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.configuration import SUPPORTED_RESOURCES
from wlre.services import official_version
from wlre.services.resource_compatibility import load_supported_resources, baseline_maps, baseline_label
from wlre.services.official_resource_sync import validate_snapshot, compare_snapshot
from wlre.services.official_source import selected_host
from wlre.services.official_manifest_sync import ManifestSpec, VerifiedManifest
from wlre.services.world.catalog_identity import identity_from_verified_manifests
from wlre.services.world.catalog_runtime import official_package_versions, official_catalog_key, select_catalog_runtime
from wlre.services.world.dynamic_bundle_runtime import load_dynamic_runtime_metadata
from wlre.services.world.catalog_adapters import FEATURES

DATA = '1275_2026_10_21_18_27_33_84'
MAIN = '1275_2026_10_21_18_29_38_49'
SNAPSHOT = dict(schema_version=1, origin='official_pc_version_endpoint', data_ver='1.3.21',
                exe_version='1.3.0', packages=dict(DataPackage=DATA, MainPackage=MAIN),
                checked_at_utc='2026-10-24T00:00:00+00:00', assets_ready=False)
REMOTE = dict(resource_path='1.3.21', official_exe_version='1.3.0', newer_official_client=False,
              packages=dict(DataPackage=dict(remote=DATA), MainPackage=dict(remote=MAIN)))
CASES = []
def compact(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))
def emit(kind, name, value, evaluator, raw=None):
    body = compact(value).encode() if raw is None else raw
    try:
        expected = evaluator(value, body)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        expected = None
    CASES.append((kind, name, base64.b64encode(body).decode(), None if expected is None else compact(expected)))
def altered(value, path, new):
    result = deepcopy(value)
    target = result
    for key in path[:-1]: target = target[key]
    target[path[-1]] = new
    return result

def baseline(value, raw):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'baseline.json'; path.write_bytes(raw)
        doc = load_supported_resources(path)
    revisions, manifests = baseline_maps(doc)
    return dict(exe=doc['official_game_exe_version'], label=baseline_label(revisions), revisions=revisions, manifests=manifests)
emit('baseline', 'shipped-policy', SUPPORTED_RESOURCES, baseline)
for name, payload in [('different-revisions', altered(SUPPORTED_RESOURCES, ['packages','MainPackage'], dict(revision='1300',manifest='1300_2027_01_01_00_00_00_00'))),
    ('date-is-identifier', altered(SUPPORTED_RESOURCES, ['packages','MainPackage','manifest'], '1275_2099_99_99_99_99_99_99'))]: emit('baseline', name, payload, baseline)
for field, values in [('schema_version', [True,1.0,0,2,'1',None]), ('official_game_exe_version',['','1.2','1.2.3.4','1.2.3\n','10000.0.0',0,None]), ('packages',[{},None,[]])]:
    for i,v in enumerate(values): emit('baseline',f'{field}-{i}',altered(SUPPORTED_RESOURCES,[field],v),baseline)
for field, values in [('revision',['0','01275','1000000',1275,None,'1275\n']), ('manifest',['1275','1262_2026_10_21_18_27_33_84','1275_2026_10_21_18_27_33_84\n',None])]:
    for i,v in enumerate(values): emit('baseline',f'package-{field}-{i}',altered(SUPPORTED_RESOURCES,['packages','DataPackage',field],v),baseline)
for path in [[],['packages'],['packages','DataPackage']]:
    value=deepcopy(SUPPORTED_RESOURCES); target=value
    for p in path: target=target[p]
    target['unexpected']=True
    emit('baseline',f'extra-{len(path)}',value,baseline)
for i,raw in enumerate([b'\xef\xbb\xbf'+compact(SUPPORTED_RESOURCES).encode(), b'{', b'\xff', b' '*4097, b'[]',b'null']): emit('baseline',f'raw-{i}',None,baseline,raw)

def snapshot(v,raw):
    v=validate_snapshot(json.loads(raw.decode('utf-8')))
    return dict(data=v['data_ver'], exe=v['exe_version'], packages=v['packages'], checked=v['checked_at_utc'], assets_ready=False)
emit('snapshot','valid',SNAPSHOT,snapshot)
for field, values in [('schema_version',[True,1.0,0,'1']),('data_ver',['1.3.21.1','0.00.000.0000','1.2','1.2.3.4.5','10000.0.0','1.2.3\n',True]),('exe_version',['1.2.3.4','1.2.3\n',None]),('checked_at_utc',['','not-a-date','😀'*40,'😀'*41,'x'*41,None]),('assets_ready',[True,0,None,'false']),('origin',['local','OFFICIAL_PC_VERSION_ENDPOINT',None])]:
    for i,v in enumerate(values): emit('snapshot',f'{field}-{i}',altered(SNAPSHOT,[field],v),snapshot)
for name in ('DataPackage','MainPackage'):
    for i,v in enumerate(['1275','0_2026_10_21_18_27_33_84','1275_2026_10_21_18_27_33_84\n',None,[],DATA]): emit('snapshot',f'{name}-{i}',altered(SNAPSHOT,['packages',name],v),snapshot)
for field in SNAPSHOT:
    v=deepcopy(SNAPSHOT); del v[field]; emit('snapshot','missing-'+field,v,snapshot)
v=deepcopy(SNAPSHOT);v['extra']=1;emit('snapshot','extra-key',v,snapshot)
for i,raw in enumerate([b'\xef\xbb\xbf'+compact(SNAPSHOT).encode(),b'{',b'null',b'\xff']): emit('snapshot',f'raw-{i}',None,snapshot,raw)
for name, prior in [('first',None),('same',SNAPSHOT),('data',altered(SNAPSHOT,['data_ver'],'1.4.0')),('exe',altered(SNAPSHOT,['exe_version'],'1.4.0')),('main',altered(SNAPSHOT,['packages','MainPackage'],'1300_2027_01_01_00_00_00_00')),('timestamp',altered(SNAPSHOT,['checked_at_utc'],'old'))]:
    emit('snapshot-compare',name,dict(current=SNAPSHOT,previous=prior),lambda v,_: compare_snapshot(v['current'],v['previous']))

def observation(v,_):
    return dict(key=official_catalog_key(v),packages=official_package_versions(v), decision=asdict(select_catalog_runtime(v)))
emit('observation','normal',REMOTE,observation)
for field,values in [('newer_official_client',[True,1,None,'false']),('resource_path',['','not-a-version','A<&>+"\\\n\x00\x7f中文😀',None]),('official_exe_version',['','future',' 😀 ',1])]:
    for i,v in enumerate(values):emit('observation',f'{field}-{i}',altered(REMOTE,[field],v),observation)
for name in ('DataPackage','MainPackage'):
    for i,v in enumerate(['1275',' ','😀'*100,'x'*101,0,None,'1286_2026_10_29_13_42_37_94']):emit('observation',f'{name}-{i}',altered(REMOTE,['packages',name,'remote'],v),observation)
    v=deepcopy(REMOTE);del v['packages'][name];emit('observation','missing-'+name,v,observation)
for field in REMOTE:
    v=deepcopy(REMOTE);del v[field];emit('observation','missing-'+field,v,observation)
v=deepcopy(REMOTE);v['packages']['Unexpected']={'remote':DATA};emit('observation','extra-package',v,observation)
v=deepcopy(REMOTE);v['other']='okay';v['packages']['DataPackage']['comparison']='same';emit('observation','extra-not-authority',v,observation)
for i,v in enumerate([None,[],True]): emit('observation',f'not-object-{i}',v,observation)

for name,versions in [('same',dict(DataPackage=DATA,MainPackage=MAIN)),('bare',dict(DataPackage='1275',MainPackage='1275')),('missing',{}),('mixed',dict(DataPackage=DATA)),('republished',dict(DataPackage=DATA,MainPackage='1275_2026_10_22_18_29_38_49')),('newer',dict(DataPackage='1296',MainPackage='1296')),('older',dict(DataPackage='1262',MainPackage='1262')),('unrecognized',dict(DataPackage='hello',MainPackage=MAIN))]:
    def compare(v,_):
        def fetch(url):
            if v.get(url) is None: raise ValueError('synthetic missing input')
            return v[url]
        result=official_version.check_official_versions({p:p for p in versions},fetcher=fetch,strict_manifest=True)
        return dict(status=result['status'],comparisons={p:row['comparison'] for p,row in result['packages'].items()})
    emit('compatibility',name,versions,compare)

KEY=official_catalog_key(REMOTE)
METADATA=dict(catalog_key=KEY,sources={f:dict(source_name=f+'-source',schema_id='display-only-schema',sha256='a'*64,record_count=7) for f in FEATURES})
def metadata(v,_):
    # Execute the actual active_official_catalog validation, not a replacement validator.
    with tempfile.TemporaryDirectory() as folder:
        dbpath=Path(folder)/'synthetic.sqlite3'
        with sqlite3.connect(dbpath) as db:
            db.execute('create table official_catalog_active(singleton integer, catalog_key text)')
            db.execute('create table official_catalog_sources(catalog_key text, feature text, source_name text, schema_id text, sha256 text, record_count)')
            db.execute('insert into official_catalog_active values(1,?)',(v['catalog_key'],))
            for feature,row in v['sources'].items():
                # SQLite transports bool as int; reject JSON booleans separately using the pure metadata layer below.
                db.execute('insert into official_catalog_sources values(?,?,?,?,?,?)',(v['catalog_key'],feature,row['source_name'],row['schema_id'],row['sha256'],row['record_count']))
        result=load_dynamic_runtime_metadata(REMOTE,db_path=dbpath)
    return dict(key=result.catalog_key,counts=result.record_counts,digests=result.source_sha256,assets_ready=result.assets_ready,can_send_packets=result.can_send_packets)
emit('metadata','complete',METADATA,metadata)
for f in FEATURES:
    v=deepcopy(METADATA);del v['sources'][f];emit('metadata','missing-'+f,v,metadata)
v=deepcopy(METADATA);v['sources']['unknown']=v['sources']['npc'];emit('metadata','extra-feature',v,metadata)
for field,values in [('record_count',[0,20000,-1,20001,1.5,'1',None]),('sha256',['b'*64,'A'*64,'a'*63,'a'*65,'g'*64,'a'*64+'\n',None]),('source_name',['','x'*120,'x'*121,'😀'*120,'../display-only',None]),('schema_id',['',None,'unknown-schema'])]:
    for i,v in enumerate(values):emit('metadata',f'{field}-{i}',altered(METADATA,['sources','items',field],v),metadata)
for i,v in enumerate(['0'*64,'A'*64,'',None]):emit('metadata',f'wrong-key-{i}',altered(METADATA,['catalog_key'],v),metadata)
v=deepcopy(METADATA);v['assets_ready']=True;v['can_send_packets']=True;emit('metadata','ignored-authority-flags',v,metadata)

def manifests(v,_):
    with tempfile.TemporaryDirectory() as folder:
        items={}
        for name,row in v['manifests'].items():
            body=base64.b64decode(row['bytes']);path=Path(folder)/(name+'.bin');path.write_bytes(body)
            spec=ManifestSpec(row['data_ver'],row['package'],row['package_version'])
            items[name]=VerifiedManifest(spec,dict(header=row['header']),row['crc'],path,True)
        identity=identity_from_verified_manifests(v['snapshot'],items)
        return dict(key=identity.key,identity=identity.as_dict())
MANIFESTS=dict(snapshot=SNAPSHOT,manifests={})
for name,rev in SNAPSHOT['packages'].items():
    body=('synthetic manifest '+name).encode()
    MANIFESTS['manifests'][name]=dict(data_ver=SNAPSHOT['data_ver'],package=name,package_version=rev,
       header=dict(package_name=name,package_version=rev,file_version='2.2.5'),crc=zlib.crc32(body).to_bytes(4,'little').hex(),bytes=base64.b64encode(body).decode())
emit('manifest','normal',MANIFESTS,manifests)
for name in ('DataPackage','MainPackage'):
    for field,val in [('data_ver','1.3.22'),('package','MainPackage' if name=='DataPackage' else 'DataPackage'),('package_version','1275_2026_10_22_18_29_38_49'),('crc','00000000'),('bytes','')]:
        emit('manifest',name+'-'+field,altered(MANIFESTS,['manifests',name,field],val),manifests)
    for field,val in [('package_name','unknown'),('package_version',DATA+'x'),('file_version','2.2.6')]:emit('manifest',name+'-header-'+field,altered(MANIFESTS,['manifests',name,'header',field],val),manifests)
    v=deepcopy(MANIFESTS);del v['manifests'][name];emit('manifest','missing-'+name,v,manifests)
rng=random.Random(1079)
for i in range(24):
    v=deepcopy(MANIFESTS)
    for name in v['manifests']:
        body=rng.randbytes(i*57+1);v['manifests'][name]['bytes']=base64.b64encode(body).decode();v['manifests'][name]['crc']=zlib.crc32(body).to_bytes(4,'little').hex()
    if i%3==0:
        revision=f'{1300+i}_2027_01_01_00_00_00_00';v['snapshot']['packages']['MainPackage']=revision;v['manifests']['MainPackage']['package_version']=revision;v['manifests']['MainPackage']['header']['package_version']=revision
    emit('manifest',f'synthetic-crc-sha-{i}',v,manifests)
for i,v in enumerate([{},dict(WLRE_OFFICIAL_RESOURCE_HOST='wlreftp.chinesegamer.net'),dict(WLRE_OFFICIAL_RESOURCE_HOST='wlreftpsrc.chinesegamer.net'),dict(WLRE_OFFICIAL_RESOURCE_HOST='WLREFTP.chinesegamer.net'),dict(WLRE_OFFICIAL_RESOURCE_HOST='https://wlreftp.chinesegamer.net'),dict(WLRE_OFFICIAL_RESOURCE_HOST='evil.example'),dict(WLRE_OFFICIAL_RESOURCE_HOST=''),dict(WLRE_OFFICIAL_RESOURCE_HOST=None)]):
    emit('origin',str(i),v,lambda v,_: dict(host=selected_host(v)))

lines=['// Generated by generate_resource_vectors.py from retained Python. Synthetic only.', 'namespace Lala.Core.Tests.Resources;', 'public static class PythonResourceVectors', '{', '    public static IEnumerable<object?[]> Cases()', '    {']
for row in CASES:
    lines.append('        yield return new object?[] { '+', '.join('null' if v is None else json.dumps(v,ensure_ascii=True) for v in row)+' };')
lines+=['    }','}']
Path(__file__).with_name('PythonResourceVectors.cs').write_text('\n'.join(lines)+'\n')
print(f'Generated {len(CASES)} synthetic Python resource parity cases')
