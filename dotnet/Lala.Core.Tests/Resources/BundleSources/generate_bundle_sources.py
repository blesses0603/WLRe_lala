#!/usr/bin/env python3
"""Retained offline parity oracle. No network; all openers serve synthetic bytes.
Source digests normalize CRLF only (not arbitrary whitespace or bare CR).
"""
import argparse
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tools.resources.lala_manifest_full_index import parse_manifest, bundle_fingerprint, asset_fingerprint
from wlre.services.official_manifest_sync import ManifestSpec, fetch_official_manifest
from wlre.services.official_incremental_sync import build_update_plan
from wlre.services.official_bundle_download import fetch_bundle, spec_from_manifest
from wlre.services.world.bundle_runtime_1275 import _REQUIRED_TABLES, _ASSET_ROOT

SOURCES = ('tools/resources/lala_manifest_full_index.py',
    'wlre/services/official_manifest_sync.py', 'wlre/services/official_incremental_sync.py',
    'wlre/services/official_bundle_download.py', 'wlre/services/world/dynamic_bundle_runtime.py',
    'wlre/services/world/bundle_runtime_1275.py')
VERSION = '1275_2026_01_02_03_04_05_06'
DATA_VER = '1.3.21'

def sha(data): return hashlib.sha256(data).hexdigest()
def crc(data): return (zlib.crc32(data) & 0xffffffff).to_bytes(4, 'little').hex()
def b64(data): return base64.b64encode(data).decode('ascii')
def md5(data): return hashlib.md5(data, usedforsecurity=False).hexdigest()
def s(value):
    raw = value.encode('utf-8')
    return struct.pack('<H', len(raw)) + raw

def manifest(model):
    h = model['header']
    data = struct.pack('<I', 0x00594f4f) + s('2.2.5')
    data += bytes(h[k] for k in ('enable_addressable', 'location_to_lower', 'include_asset_guid'))
    data += struct.pack('<ii', h['output_name_style'], h['build_bundle_type'])
    data += b''.join(s(h[k]) for k in ('build_pipeline', 'package_name', 'package_version', 'package_note'))
    data += struct.pack('<i', len(model['assets']))
    for a in model['assets']:
        data += b''.join(s(a[k]) for k in ('address', 'path', 'guid'))
        data += struct.pack('<H',len(a['tags'])) + b''.join(map(s,a['tags'])) + struct.pack('<i',a['bundle_id'])
    data += struct.pack('<i', len(model['bundles']))
    for b in model['bundles']:
        data += s(b['name']) + struct.pack('<I',b['unity_crc']) + s(b['file_hash']) + s(b['file_crc'])
        data += struct.pack('<qB',b['file_size'],b['encrypted'])
        data += struct.pack('<H',len(b['tags'])) + b''.join(map(s,b['tags']))
        data += struct.pack('<H',len(b['dependency_ids'])) + b''.join(struct.pack('<i',v) for v in b['dependency_ids'])
    return data

class Response(io.BytesIO):
    status = 200
    def __init__(self, body, url):
        super().__init__(body)
        self.url = url
        self.headers = {'Content-Length': str(len(body))}
    def geturl(self): return self.url

def opener_for(mapping):
    def opener(request, **kwargs):
        url = request.full_url
        if url not in mapping: raise AssertionError('Unexpected request: ' + url)
        return Response(mapping[url], url)
    return opener

def verified(raw, package, root):
    spec = ManifestSpec(DATA_VER, package, VERSION)
    return fetch_official_manifest(spec, cache_root=root,
        opener=opener_for({spec.url('hash'):crc(raw).encode(),spec.url('bytes'):raw}))

def model(package):
    payloads = {name: ('synthetic/' + package + '/' + name + '/資料\x00').encode()
                for name in ('root-a.bundle','root-b.bundle','dep-a.bundle','dep-b.bundle','unrelated.bundle')}
    names = list(payloads)
    bundles = [dict(name=n,unity_crc=0xfedcba98+i,file_hash=md5(payloads[n]),file_crc=crc(payloads[n]),
        file_size=len(payloads[n]),encrypted=bool(i%2),tags=['合成',str(i)],dependency_ids=d)
        for i,(n,d) in enumerate(zip(names,([3,2,2,0],[2],[4,0],[2],[])))]
    tables = list(_REQUIRED_TABLES) if package == 'DataPackage' else ['SyntheticImage']
    assets = [dict(address='位址'+str(i),path=_ASSET_ROOT+t+'.bytes',guid='guid-'+str(i),
                   tags=['標籤',''],bundle_id=i%2) for i,t in enumerate(tables)]
    header = dict(enable_addressable=True,location_to_lower=False,include_asset_guid=True,
        output_name_style=1,build_bundle_type=2,build_pipeline='ScriptableBuildPipeline',
        package_name=package,package_version=VERSION,package_note='合成資料 🐾')
    return dict(header=header,assets=assets,bundles=bundles), payloads

def case(cid, m, payloads, *, raw=None, plan_paths=None, large=False):
    raw = manifest(m) if raw is None else raw
    result = dict(id=cid,package=m['header']['package_name'],data_ver=DATA_VER,package_version=VERSION,
        manifest_crc32_le=crc(raw),manifest_sha256=sha(raw),manifest_size=len(raw))
    if large:
        result['recipe'] = dict(kind='replace_package_note',base_case='data-valid',value='x',repeat=len(m['header']['package_note']))
    else: result['manifest_base64'] = b64(raw)
    try: index = parse_manifest(raw)
    except Exception as ex:
        result.update(parse_ok=False,error_type=type(ex).__name__)
        return result
    result.update(parse_ok=True,expected_index=index)
    if large: result['expected_index']['header']['package_note'] = None
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        try: vm = verified(raw, result['package'], root/'manifests')
        except Exception as ex:
            result['manifest_verification'] = dict(ok=False,error_type=type(ex).__name__)
            return result
        result['manifest_verification'] = dict(ok=True)
        paths = [a['path'] for a in m['assets']] if plan_paths is None else plan_paths
        result['plan'] = dict(asset_paths=paths,bundle_names=[])
        try:
            plan = build_update_plan(vm,asset_paths=paths,cache_root=root/'bundles')
            result['plan'].update(success=True,ordered_names=[e.spec.name for e in plan.entries],download_bytes=plan.download_bytes,
                entries=[dict(name=e.spec.name,dependencies=list(e.dependencies),change=e.change) for e in plan.entries])
        except Exception as ex:
            result['plan'].update(success=False,error_type=type(ex).__name__)
        result['payloads'] = [dict(name=n,base64=b64(v),size=len(v),md5=md5(v),crc32_le=crc(v),sha256=sha(v)) for n,v in payloads.items()]
        result['downloads'] = []
        for n,v in payloads.items():
            spec = spec_from_manifest(data_ver=DATA_VER,package=result['package'],index=vm.index,name=n)
            for suffix,body in [('valid',v),('same-size-corrupt',bytes([v[0]^1])+v[1:]),('short',v[:-1]),('long',v+b'!')]:
                try:
                    path = fetch_bundle(spec,cache_root=root/('download-'+n+'-'+suffix),opener=opener_for({spec.url:body}))
                    assert path.read_bytes() == v
                    ok = True
                except ValueError: ok = False
                result['downloads'].append(dict(id=suffix,name=n,ok=ok))
    return result

def generate():
    output = dict(schema_version=1,source_sha256={p:sha((ROOT/p).read_bytes().replace(b'\r\n',b'\n')) for p in SOURCES},
        required_tables=list(_REQUIRED_TABLES),asset_root=_ASSET_ROOT,cases=[])
    for package,prefix in [('DataPackage','data'),('MainPackage','main')]:
        base,payloads = model(package)
        output['cases'].append(case(prefix+'-valid',base,payloads))
        raw = manifest(base)
        for suffix,broken in [('trailing',raw+b'\x00'),('truncated',raw[:-1]),('boolean',raw[:11]+b'\x02'+raw[12:]),
                              ('invalid-utf8',raw[:6]+b'\xff'+raw[7:])]:
            output['cases'].append(case(prefix+'-'+suffix,base,payloads,raw=broken))
        for suffix,mutate in [
            ('duplicate-path',lambda m:m['assets'].append(copy.deepcopy(m['assets'][0]))),
            ('duplicate-name',lambda m:m['bundles'][1].update(name=m['bundles'][0]['name'])),
            ('asset-negative',lambda m:m['assets'][0].update(bundle_id=-1)),
            ('asset-out-of-range',lambda m:m['assets'][0].update(bundle_id=5)),
            ('dependency-negative',lambda m:m['bundles'][0].update(dependency_ids=[-1])),
            ('dependency-out-of-range',lambda m:m['bundles'][0].update(dependency_ids=[5])),
            ('negative-size',lambda m:m['bundles'][0].update(file_size=-1)),
            ('header-flags',lambda m:m['header'].update(enable_addressable=False,location_to_lower=True,include_asset_guid=False))]:
            changed=copy.deepcopy(base); mutate(changed)
            output['cases'].append(case(prefix+'-'+suffix,changed,payloads))
        if package == 'DataPackage':
            for table in _REQUIRED_TABLES:
                changed=copy.deepcopy(base)
                changed['assets']=[a for a in changed['assets'] if a['path'] != _ASSET_ROOT+table+'.bytes']
                output['cases'].append(case('missing-'+table,changed,payloads,plan_paths=[_ASSET_ROOT+t+'.bytes' for t in _REQUIRED_TABLES]))
            changed=copy.deepcopy(base);changed['header']['package_note']='x'*65535
            output['cases'].append(case('note-utf8-max',changed,payloads,large=True))
    # Field-level fingerprint sensitivity uses the actual Python fingerprint functions.
    index=parse_manifest(manifest(model('DataPackage')[0]))
    output['fingerprint_deltas']=[]
    for kind,func,original,changes in [
        ('bundle',bundle_fingerprint,index['bundles'][0],dict(unity_crc=1,encrypted=False,tags=['different'],dependencies=['dep-b.bundle'],file_hash='0'*32,file_crc='0'*8,file_size=999,name='renamed.bundle',dependency_ids=[4])),
        ('asset',asset_fingerprint,index['assets'][0],dict(address='different',guid='different',tags=['different'],bundle_name='dep-a.bundle',path='different',bundle_id=4))]:
        for field,value in changes.items():
            changed=copy.deepcopy(original);changed[field]=value
            output['fingerprint_deltas'].append(dict(id=kind+'-'+field,kind=kind,field=field,value=value,
                before=func(original),after=func(changed),changed=func(original)!=func(changed)))
    return (json.dumps(output,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    path=Path(__file__).with_name('bundle_sources.json')
    data=generate()
    if args.check:
        if not path.exists() or path.read_bytes()!=data: raise SystemExit('Bundle source fixture differs; regenerate and review.')
        print('Bundle source parity fixture is current.')
    else:
        path.write_bytes(data);print(str(path))
