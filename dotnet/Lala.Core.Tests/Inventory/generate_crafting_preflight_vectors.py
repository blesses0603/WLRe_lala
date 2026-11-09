"""Real retained recipe_plan prefix oracle, synthetic and offline only.

The actual helper runs through allocation and coherent recipe identity validation.
Legacy Writer construction / official build_add_packet are intercepted BEFORE any
packet bytes are created. No command wrapper, reservation acquire, observer, timer,
runtime activation or network operation runs. This deliberately is NOT an oracle
for late catalog drift, packet-builder validation, or production authorization.
"""
import base64
import copy
import gzip
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.services.items import crafting
from wlre.services.items.crafting_official_v1286 import RecipeCatalog
from wlre.network.wire import ProtocolError


class Captured(Exception):
    pass


def before_writer(*args, **kwargs):
    frame = inspect.currentframe().f_back
    while frame and frame.f_code is not crafting.recipe_plan.__code__:
        frame = frame.f_back
    assert frame is not None
    values = frame.f_locals
    raise Captured(copy.deepcopy({'tool': values['tool'], 'allocations': values['allocations']}))


def recipe(**fields):
    return dict(item_id=500, design_id=0, skill=0, tool_id=39001, output=3,
                materials=[{'item_id': 100, 'count': 2}], seconds=30,
                skill_level=0, suggest=0, time_id=0, limit_kind=0, mark_id=0,
                limit_times=0, order=1, open_used=0, **fields)


def item(index=2, item_id=100, count=10, **fields):
    return dict(index=index, item_id=item_id, count=count, serial=1000+index,
                serial_version=1, **fields)


def base():
    return {'recipes': [recipe()], 'item_id': 500, 'count': 2, 'role': 7,
            'crafting': {**crafting.defaults(), 'ready': True},
            'furniture': {**crafting.room_defaults(), 'owner': 7, 'ready': True,
                          'items': {'9': {'index': 9, 'item_id': 39001, 'status': 0, 'workbench': 123}}},
            'inventory': {'ready': True, 'reliable': True, 'items': {'2': item()}},
            'room_storage': {'materials': {'ready': True, 'reliable': True, 'items': {}},
                             'pending': None, 'uncertain': False}}


ERRORS = {
    '找不到這個製作配方': 'UnknownRecipe',
    '此配方僅供查看，不能加入製作排程': 'ReadOnlyRecipe',
    '此製作物在目前版本尚未開放': 'ProductClosed',
    '製作批數必須為 1～255': 'InvalidBatchCount',
    '此配方需要圖紙解鎖；圖鑑狀態尚未同步，未送出': 'DesignUnlockUnknown',
    '此配方有活動時間或次數限制，目前無法確認條件，未送出': 'TimeOrLimitUnknown',
    '請先進入自己的帳篷，取得工作設備資料': 'OwnRoomUnknown',
    '製作排程尚未同步': 'ScheduleNotReady', '製作排程已滿': 'QueueFull',
    '排程已有相同物品，需原版允許重複製作的家具': 'DuplicateProduct',
    '背包資料尚未同步或不可靠': 'BagNotReadyOrReliable',
    '等待儲藏存取確認，結果不明時請重新登入同步': 'StoragePendingOrUncertain',
    '使用的背包格數過多': 'TooManyBagRows',
}
CASES = []


def add(name, mutate=lambda data: None):
    data = base()
    mutate(data)
    groups = {}
    for row in data['recipes']:
        groups.setdefault(row['item_id'], []).append(row)
    products = {str(key): rows[0] for key, rows in groups.items() if len(rows) == 1}
    catalog = RecipeCatalog(data['recipes']) if data['recipes'] and data['recipes'][0].get('recipe_id') is not None else None
    state = SimpleNamespace(player={'role_id': data['role']}, **{key: copy.deepcopy(data[key])
        for key in ('crafting', 'furniture', 'inventory', 'room_storage')})
    before = copy.deepcopy(state.__dict__)
    input_before = copy.deepcopy(data)
    with patch.object(crafting, 'RECIPES', products), \
         patch.object(crafting, 'item_name', side_effect=lambda value: 'item:' + str(value)), \
         patch.object(crafting, 'active_recipe_catalog', return_value=catalog), \
         patch.object(crafting, 'Writer', side_effect=before_writer), \
         patch('wlre.services.items.crafting_official_v1286.build_add_packet', side_effect=before_writer), \
         patch.object(crafting, 'Packet', side_effect=AssertionError('Packet creation is outside this oracle')):
        try:
            crafting.recipe_plan(state, data['item_id'], data['count'])
            raise AssertionError('Missing packet boundary interception')
        except Captured as result:
            expected = {'blocker': None, **result.args[0]}
        except ProtocolError as error:
            message = str(error)
            blocker = ERRORS.get(message)
            if message.startswith('缺少已確認擺放的工作設備：'): blocker = 'MissingTool'
            if '材料不足；' in message: blocker = 'MaterialShortage'
            if blocker == 'UnknownRecipe' and len(groups.get(data['item_id'], [])) > 1: blocker = 'AmbiguousProduct'
            assert blocker is not None, message
            expected = {'blocker': blocker, 'message': message}
    assert before == state.__dict__, name
    assert input_before == data, name
    CASES.append({'name': name, 'input': data, 'expected': expected})


add('legacy_success')
add('official_identity_not_product', lambda d: d['recipes'][0].update(recipe_id=42, candidate_row_key=42))
add('empty_materials', lambda d: d['recipes'][0].update(materials=[]))
for key, value, name in [('read_only', True, 'readonly'), ('open_used', 1, 'closed'),
                          ('design_id', 5, 'design'), ('time_id', 5, 'time'), ('limit_kind', 1, 'limit')]:
    add(name, lambda d, k=key, v=value: d['recipes'][0].update({k: v}))
add('readonly_precedes_closed_and_count', lambda d: (d['recipes'][0].update(read_only=True, open_used=1), d.update(count=0)))
add('closed_precedes_count', lambda d: (d['recipes'][0].update(open_used=1), d.update(count=0)))
add('count_precedes_design', lambda d: (d['recipes'][0].update(design_id=1), d.update(count=0)))
for count in [-2147483648, -1, 0, 256, 2147483647]:
    add('invalid_count_' + str(count), lambda d, n=count: d.update(count=n))
add('unknown_product', lambda d: d.update(item_id=999))
add('room_not_ready', lambda d: d['furniture'].update(ready=False))
add('different_owner', lambda d: d['furniture'].update(owner=99))
add('null_owner_and_role_source_equality', lambda d: (d.update(role=None), d['furniture'].update(owner=None)))
add('current_owner_is_not_owner', lambda d: d['furniture'].update(current_owner=99))
add('workbench_does_not_match_tool', lambda d: d['furniture']['items']['9'].update(item_id=123, workbench=39001))
add('last_active_tool_in_insertion_order', lambda d: d['furniture']['items'].update({
    '2': {'index': 2, 'item_id': 39001, 'status': 0}, '8': {'index': 8, 'item_id': 39001, 'status': 1}}))
add('schedule_not_ready', lambda d: d['crafting'].update(ready=False))
add('pending_and_uncertain_are_observations', lambda d: d['crafting'].update(pending='add', uncertain=True))


def queue(data, count, duplicate=False):
    data['crafting']['queue'] = {str(i): {'index': i, 'item_id': 500 if duplicate else 600+i,
        'elapsed': 0, 'count': 1, 'base_time': 10} for i in range(1, count+1)}


def furniture(data, index, item_id):
    data['furniture']['items'][str(index)] = {'index': index, 'item_id': item_id, 'status': 0}


add('three_queue_full', lambda d: queue(d, 3))
add('capacity_five_four_used', lambda d: (queue(d, 4), furniture(d, 3, 39050)))
add('capacity_five_full', lambda d: (queue(d, 5), furniture(d, 3, 39050)))
add('duplicate_product_blocked', lambda d: queue(d, 1, True))
add('duplicate_product_allowed', lambda d: (queue(d, 1, True), furniture(d, 3, 39814)))
for key in ['ready', 'reliable']:
    add('bag_' + key, lambda d, k=key: d['inventory'].update({k: False}))
add('storage_pending_blocks_empty_materials', lambda d: (d['recipes'][0].update(materials=[]), d['room_storage'].update(pending='deposit')))
add('storage_uncertain', lambda d: d['room_storage'].update(uncertain=True))
add('empty_pending_string', lambda d: d['room_storage'].update(pending=''))
add('shortage', lambda d: d['inventory']['items'].clear())
for key in ['locked', 'enhance_level', 'magic_spar', 'beat_level']:
    add('quality_' + key, lambda d, k=key: d['inventory']['items']['2'].update({k: 1}))
for key in ['alchemy_slots', 'expedition_slots', 'maintenance_slots']:
    add('locked_projection_' + key, lambda d, k=key: d['inventory'].update({k: ['2']}))


def hold(data, bucket, exclusive=False, uncertain=False, remaining=0):
    target = data['inventory'] if bucket == 'bag' else data['room_storage']['materials']
    target['holds'] = {'storage': [{'index': '2', 'identity': [100, 1002, 1], 'count': 4,
                                   'remaining': remaining, 'before': 10, 'exclusive': exclusive, 'uncertain': uncertain}]}


add('exclusive_zero_hold', lambda d: hold(d, 'bag', exclusive=True))
add('uncertain_zero_hold', lambda d: hold(d, 'bag', uncertain=True))
add('nonexclusive_foreign_hold_is_not_acquire', lambda d: hold(d, 'bag', remaining=4))
add('reserved_counters', lambda d: d['inventory'].update(reserved={'2': 8}))
add('negative_reserved_preserves_source_arithmetic', lambda d: (d['inventory']['items']['2'].update(count=0), d['inventory'].update(reserved={'2': -10})))


def two_sources(data):
    data['recipes'][0]['materials'] = [{'item_id': 100, 'count': 3}, {'item_id': 200, 'count': 2}, {'item_id': 100, 'count': 2}]
    data['inventory']['items'] = {'10': item(10, count=2), '2': item(2, count=3), '9': item(9, 200, 1)}
    data['room_storage']['materials']['items'] = {'10': item(10, count=100), '2': item(2, count=2), '7': item(7, 200, 9)}


add('aggregate_duplicates_first_material_order_bag_first_numeric_slots', two_sources)
add('cupboard_unready', lambda d: (two_sources(d), d['room_storage']['materials'].update(ready=False)))
add('cupboard_unreliable', lambda d: (two_sources(d), d['room_storage']['materials'].update(reliable=False)))
add('cupboard_exclusive_zero_hold', lambda d: (two_sources(d), hold(d, 'materials', exclusive=True)))
add('cupboard_reserved', lambda d: (two_sources(d), d['room_storage']['materials'].update(reserved={'10': 99})))


def large(data):
    data['count'] = 255
    data['recipes'][0]['materials'] = [{'item_id': 100, 'count': 255}] * 5
    data['inventory']['items'] = {'2': item(count=100000)}
    data['room_storage']['materials']['items'] = {str(i): item(i, count=100000) for i in (10, 2, 99, 20, 30)}


add('caps_once_per_slot_and_current_before', large)
add('bag_cap_does_not_revisit_slot', lambda d: (d.update(count=2), d['recipes'][0].update(materials=[{'item_id': 100, 'count': 200}]), d['inventory']['items']['2'].update(count=1000)))
add('256_bag_rows_rejected', lambda d: (d.update(count=2), d['recipes'][0].update(materials=[{'item_id': 100, 'count': 128}]),
    d['inventory'].update(items={str(i): item(i, count=1) for i in range(256)})))
add('ambiguous_official_product', lambda d: d.update(recipes=[{**d['recipes'][0], 'recipe_id': 4}, {**d['recipes'][0], 'recipe_id': 9}]))
add('same_product_different_recipe_queue', lambda d: (d['recipes'][0].update(recipe_id=42), queue(d, 1, True), d['crafting']['queue']['1'].update(recipe_id=99)))

RNG = random.Random(64012026)
for iteration in range(96):
    def random_case(data):
        data['count'] = RNG.randint(1, 255)
        data['recipes'][0]['materials'] = [{'item_id': RNG.choice([100, 200, 300]), 'count': RNG.randint(1, 255)} for _ in range(RNG.randint(0, 5))]
        if RNG.randrange(2): data['recipes'][0]['recipe_id'] = RNG.randint(1, 65535)
        for bucket in [data['inventory'], data['room_storage']['materials']]:
            indices = RNG.sample(range(1, 32), 18)
            bucket['items'] = {str(i): item(i, RNG.choice([100, 200, 300]), RNG.randint(0, 30000)) for i in indices}
            bucket['reserved'] = {str(i): RNG.randint(0, 100) for i in indices[:5]}
            bucket['maintenance_slots'] = [str(i) for i in indices[5:8]]
        for row in list(data['inventory']['items'].values())[:5]: row[RNG.choice(['locked', 'magic_spar', 'enhance_level', 'beat_level'])] = 1
    add('seeded_' + str(iteration), random_case)

sources = ['wlre/services/items/crafting.py', 'wlre/services/items/crafting_official_v1286.py',
           'wlre/services/items/reservations.py', 'wlre/services/items/combat_resources.py',
           'wlre/services/items/inventory.py']
hashes = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
payload = base64.b64encode(gzip.compress(json.dumps(CASES, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0)).decode()
target = ROOT/'dotnet/Lala.Core.Tests/Inventory/CraftingPreflightPythonVectors.cs'
target.write_text('''// Generated by generate_crafting_preflight_vectors.py; real retained helper, synthetic inputs.
using System.IO.Compression;
using System.Text;
using System.Text.Json;
namespace Lala.Core.Tests.Inventory;
public static class CraftingPreflightPythonVectors
{
    public const string SourceSha256 = ''' + json.dumps(json.dumps(hashes, separators=(',', ':'))) + ''';
    public static IEnumerable<object[]> Cases()
    {
        using var input = new MemoryStream(Convert.FromBase64String("''' + payload + '''"));
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        using var reader = new StreamReader(gzip, Encoding.UTF8);
        using var document = JsonDocument.Parse(reader.ReadToEnd());
        foreach (var row in document.RootElement.EnumerateArray())
            yield return new object[] { row.GetProperty("name").GetString()!, row.GetRawText() };
    }
}
''', encoding='utf-8')
print(f'{len(CASES)} retained-helper vectors; {target.stat().st_size} generated bytes')
