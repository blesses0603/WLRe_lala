"""Validated preferences keyed by endpoint/account hash; never store credentials."""
import hashlib,json,os
from pathlib import Path
from wlre.services.battle.auto_battle import defaults,validate
from wlre.services.battle import party_guard
from wlre.storage.atomic import file_lock,write_json


def identity(host,port,account,line=0):
    return hashlib.sha256(json.dumps([host.strip(),int(port),account,int(line)],ensure_ascii=False).encode()).hexdigest()


def settings_file(key,base=None):
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('帳號設定識別碼錯誤')
    root=Path(base) if base is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'WLRE_LaLa'
    return root/'accounts'/(key+'.json')


def load(key,base=None):
    file=settings_file(key,base)
    try:
        if not file.exists():raise FileNotFoundError
        with file_lock(file):value=json.loads(file.read_text(encoding='utf8'))
        if not isinstance(value,dict) or set(value)!={'version','ai'} or value.get('version')!=1:raise ValueError('帳號設定格式不支援')
        return validate(value['ai'])
    except FileNotFoundError:
        value=defaults();value['party_guard']=party_guard.load()
        return value


def save(key,value,base=None):
    checked=validate(value);file=settings_file(key,base)
    with file_lock(file):write_json(file,{'version':1,'ai':checked})
