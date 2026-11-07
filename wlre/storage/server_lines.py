"""ServerList.txt endpoints follow Network.Connect; never guess line addresses."""
from wlre.paths import RESOURCE_ROOT

CUSTOM='目前連線（自訂）'

def path():return RESOURCE_ROOT.joinpath('server_list.json')

def parse(data):
    if isinstance(data,dict):data=data.get('serverList')
    if not isinstance(data,list):raise ValueError('分流表須為原版 ServerList.txt 的 JSON 陣列。')
    relays={r['id']:str(r.get('name','')) for r in data if isinstance(r,dict) and type(r.get('id')) is int and 0<r['id']<100}
    result=[];seen=set()
    for row in data:
        if not isinstance(row,dict):raise ValueError('分流資料格式錯誤')
        rid=row.get('id')
        if type(rid) is not int:raise ValueError('分流 ID 須為整數')
        if rid<=100:continue
        if rid>65535:raise ValueError('分流 ID 超出範圍')
        host=row.get('address',row.get('host'));port=row.get('port')
        if not isinstance(host,str) or not host.strip() or len(host)>255 or any(c.isspace() or ord(c)<32 for c in host) or type(port) is not int or not 0<port<=65535 or rid in seen:
            raise ValueError('分流 ID、位址或 Port 錯誤／重複')
        title=relays.get(rid//100) or str(row.get('name','伺服器'))
        title=''.join(c for c in title if ord(c)>=32 and ord(c)!=127)[:60]
        result.append({'id':rid,'name':f'{title}｜{rid%100}線 ({rid})','host':host.strip(),'port':port})
        seen.add(rid)
    if not result:raise ValueError('分流表中沒有可登入的分流（ID > 100）。')
    return sorted(result,key=lambda r:r['id'])

def load():
    """Read the last verified official import; a new offline install has no lines."""
    from wlre.services.official_server_list import read_cached_server_list
    return read_cached_server_list()['rows']


def for_endpoint(lines,host,port):
    return next((row for row in lines if row['host']==host and row['port']==port),None)


def status_label():
    from wlre.services.official_server_list import read_cached_server_list
    try:
        status = read_cached_server_list()
    except (OSError, ValueError):
        return '伺服器清單校驗失敗，請重新更新官方資料'
    if not status['rows']:
        return '尚未取得官方伺服器清單，請連網更新官方資料'
    source = status['origin'].split('/')[2]
    prefix = '更新失敗，沿用上次官方清單' if status['status'] == 'cached_after_refresh_failure' else '官方伺服器清單'
    return prefix + ' · ' + source + ' · ' + status['checked_at']
