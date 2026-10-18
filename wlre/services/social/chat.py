"""1262 text chat: UIChat.SendChat and Protocols_002; no automatic messages."""
import re
from wlre.network.wire import Packet, Reader, Writer, ProtocolError
from wlre.network.live_data import item_save
from wlre.services.battle.party import own_team

CHANNELS={'區域':2,'世界':1,'隊伍':5,'組織':6,'密語':3}
RECEIVE_CHANNELS={1:'世界',2:'區域',3:'密語',5:'隊伍',6:'組織',10:'世界',17:'密語',27:'跨服',28:'跨服'}
RESULTS={0:'伺服器已回覆發話結果',1:'發話太頻繁，請稍候再試',2:'目前被禁言，請稍後再發言'}

def unicode_field(text):
    try:raw=text.encode('utf-16le')
    except (UnicodeEncodeError,AttributeError) as exc:raise ProtocolError('聊天文字無法編碼') from exc
    if len(raw)>254:raise ProtocolError('訊息過長，最多 254 個 UTF-16 位元組（一般中文字 127 字）')
    return bytes([len(raw)])+raw


def chat_packet(command,state):
    channel=command.get('channel');text=command.get('text','')
    if channel not in CHANNELS:raise ProtocolError('請選擇可發話的頻道')
    if not isinstance(text,str) or not text.strip():raise ProtocolError('請輸入聊天內容')
    if any(ord(c)<32 or ord(c)==127 for c in text):raise ProtocolError('聊天內容不可含換行或控制字元')
    encoded=unicode_field(text)
    if channel=='隊伍' and not own_team(state):raise ProtocolError('請先加入隊伍再發話')
    if channel=='組織':
        guild=getattr(state,'guild',{}) or {}
        role_id=state.player.get('role_id')
        if not guild.get('ready'):
            raise ProtocolError('組織資料尚未同步或尚未加入組織，無法發話')
        if not role_id or str(role_id) not in guild.get('members',{}):
            raise ProtocolError('目前角色不在組織成員名單中，無法發話')
    if channel=='世界':
        attrs=state.attributes.get('self',{})
        level=attrs.get('40:0',attrs.get('35:0',state.attributes.get('TrueLv',state.attributes.get('Lv'))))
        if level is not None and level<10:raise ProtocolError('須達 10 級才可世界發話')
    w=Writer().u8(0)  # no linked inventory items
    if channel=='密語':
        try:target=int(command.get('target',0))
        except (TypeError,ValueError) as exc:raise ProtocolError('密語請填入對方角色 ID') from exc
        if not 0<target<=0xffffffff or target==state.player.get('role_id'):raise ProtocolError('請填入有效的其他角色 ID')
        w.u32(target)
    w.raw(encoded)
    reply=command.get('reply')
    if reply is None:w.u32(0)
    else:
        if not isinstance(reply,dict):raise ProtocolError('引用資料無效')
        rid=reply.get('role_id');quote=reply.get('text')
        if type(rid) is not int or not 0<rid<=0xffffffff:raise ProtocolError('引用角色 ID 無效')
        if reply.get('channel')!=channel:raise ProtocolError('引用回覆需使用原訊息頻道')
        if channel=='密語' and reply.get('whisper_target')!=target:raise ProtocolError('密語引用對象已變更，請重新選取訊息')
        if not isinstance(quote,str) or any(ord(c)<32 or ord(c)==127 for c in quote):raise ProtocolError('引用文字無效')
        items=reply.get('items',[])
        if not isinstance(items,list) or len(items)>255 or any(type(v) is not int or not 0<v<=65535 for v in items):raise ProtocolError('引用道具欄位無效')
        w.u32(rid).raw(unicode_field(quote)).u8(1 if reply.get('has_at') else 0).u8(len(items))
        for sid in items:w.u16(sid)
    return Packet(2,CHANNELS[channel],w.build())


def _profile(r):
    name=r.unicode8()
    r.take(16)  # sex/head, palettes, level/element/job/degree/rank/header frame
    if r.u8()==0:  # NewChat: readable business card
        r.take(7);r.unicode8()
        r.take(r.u8()*2)
    return name


def _body(r,event,cross=False):
    event['items']=[item_save(r,r.u8()) for _ in range(r.u8())]
    event['text']=r.unicode8()
    event['reply_id']=r.u32()
    if event['reply_id']:
        if cross:event['reply_server']=r.u16()
        event['reply_text']=r.unicode8();event['reply_at']=bool(r.u8())
        event['reply_items']=[r.u16() for _ in range(r.u8())]
    r.end()
    return event


def decode_chat(packet,local_role_id=None):
    if packet.main!=2:return None
    r=Reader(packet.payload);sub=packet.sub
    base={'main':2,'sub':sub}
    if sub==13:
        result=r.u8();r.end()
        return dict(base,type='chat_result',result=result,text=RESULTS.get(result,f'發話結果代碼 {result}'))
    if sub in (18,19):
        rid=r.u32()
        if not rid:r.end();return dict(base,type='chat_notice',text='查無此角色')
        online=bool(r.u8());name=_profile(r);r.end()
        return dict(base,type='chat_profile',role_id=rid,name=name,online=online)
    if sub==21:
        target=r.u32();r.end()
        return dict(base,type='chat_notice',role_id=target,text=f'密語對象 {target} 目前離線')
    if sub==0:
        index=r.u32();raw=r.take(r.remaining)
        # Lua explicitly uses EncodingType.System here; raw Chinese encoding is
        # not verified, so do not guess. Normal text channels use UTF-16LE.
        text=raw.decode('ascii') if raw.isascii() else '收到系統公告（此公告文字編碼尚未確認）'
        return dict(base,type='chat_message',channel='系統',role_id=0,text=text,announcement_index=index)
    if sub not in RECEIVE_CHANNELS:return None
    event=dict(base,type='chat_message',channel=RECEIVE_CHANNELS[sub])
    if sub==28:event['server_id']=r.u16()
    event['role_id']=r.u32()
    if sub==3:
        if local_role_id is None:
            return dict(base,type='chat_notice',text='收到密語，但尚無本機角色 ID，未猜測內容')
        event['target_id']=r.u32() if event['role_id']==local_role_id else local_role_id
    elif sub==17:event['target_id']=r.u32()
    if sub in (10,17):event['name']=_profile(r)
    elif sub==28:
        event['name']=r.unicode8();r.take(16)  # NewChat(hasCardData=false)
    return _body(r,event,cross=sub in (27,28))


def sent_event(packet):
    r=Reader(packet.payload);r.u8()
    event={'type':'chat_sent','channel':next(k for k,v in CHANNELS.items() if v==packet.sub)}
    if packet.sub==3:event['target_id']=r.u32()
    event['text']=r.unicode8();reply_id=r.u32()
    if reply_id:
        event['reply_id']=reply_id;event['reply_text']=r.unicode8();event['reply_at']=bool(r.u8());event['reply_items']=[r.u16() for _ in range(r.u8())]
    r.end()
    return event


def plain_text(text):
    # Render linked-item/colour markup as text; never open links or execute tags.
    text=re.sub(r'<[^>]{0,500}>','',str(text))
    return ''.join(c for c in text if ord(c)>=32 and ord(c)!=127)
