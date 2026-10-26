"""Validated preferences keyed by account and server hash; never store credentials."""
from wlre.storage.paths import account_file
import hashlib,json
from wlre.services.battle.auto_battle import defaults,validate
from wlre.services.battle import party_guard
from wlre.storage.atomic import file_lock,write_json
from wlre.storage import server_lines


def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False).encode()).hexdigest()


def server_scope(host,port):
    host=host.strip();port=int(port)
    lines=server_lines.load();known=server_lines.for_endpoint(lines,host,port)
    # Group only verified endpoints: a manually supplied line ID cannot merge servers.
    return ('official',known['id']//100) if known else ('custom',host,port)


def identity(host,port,account,line=0):
    return _hash(['server-account-v2',server_scope(host,port),account])


def legacy_identities(host,port,account,line=0):
    scope=server_scope(host,port)
    endpoints=[(host.strip(),int(port),int(line)),(host.strip(),int(port),0)]
    if scope[0]=='official':
        for row in server_lines.load():
            if row['id']//100==scope[1]:
                endpoints.extend(((row['host'],row['port'],row['id']),(row['host'],row['port'],0)))
    return list(dict.fromkeys(_hash([h,p,account,l]) for h,p,l in endpoints))


def settings_file(key,base=None):
    return account_file(key,base=base)


def _read(file):
    value=json.loads(file.read_text(encoding='utf8'))
    if not isinstance(value,dict) or set(value)!={'version','ai'} or value.get('version')!=1:
        raise ValueError('帳號設定格式不支援')
    return validate(value['ai'])


def load(key,base=None,legacy_keys=()):
    file=settings_file(key,base)
    with file_lock(file):
        if file.exists():return _read(file)
        candidates=[settings_file(old,base) for old in legacy_keys if old!=key]
        existing=[old for old in candidates if old.exists()]
        if existing:
            # Keep the most recently saved whole profile; preserve all old files.
            old=max(existing,key=lambda path:(path.stat().st_mtime_ns,path.name))
            with file_lock(old):value=_read(old)
            write_json(file,{'version':1,'ai':value})
            return value
    value=defaults();value['party_guard']=party_guard.load()
    return value


def save(key,value,base=None):
    checked=validate(value);file=settings_file(key,base)
    with file_lock(file):write_json(file,{'version':1,'ai':checked})
