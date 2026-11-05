"""Current official Ark tables, transcribed from ArkData.lua."""
from wlre.services.parser_diagnostics import diagnosed
from wlre.services.world.daily_task_1275 import Reader

TABLES=('ArkStarData_C','ArkAgentData_C','ArkFightData_C')


def _rows(raw,read):
    r=Reader(raw);count=r.i32();rows={}
    if not 0<count<=10000:raise ValueError('方舟資料筆數無效')
    for _ in range(count):
        row=read(r);key=row['id']
        if not key or key in rows:raise ValueError('方舟資料索引重複／無效')
        rows[key]=row
    if r.pos!=len(raw):raise ValueError('方舟資料長度不符')
    return rows


@diagnosed('ark-stars-v1')
def parse_stars(raw):
    return _rows(raw,lambda r:dict(id=r.u8(),prices=[r.u16() for _ in range(6)]))


@diagnosed('ark-agents-v1')
def parse_agents(raw):
    def read(r):
        row=dict(id=r.u8(),name_id=r.u32(),race=r.u32(),career=r.u32(),birth=r.u32(),
                 constellation=r.u32(),story=r.u32(),icon=r.u16())
        row['skills']=[dict(kind=r.u8(),icon=r.u16(),name_id=r.u32(),initial=r.u16(),
                            add=r.u16(),maximum=r.u8(),formula=r.u16()) for _ in range(2)]
        if any(not s['maximum'] for s in row['skills']):raise ValueError('情報員技能上限無效')
        return row
    return _rows(raw,read)


def _parse_fights(raw,with_tail):
    def read(r):
        row=dict(id=r.u16(),event_kind=r.u8());size=r.u16()
        if size%2 or size>1024 or r.pos+size>len(raw):raise ValueError('方舟圖示名稱長度無效')
        row['icon']=raw[r.pos:r.pos+size].decode('utf-16le');r.pos+=size
        row.update(alien=r.u32(),name_id=r.u32(),content_id=r.u32(),situation=r.u16(),
                   enemies=[r.u16() for _ in range(4)],map=r.u16(),fight=r.u16(),
                   explore=r.u16(),mark=r.u16(),agent=r.u8())
        row['awards']=[dict(kind=r.u8(),id=r.u32(),value=r.u32()) for _ in range(5)]
        if with_tail:
            row['opaque_flag']=r.u8()
            if row['opaque_flag'] not in (0,1):raise ValueError('方舟戰鬥尾端旗標無效')
        return row
    return _rows(raw,read)


@diagnosed('ark-fights-v1')
def parse_fights(raw):
    # Uploaded 1262 Lua has no tail. Verified 1286 bytes add one boolean per
    # record; retain it without assigning gameplay meaning or bypass rights.
    matches=[]
    for with_tail in (False,True):
        try:matches.append(_parse_fights(raw,with_tail))
        except (ValueError,UnicodeError):pass
    if len(matches)!=1:raise ValueError('方舟戰鬥格式未知或有歧義')
    return matches[0]


def _round_ratio(numerator,denominator):
    # Unity Mathf.Round uses midpoint-to-even. Keep prices exact without float.
    q,r=divmod(numerator,denominator)
    return q+int(r*2>denominator or r*2==denominator and q%2==1)


def dispatch_quote(catalog,planet,hours,agent):
    row=catalog['stars'].get(planet);definition=catalog['agents'].get(agent['id'])
    if not row or not definition or type(hours) is not int or not 1<=hours<=6:
        raise ValueError('沒有同版星球／情報員派遣資料')
    if agent['planet']:raise ValueError('情報員正在採集')
    discount=0;extension=0
    for skill,level in zip(definition['skills'],agent['skills']):
        if not 1<=level<=skill['maximum']:raise ValueError('情報員技能等級超出同版資料')
        value=skill['initial']+skill['add']*(level-1)
        if skill['kind']==2:discount+=value # tenths of a percent
        elif skill['kind']==1:extension+=value
        elif skill['kind'] not in (0,3,4,5):raise ValueError('未知情報員技能種類')
    if not 0<=discount<=1000:raise ValueError('情報員折扣超出可驗證範圍')
    price=_round_ratio(row['prices'][hours-1]*(1000-discount),1000)
    duration=_round_ratio(hours*3600*(100+extension),100)
    if not 0<duration<=65535:raise ValueError('採集時間超出伺服器欄位範圍')
    return dict(planet=planet,hours=hours,agent=agent['index'],price=price,duration=duration)


def load_verified_catalog(manifest,bundle_root,loader,root,identity,texts,items):
    from wlre.services.world.resource_database import load_verified_tables
    parsed,sources=load_verified_tables(manifest,bundle_root,loader,root,identity,
        {'ark_stars':('ArkStarData_C',parse_stars),'ark_agents':('ArkAgentData_C',parse_agents),
         'ark_fights':('ArkFightData_C',parse_fights)})
    for group in ('ark_agents','ark_fights'):
        for row in parsed[group].values():
            name=texts.get(row['name_id'])
            if not isinstance(name,str) or not name.strip():raise ValueError('方舟資料缺少同版名稱')
            row['name']=name
    for row in parsed['ark_fights'].values():
        if any(a['kind'] in (10,11) and a['id'] not in items for a in row['awards']):
            raise ValueError('方舟戰鬥獎勵缺少同版物品')
    return dict(stars=parsed['ark_stars'],agents=parsed['ark_agents'],fights=parsed['ark_fights'],sources=sources,texts=texts)
