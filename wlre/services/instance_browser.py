"""Current verified SQLite instance catalog; no bundled game-data fallback."""
from copy import deepcopy
from wlre.network.wire import ProtocolError


def official_catalog():
    from wlre.services.world.runtime_1275 import active_runtime, Runtime1275Unavailable
    try:
        runtime = active_runtime()
    except Runtime1275Unavailable as error:
        raise ProtocolError('副本資料尚未由官方完成同步') from error
    catalog = getattr(runtime, 'instances', None)
    if catalog is None:
        raise ProtocolError(getattr(runtime, 'instance_status', '副本資料尚未同步'))
    return deepcopy(catalog)


def catalog_token():
    try:
        return official_catalog()['catalog_key']
    except ProtocolError:
        return None


def entries_for(mode):
    if mode not in ('main', 'coop'):
        raise ValueError('未知副本分類')
    try:
        rows = official_catalog()['records']
    except ProtocolError:
        return ()
    return tuple(row for row in rows if (row['kind'] == 2) == (mode == 'coop'))


def selection_fields(row):
    return {'catalog_key': row['catalog_key'], 'catalog_id': row['id'],
            'catalog_variant': row['variant']}


def selected_entry(mode, command):
    rows = entries_for(mode)
    matches = [row for row in rows if all(command.get(key) == value
               for key, value in selection_fields(row).items())]
    if (type(command.get('catalog_id')) is not int
            or type(command.get('catalog_variant')) is not int
            or len(matches) != 1 or not matches[0].get('creation_supported')):
        raise ProtocolError('副本資料已更新、尚未同步或不支援創房，請重新選擇')
    return matches[0]
