"""Session-only, bounded, server-scoped names; never infer identity from @ text."""
from collections import OrderedDict
from wlre.network.wire import ProtocolError

def name_scope(event):
    return event.get('server_id') if event.get('server_id') is not None else 'cross-unknown' if event.get('channel')=='跨服' else None

class NameBook:
    def __init__(self):self.names=OrderedDict()
    def learn(self,rid,name,server=None):
        if type(rid) is not int or not 0<rid<=0xffffffff or not isinstance(name,str) or not name or name==str(rid):return False
        name=''.join(c for c in name if ord(c)>=32 and ord(c)!=127)
        if not name:return False
        key=(server,rid);changed=self.names.get(key)!=name
        self.names[key]=name;self.names.move_to_end(key)
        while len(self.names)>4096:self.names.popitem(last=False)
        return changed
    def update(self,state,event=None):
        changed=False
        for person in [state.get('player',{}),*state.get('party',{}).get('nearby',{}).values(),*state.get('guild',{}).get('members',{}).values()]:changed=self.learn(person.get('role_id'),person.get('name')) or changed
        if event:changed=self.learn(event.get('role_id'),event.get('name'),name_scope(event)) or changed
        return changed
    def name(self,rid,server=None):return self.names.get((server,rid),str(rid))
    def resolve(self,value,own_id=None):
        raw=str(value).strip()
        if raw.isascii() and raw.isdigit():rid=int(raw)
        else:
            ids={rid for (server,rid),name in self.names.items() if server is None and name==raw}
            if not ids:raise ProtocolError('尚無此角色名稱資料，請填 ID 或雙擊對方訊息')
            if len(ids)>1:raise ProtocolError('名稱對應多個角色，請改用 ID 或雙擊對方訊息')
            rid=ids.pop()
        if not 0<rid<=0xffffffff or rid==own_id:raise ProtocolError('請選擇有效的其他角色')
        return rid
