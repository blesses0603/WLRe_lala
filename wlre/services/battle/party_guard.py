"""User-selected required role IDs, checked against server-confirmed membership."""
import json
import os
from pathlib import Path
from wlre.services.battle.party import own_team
from wlre.network.wire import ProtocolError


def defaults():
    return {'enabled':False,'members':[]}


def validate(value):
    if not isinstance(value,dict) or set(value)-{'enabled','members'}:
        raise ProtocolError('必要隊員設定格式錯誤')
    enabled=value.get('enabled',False);members=value.get('members',[])
    if type(enabled) is not bool or not isinstance(members,list) or len(members)>4:
        raise ProtocolError('必要隊員最多四人，開關須為布林值')
    checked=[];seen=set()
    for member in members:
        if not isinstance(member,dict) or set(member)-{'role_id','name'}:
            raise ProtocolError('必要隊員資料格式錯誤')
        rid=member.get('role_id');name=member.get('name','')
        if type(rid) is not int or not 0<rid<=0xffffffff:
            raise ProtocolError('必要隊員須使用有效角色 ID')
        if rid in seen:raise ProtocolError('必要隊員名單不可重複')
        if not isinstance(name,str) or len(name)>128 or any(ord(c)<32 or ord(c)==127 for c in name):
            raise ProtocolError('必要隊員名稱格式錯誤')
        seen.add(rid);checked.append({'role_id':rid,'name':name or str(rid)})
    if enabled and not checked:raise ProtocolError('請先設定至少一位必要隊員，再啟用缺員逃跑')
    return {'enabled':enabled,'members':checked}


def present_ids(state):
    """Nearby players, guild rosters and other parties never count as teammates."""
    pid=state.get('player',{}).get('role_id')
    if not pid:return set()
    team=own_team(state)
    # A lone local player still satisfies a requirement for that same role.
    return set(team['members']) if team else {pid}


def missing(state,config):
    present=present_ids(state)
    return [dict(member) for member in config['members'] if member['role_id'] not in present]


def escape_reason(state,config):
    absent=missing(state,config) if config['enabled'] else []
    return '必要隊員未到齊：'+ '、'.join(m['name'] for m in absent)+'；優先逃跑' if absent else ''


def settings_path():
    base=Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'.config'))
    return base/'WLRE_LaLa'/'party_guard.json'


def load(path=None):
    path=Path(path) if path is not None else settings_path()
    try:
        with path.open(encoding='utf-8-sig') as stream:return validate(json.load(stream))
    except FileNotFoundError:return defaults()


def save(config,path=None):
    checked=validate(config);path=Path(path) if path is not None else settings_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    # Use a unique temporary file so separate client windows never share it.
    import tempfile
    fd,temp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(checked,stream,ensure_ascii=False,indent=2)
        os.replace(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)
