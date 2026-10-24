"""Collect one current 1275 scene pair from a pinned official YooAsset manifest.

Read-only game input. Uses upstream YooAsset 2.2.5 ManifestTools binary layout;
never searches raw strings for names, and never copies every game bundle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib
from zipfile import ZipFile,ZIP_DEFLATED

MAIN_SHA256='65da10fab29b8ce96247a18e611ee0ba3c5c3bc5cb71a42c4e177001a8c4ba49'
MANIFEST='MainPackage_1275_2026_10_21_18_29_38_49.bytes'


class SceneCollectionError(ValueError):pass


class Reader:
    def __init__(self,data):self.data=data;self.pos=0
    def take(self,n):
        if n<0 or self.pos+n>len(self.data):raise SceneCollectionError('Manifest truncated')
        start=self.pos;self.pos+=n;return self.data[start:self.pos]
    def number(self,fmt):return struct.unpack('<'+fmt,self.take(struct.calcsize('<'+fmt)))[0]
    def text(self):return self.take(self.number('H')).decode('utf8')
    def texts(self):return [self.text() for _ in range(self.number('H'))]
    def boolean(self):
        value=self.number('B')
        if value not in (0,1):raise SceneCollectionError('Invalid Manifest Boolean')
        return bool(value)


def parse_manifest(raw):
    if hashlib.sha256(raw).hexdigest()!=MAIN_SHA256:raise SceneCollectionError('Not the reviewed official 1275 MainPackage manifest')
    r=Reader(raw)
    if r.number('I')!=0x00594f4f or r.text()!='2.2.5':raise SceneCollectionError('Unsupported YooAsset manifest')
    for _ in range(3):r.boolean()
    r.number('i');r.number('i');r.text()
    if r.text()!='MainPackage' or r.text()!='1275_2026_10_21_18_29_38_49':raise SceneCollectionError('Wrong package version')
    r.text();assets=r.number('i')
    if not 0<=assets<=100000:raise SceneCollectionError('Invalid asset count')
    ids=[]
    for _ in range(assets):r.text();r.text();r.text();r.texts();ids.append(r.number('i'))
    count=r.number('i')
    if not 0<count<=100000:raise SceneCollectionError('Invalid bundle count')
    bundles=[];names=set()
    for _ in range(count):
        name=r.text();unity_crc=r.number('I');md5=r.text();crc=r.text();size=r.number('q');encrypted=r.boolean();r.texts()
        deps=[r.number('i') for _ in range(r.number('H'))]
        if (name in names or not re.fullmatch('[0-9a-f]{32}',md5) or not re.fullmatch('[0-9a-f]{8}',crc)
                or size<=0 or any(not 0<=i<count for i in deps)):
            raise SceneCollectionError('Invalid bundle record')
        names.add(name);bundles.append({'bundle_name':name,'file_hash':md5,'crc':crc,'size':size,'encrypted':encrypted,'dependencies':deps})
    if r.pos!=len(raw) or any(not 0<=i<count for i in ids):raise SceneCollectionError('Manifest boundary or asset references invalid')
    return {row['bundle_name']:row for row in bundles}


def collect(yoo_root,model,output):
    if type(model) is not int or not 0<model<=65535:raise SceneCollectionError('Invalid scene model')
    root=Path(yoo_root).resolve(strict=True);output=Path(output).resolve()
    game_data=root.parent if root.name.casefold()=='yoo' else root
    if output==game_data or game_data in output.parents:raise SceneCollectionError('Output must be outside game data')
    if output.exists():raise FileExistsError(output)
    manifest=root/'MainPackage'/'ManifestFiles'/MANIFEST
    raw=manifest.read_bytes();bundles=parse_manifest(raw);rows=[];sources=[]
    for name in (f'mainpackage_scene_{model}.bundle',f'mainpackage_scene_{model}_dependency.bundle'):
        if name not in bundles:raise SceneCollectionError('Model pair missing from official 1275 manifest: '+name)
        row=bundles[name]
        if row['encrypted']:raise SceneCollectionError('Encrypted bundle is unsupported')
        relative=f"MainPackage/BundleFiles/{row['file_hash'][:2]}/{row['file_hash']}/__data"
        path=(root/relative).resolve(strict=True)
        if root not in path.parents:raise SceneCollectionError('Source path leaves game data')
        blob=path.read_bytes()
        if (len(blob)!=row['size'] or hashlib.md5(blob).hexdigest()!=row['file_hash']
                or zlib.crc32(blob).to_bytes(4,'little').hex()!=row['crc'] or not blob.startswith(b'UnityFS\0')):
            raise SceneCollectionError('Bundle size/hash/CRC mismatch: '+name)
        rows.append({'package':'MainPackage','group':'scenes',**row,'path':relative,'sha256':hashlib.sha256(blob).hexdigest()})
        sources.append((relative,blob))
    selection={'kind':'current_scene_pair_1275','target_revision':1275,'model_ids':[model],
        'manifest_sha256_1275':{'MainPackage':MAIN_SHA256},'bundles':rows,
        'all_runtime_dependencies_verified':False}
    created=False
    try:
        with ZipFile(output,'x',compression=ZIP_DEFLATED) as z:
            created=True
            z.writestr('scene_selection.json',json.dumps(selection,ensure_ascii=False,indent=2))
            z.writestr('source/MainPackage/ManifestFiles/'+MANIFEST,raw)
            for relative,blob in sources:z.writestr('source/'+relative,blob)
        with ZipFile(output) as z:
            if z.testzip() is not None:raise SceneCollectionError('Output archive CRC invalid')
    except Exception:
        if created:output.unlink(missing_ok=True)
        raise
    return {'model_id':model,'bundles':len(rows),'output':str(output),'can_send_packets':False}


def main():
    p=argparse.ArgumentParser(description='依已核對1275 Manifest提取指定場景pair；不需舊差異清單')
    p.add_argument('yoo_root',type=Path);p.add_argument('--model',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(collect(a.yoo_root,a.model,a.output),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
