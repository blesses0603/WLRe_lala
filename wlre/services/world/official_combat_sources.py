"""Bounded official Lua data inputs; no Lua or downloaded client code executes."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, build_opener
import zipfile
from wlre.services.official_lua_index import _NoRedirect, list_url, parse_list, MAX_LIST_BYTES
from wlre.services.world.official_lua_codec import METADATA_SHA256, KNOWN_FILES, decode_reviewed

APK_URL='https://cgdl.chinesegamer.net/apk/wlre.apk'
APK_SIZE=103074197
APK_ETAG='"b65fca9976e6dc1:0"'
METADATA_MEMBER='assets/bin/Data/Managed/Metadata/global-metadata.dat'
LUA_PATHS=('Lua/Common/Define.lua','Lua/Controller/FightUnit.lua')
MAX_DOWNLOAD=8*1024*1024


def opener():
    try:
        from android_app.tls import verified_https_opener
    except ImportError:
        return build_opener(_NoRedirect()).open
    return verified_https_opener(_NoRedirect())


class Budget:
    def __init__(self,open_url):self.open=open_url;self.used=0;self.calls=0
    def get(self,url,limit,*,start=None):
        if self.calls>=16 or self.used+limit>MAX_DOWNLOAD:raise ValueError('官方 Lua 擷取超出額度')
        self.calls+=1
        headers={'User-Agent':'WLRe-LaLa-CombatSources/1'}
        if start is not None:headers.update(Range=f'bytes={start}-{start+limit-1}',**{'If-Range':APK_ETAG})
        with self.open(Request(url,headers=headers),timeout=20) as response:
            if response.geturl()!=url or response.status!=(200 if start is None else 206):
                raise ValueError('Unexpected official source response')
            if start is not None and response.headers.get('Content-Range')!=f'bytes {start}-{start+limit-1}/{APK_SIZE}':
                raise ValueError('Official APK changed or ignored range')
            raw=response.read(limit+1)
        self.used+=len(raw)
        if len(raw)>limit or start is not None and len(raw)!=limit:raise ValueError('Invalid official source length')
        return raw


class RemoteZip(io.RawIOBase):
    def __init__(self,budget):self.pos=0;self.budget=budget
    def seekable(self):return True
    def readable(self):return True
    def tell(self):return self.pos
    def seek(self,offset,whence=0):
        if whence not in (0,1,2):raise ValueError('Invalid range mode')
        self.pos=offset if whence==0 else self.pos+offset if whence==1 else APK_SIZE+offset
        if not 0<=self.pos<=APK_SIZE:raise ValueError('Invalid APK range')
        return self.pos
    def read(self,size=-1):
        size=APK_SIZE-self.pos if size<0 else min(size,APK_SIZE-self.pos)
        if not size:return b''
        raw=self.budget.get(APK_URL,size,start=self.pos);self.pos+=size;return raw


def _save(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink() or path.exists() and path.stat().st_size>16*1024*1024:
        raise ValueError('Unsafe or oversized official source cache')
    fd,name=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if path.exists() and path.read_bytes()!=raw:
            old=path.read_bytes();archive=path.with_name(path.name+'.rejected-'+hashlib.sha256(old).hexdigest())
            if not archive.exists():os.replace(path,archive)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def _cached(path,digest,limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:return None
    raw=path.read_bytes()
    return raw if hashlib.sha256(raw).hexdigest()==digest else None


def _load_inputs(root,data_ver,*,download=False,open_url=None):
    # The interpreter/data contract is reviewed for this version only.
    if data_ver!='1.3.23':raise ValueError('官方戰鬥 Lua 版本尚未驗證')
    base=Path(root)/'combat_sources';budget=Budget(open_url or opener());inputs={}
    metadata_path=base/('metadata-'+METADATA_SHA256)
    metadata=_cached(metadata_path,METADATA_SHA256,16*1024*1024)
    if metadata is None:
        if not download:raise ValueError('官方 Lua 解碼所需客戶端中繼資料尚未同步')
        with zipfile.ZipFile(RemoteZip(budget)) as archive:
            if len(archive.infolist())>2000:raise ValueError('Unexpected APK directory')
            matches=[i for i in archive.infolist() if i.filename==METADATA_MEMBER]
            if len(matches)!=1:raise ValueError('Ambiguous official client metadata')
            info=matches[0]
            if info.file_size!=12812252 or info.compress_size>4*1024*1024:raise ValueError('Unknown client metadata size')
            with archive.open(info) as stream:metadata=stream.read(16*1024*1024+1)
        if hashlib.sha256(metadata).hexdigest()!=METADATA_SHA256:
            _save(base/'rejected'/('metadata-'+hashlib.sha256(metadata).hexdigest()),metadata)
            raise ValueError('Unknown official client metadata fingerprint')
        _save(metadata_path,metadata)
    inputs['client-metadata']=metadata
    index_path=base/data_ver/'LuaScriptPathList.txt'
    if download:
        index_raw=budget.get(list_url(data_ver),MAX_LIST_BYTES);parse_list(index_raw)
    else:
        if not index_path.is_file() or index_path.stat().st_size>MAX_LIST_BYTES:raise ValueError('官方 Lua 版本清單尚未同步')
        index_raw=index_path.read_bytes()
    index=parse_list(index_raw);inputs['lua-index']=index_raw
    clear={}
    for source in LUA_PATHS:
        name=Path(source).name;expected=KNOWN_FILES[name][0]
        path=base/data_ver/name;raw=_cached(path,expected,2*1024*1024)
        if raw is None:
            if not download:raise ValueError('官方戰鬥 Lua 尚未同步：'+name)
            raw=budget.get(list_url(data_ver).rsplit('/',1)[0]+'/'+source,2*1024*1024)
        if hashlib.sha256(raw).hexdigest()!=expected or hashlib.md5(raw).hexdigest()!=index.get(source):
            if download:
                _save(base/'rejected'/(name+'-'+hashlib.sha256(raw).hexdigest()),raw)
                _save(base/'rejected'/('index-'+hashlib.sha256(index_raw).hexdigest()),index_raw)
            raise ValueError('Official Lua source or version list changed: '+name)
        clear[name]=decode_reviewed(name,raw,metadata).decode('utf-8-sig')
        inputs[name]=raw
        if download:_save(path,raw)
    if download:_save(index_path,index_raw)
    return clear,inputs


def load_inputs(root,data_ver,*,download=False,open_url=None):
    if data_ver!='1.3.23':raise ValueError('官方戰鬥 Lua 版本尚未驗證')
    marker=Path(root)/'combat_sources'/data_ver/'last_attempt.json'
    if not download and marker.exists():
        if marker.is_symlink() or marker.stat().st_size>4096:raise ValueError('官方戰鬥來源狀態無效')
        status=json.loads(marker.read_text())
        if not isinstance(status,dict) or status.get('ok') is not True:raise ValueError('上次官方戰鬥來源同步未完成，等待重試；保留舊版資料')
    try:
        result=_load_inputs(root,data_ver,download=download,open_url=open_url)
    except (OSError,ValueError,RuntimeError,ImportError,zipfile.BadZipFile,EOFError) as error:
        if download:_save(marker,json.dumps({'ok':False,'error_type':type(error).__name__}).encode())
        if isinstance(error,(zipfile.BadZipFile,EOFError)):
            raise ValueError('官方客戶端封裝未通過驗證') from error
        raise
    if download:_save(marker,b'{"ok":true}')
    return result
