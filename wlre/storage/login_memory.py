"""Opt-in login memory. Passwords use current-user Windows DPAPI only."""
from wlre.storage.paths import data_root as user_data_root
import base64
import ctypes
import json
import os
from pathlib import Path
import tempfile


class MemoryError(ValueError):
    pass


def path():
    return user_data_root()/'login_memory.json'


def _crypt(raw,entropy,decrypt=False):
    if os.name!='nt':raise MemoryError('記住密碼需要 Windows 的加密保護；仍可只記住帳號。')
    class Blob(ctypes.Structure):
        _fields_=[('size',ctypes.c_uint32),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffers=[]
    def blob(data):
        buffer=ctypes.create_string_buffer(data);buffers.append(buffer)
        return Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    source,extra,result=blob(raw),blob(entropy),Blob()
    crypt32=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    function=crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p if decrypt else ctypes.c_wchar_p,
                       ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(Blob)]
    function.restype=ctypes.c_int
    kernel32.LocalFree.argtypes=[ctypes.c_void_p];kernel32.LocalFree.restype=ctypes.c_void_p
    try:
        if not function(ctypes.byref(source),None if decrypt else 'WLRE LaLa login',ctypes.byref(extra),None,None,1,ctypes.byref(result)):
            raise MemoryError('Windows 無法解密已記住的密碼，請重新輸入。' if decrypt else 'Windows 無法加密密碼；未儲存明文密碼。')
        return ctypes.string_at(result.data,result.size)
    finally:
        if result.data:kernel32.LocalFree(ctypes.cast(result.data,ctypes.c_void_p))
        for buffer in buffers:ctypes.memset(buffer,0,ctypes.sizeof(buffer))


def _entropy(record):
    return json.dumps(['WLRE.LaLa.Login.v1',record['host'],record['port'],record['account'],record.get('line_id',0)],ensure_ascii=False).encode('utf8')


def identity(host,port,account,line_id=0):
    import hashlib
    return hashlib.sha256(json.dumps([host.strip(),port,account,line_id],ensure_ascii=False).encode('utf8')).hexdigest()


def _empty():return {'version':2,'selected':None,'entries':{}}


def _read_unlocked(file):
    try:
        with file.open(encoding='utf8') as stream:store=json.load(stream)
    except FileNotFoundError:return _empty()
    except (ValueError,UnicodeError):raise MemoryError('記住的登入資料損壞，請重新設定。') from None
    if not isinstance(store,dict) or store.get('version')!=2 or not isinstance(store.get('entries'),dict):
        raise MemoryError('記住的登入資料格式錯誤。')
    for key,record in store['entries'].items():
        if not isinstance(record,dict) or not isinstance(record.get('host'),str) or not isinstance(record.get('account'),str) or not record['account'] or type(record.get('port')) is not int or not 0<record['port']<=65535 or not isinstance(record.get('secret',''),str) or type(record.get('line_id',0)) is not int or not 0<=record.get('line_id',0)<=65535 or not isinstance(record.get('line_name',''),str) or key!=identity(record['host'],record['port'],record['account'],record.get('line_id',0)):
            raise MemoryError('記住的登入資料格式錯誤。')
        record.setdefault('line_id',0);record.setdefault('line_name','')
    if store.get('selected') is not None and (not isinstance(store['selected'],str) or store['selected'] not in store['entries']):
        raise MemoryError('記住的帳號選擇資料錯誤。')
    return store


def _read(file):
    from wlre.storage.atomic import file_lock
    if not file.exists():return _empty()
    with file_lock(file):return _read_unlocked(file)


def list_entries(file=None):
    store=_read(Path(file) if file is not None else path())
    return [{'key':key,**{field:r[field] for field in ('host','port','account','line_id','line_name')},'remember_password':bool(r.get('secret'))}
            for key,r in store['entries'].items()]


def load(key=None,file=None):
    store=_read(Path(file) if file is not None else path())
    key=key or store.get('selected')
    if key is None:return None
    record=store['entries'].get(key)
    if record is None:return None
    result={field:record[field] for field in ('host','port','account','line_id','line_name')}
    result.update(key=key,remember_account=True,remember_password=bool(record.get('secret')),password='',password_error=False)
    if record.get('secret'):
        try:
            encrypted=base64.b64decode(record['secret'],validate=True)
            result['password']=_crypt(encrypted,_entropy(record),True).decode('utf8')
        except (ValueError,OSError,UnicodeError):result['password_error']=True
    return result


def _write(store,file):
    file.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix=file.name+'.',dir=file.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:json.dump(store,stream,ensure_ascii=False,indent=2)
        os.replace(temporary,file)
    finally:Path(temporary).unlink(missing_ok=True)


def _transaction(function):
    from functools import wraps
    from inspect import signature
    from wlre.storage.atomic import file_lock
    parameters=signature(function)
    @wraps(function)
    def guarded(*args,**kwargs):
        file=parameters.bind(*args,**kwargs).arguments.get('file')
        with file_lock(Path(file) if file is not None else path()):
            return function(*args,**kwargs)
    return guarded


@_transaction
def select(key,file=None):
    file=Path(file) if file is not None else path();store=_read(file)
    if key not in store['entries']:raise MemoryError('此帳號已移除，請重新選擇。')
    store['selected']=key;_write(store,file)


@_transaction
def delete(key,file=None):
    file=Path(file) if file is not None else path();store=_read(file)
    store['entries'].pop(key,None)
    if store.get('selected') not in store['entries']:store['selected']=next(iter(store['entries']),None)
    if store['entries']:_write(store,file)
    else:file.unlink(missing_ok=True)


@_transaction
def forget_password(key,file=None):
    file=Path(file) if file is not None else path();store=_read(file)
    if key in store['entries']:
        store['entries'][key].pop('secret',None);_write(store,file)


@_transaction
def save(host,port,account,password,remember_account,remember_password,file=None,line_id=0,line_name=''):
    file=Path(file) if file is not None else path()
    if not isinstance(host,str) or not host.strip() or type(port) is not int or not 0<port<=65535 or not isinstance(account,str) or not account:
        raise MemoryError('請先填妥伺服器、Port 與帳號。')
    if type(line_id) is not int or not 0<=line_id<=65535 or not isinstance(line_name,str) or len(line_name)>128:raise MemoryError('分流設定錯誤。')
    key=identity(host,port,account,line_id)
    if not remember_account:
        delete(key,file);return None
    record={'host':host.strip(),'port':port,'account':account,'line_id':line_id,'line_name':line_name}
    if remember_password:
        if not isinstance(password,str) or not password:raise MemoryError('請先輸入要記住的密碼。')
        record['secret']=base64.b64encode(_crypt(password.encode('utf8'),_entropy(record))).decode('ascii')
    store=_read(file);store['entries'][key]=record;store['selected']=key;_write(store,file)
    return key
