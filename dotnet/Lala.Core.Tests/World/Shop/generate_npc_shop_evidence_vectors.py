"""Deterministic, synthetic, offline source oracle. No commands, network or settlement."""
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import csharp_gzip_json
from wlre.services.world import npc_shop_evidence as source

RNG = random.Random(202611080201)
BUY = dict(kind='buy', start_packet=10, item_id=42, count=2, expected_gold_delta=-1500)
SELL = dict(kind='sell', start_packet=10, item_id=42, count=2, expected_gold_delta=1500, bag_slot=7)
SEQUENCES, CASES = [], []
MISSING = object()


def outcome(evidence, order):
    try:
        return dict(expected=source.classify(evidence, **order))
    except Exception as exc:
        return dict(error_type=type(exc).__name__, error=str(exc))


def encode(value):
    if isinstance(value, tuple): return {'$tuple': [encode(v) for v in value]}
    if isinstance(value, float) and not math.isfinite(value): return {'$float': str(value)}
    if isinstance(value, dict): return {k: encode(v) for k, v in value.items()}
    if isinstance(value, list): return [encode(v) for v in value]
    return value


def case(name, entries=None, order=None, evidence=MISSING):
    order = copy.deepcopy(BUY if order is None else order)
    evidence = copy.deepcopy(dict(events=entries or []) if evidence is MISSING else evidence)
    CASES.append((name, encode(dict(evidence=evidence, order=order, **outcome(evidence, order)))))


def row(kind, packet=11, **fields):
    return dict(packet=packet, type=kind, inventory_revision=3, gold_revision=5,
                inventory_reliable=True, gold_reliable=True, **fields)


def buy_rows():
    return [row('gold_delta', 11, delta=-1500), row('bag_add', 12, item_id=42, count=2, index=7),
            row('shop_purchase_result', 13, result=0)]


def sell_rows():
    return [row('gold_delta', 11, delta=1500), row('bag_sell', 12, index=7, count=2, s27_gold_field=999999),
            row('sale_notice', 13, result=1)]


class Sequence:
    def __init__(self, name, revision=0):
        self.name = name
        self.state = SimpleNamespace(shop_evidence=source.defaults(), packet_count=10,
            inventory=dict(ready=True, reliable=True, revision=revision),
            gold=dict(ready=True, reliable=True, revision=revision))
        self.steps = [self.project(None)]

    def project(self, event):
        return dict(event=event, packet=self.state.packet_count, inventory=copy.deepcopy(self.state.inventory),
            gold=copy.deepcopy(self.state.gold), expected=copy.deepcopy(self.state.shop_evidence),
            buy=outcome(self.state.shop_evidence, BUY), sell=outcome(self.state.shop_evidence, SELL))

    def observe(self, event, packet=None):
        self.state.packet_count = self.state.packet_count + 1 if packet is None else packet
        source.observe(self.state, event)
        self.steps.append(self.project(event))
        return self

    def finish(self): SEQUENCES.append((self.name, self.steps))


EVENTS = [dict(type='bag_snapshot', capacity=255, items=[dict(private_token='DO_NOT_RETAIN')]),
    dict(type='bag_add', item=dict(index=255, item_id=65535, count=255, private_token='DO_NOT_RETAIN'), source=65535),
    dict(type='bag_delete', index=0, count=0), dict(type='bag_sell', gold=0xffffffff, index=255, count=255),
    dict(type='gold_snapshot', amount=0xffffffff), dict(type='gold_delta', delta=-0xffffffff),
    dict(type='gold_limit'), dict(type='shop_purchase_result', result=255), dict(type='sale_notice', result=255),
    dict(type='unimplemented'), dict(type='event_end'), dict(type='role_list_available'), dict(type='login_result', result=255)]
for flags in itertools.product([False, True], repeat=4):
    s = Sequence('post_handler_ready_reliable_' + ''.join(str(int(x)) for x in flags), 2**100)
    s.state.inventory.update(ready=flags[0], reliable=flags[1])
    s.state.gold.update(ready=flags[2], reliable=flags[3])
    for event in EVENTS: s.observe(event)
    s.finish()
for mode in ['buy', 'sell']:
    events = ([dict(type='gold_delta', delta=-1500), dict(type='bag_add', item=dict(index=7, item_id=42, count=2)),
        dict(type='shop_purchase_result', result=0)] if mode == 'buy' else
        [dict(type='gold_delta', delta=1500), dict(type='bag_sell', gold=99999, index=7, count=2), dict(type='sale_notice', result=1)])
    for number, sequence in enumerate(itertools.permutations(events)):
        s = Sequence(f'{mode}_receive_order_{number}')
        for event in sequence: s.observe(event)
        s.finish()
s = Sequence('retention_96_97_150_ignored_and_both_reset_events', 2**130)
for i in range(150): s.observe(dict(type='gold_delta', delta=i - 75))
s.observe(dict(type='unimplemented')).observe(dict(type='role_list_available'))
s.observe(dict(type='bag_add', item=dict(index=None, item_id=0, count=0)))
s.observe(dict(type='login_result', result=0)).observe(dict(type='login_result', result=1)).finish()
s = Sequence('arbitrary_precision_packet_counters_and_synthetic_delta_extremes', 2**200)
for delta in [-(2**63), 2**63-1, 0]: s.observe(dict(type='gold_delta', delta=delta), 2**180)
s.finish()
for i in range(20):
    s = Sequence(f'random_observation_history_{i}')
    for j in range(35):
        s.state.inventory.update(ready=RNG.choice([True, False]), reliable=RNG.choice([True, False]), revision=RNG.randrange(2**80))
        s.state.gold.update(ready=RNG.choice([True, False]), reliable=RNG.choice([True, False]), revision=RNG.randrange(2**80))
        s.observe(copy.deepcopy(RNG.choice(EVENTS)))
    s.finish()

case('missing_events_defaults', evidence={})
case('buy_consistent', buy_rows())
case('sell_consistent', sell_rows(), SELL)
for mode, rows, order in [('buy', buy_rows(), BUY), ('sell', sell_rows(), SELL)]:
    for size in range(4):
        for subset in itertools.combinations(rows, size):
            for perm in itertools.permutations(subset):
                renumbered = [dict(r, packet=11+i) for i, r in enumerate(perm)]
                case(f'{mode}_subset_{len(CASES)}', renumbered, order)
    for field, values in {
        'kind': [None, True, 1, '', 'BUY', 'sale', [], {}],
        'start_packet': [None, True, False, 10.0, '10', -1, 2**200, [], {}],
        'item_id': [None, True, 42.0, '42', 0, -1, 1, 65535, 65536, 2**200],
        'count': [None, True, 2.0, '2', 0, -1, 1, 255, 256, 2**200],
        'expected_gold_delta': [None, True, -1500.0, '1500', 0, -0xffffffff, 0xffffffff, -2**32, 2**32, 2**200],
        'bag_slot': [None, True, 7.0, '7', 0, -1, 255, 256, 2**200, [], {}],
    }.items():
        for value in values:
            changed = dict(order, **{field:value})
            case(f'{mode}_descriptor_{field}_{len(CASES)}', rows, changed)
    for position, original in enumerate(rows):
        for field, values in {
            'packet': [None, True, 11.0, '11', -1, 0, 10, 11, 12, 2**200],
            'type': [None, True, 1, '', 'ignored', 'gold_delta', 'bag_snapshot', 'gold_snapshot', 'gold_limit',
                     'bag_add', 'bag_delete', 'bag_sell', 'shop_purchase_result', 'sale_notice', [], {}],
            'inventory_reliable': [None, False, 0, 0.0, '', [], {}, 1, 'yes', [0], {'x':0}],
            'gold_reliable': [None, False, 0, '', [], {}, True, 1, [0]],
            'count': [None, False, True, 2.0, '2', -1, 0, 1, 2, 3, 2**200],
            'index': [None, False, True, 7.0, '7', -1, 0, 7, 8, 255, 2**200],
            'item_id': [None, False, True, 42.0, '42', 0, 42, 43, 65535],
            'delta': [None, False, True, -1500.0, 1500.0, '1500', 0, -1500, 1500, 2**200],
            'result': [None, False, True, 0.0, 1.0, '0', -1, 0, 1, 2, 255],
        }.items():
            for value in values:
                changed = copy.deepcopy(rows); changed[position][field] = value
                case(f'{mode}_row{position}_{field}_{len(CASES)}', changed, order)
            changed = copy.deepcopy(rows); changed[position].pop(field, None)
            case(f'{mode}_row{position}_missing_{field}', changed, order)
    for extra in [row('gold_delta', 14, delta=1), row('bag_add',14,item_id=42,count=1), row('bag_delete',14,index=7,count=2),
                  row('bag_sell',14,index=7,count=2), row('shop_purchase_result',14,result=0), row('sale_notice',14,result=1),
                  row('gold_snapshot',14,amount=100), row('bag_snapshot',14,capacity=40), row('gold_limit',14)]:
        case(f'{mode}_extra_{extra["type"]}', rows+[extra], order)
    for packet in [10, 11, 12, 2**130]:
        case(f'{mode}_stale_first_{packet}', [dict(rows[0],packet=packet)]+rows[1:], order)
    for result in [0, 1, 2, 255, None]:
        rejection = dict(rows[2],packet=11,result=result)
        for extra in [[], [row('gold_snapshot',12)], [row('bag_snapshot',12)], [row('gold_limit',12)], [rows[0]], [rows[1]]]:
            case(f'{mode}_rejection_precedence_{len(CASES)}', [rejection]+extra, order)

for value in [None, False, 0, '', {}, (), tuple(buy_rows()), [None], [False], [0], ['x'], [[]]]:
    case(f'invalid_evidence_shape_{len(CASES)}', evidence={'events': value})
for value in [None, False, 0, '', [], ()]: case(f'invalid_evidence_map_{len(CASES)}', evidence=value)
for length in [95, 96, 97, 150]: case(f'raw_retention_length_{length}', [row('ignored',11) for _ in range(length)])
case('window_gap_precedes_invalid_later_row', evidence={'events':[row('ignored',12),None]})
case('window_gap_not_inferred_from_later_rows', [row('ignored',None),row('gold_delta',100,delta=-1500)])
case('exact_huge_start_plus_one', [row('shop_purchase_result',2**200+1,result=0)], dict(BUY,start_packet=2**200))
case('huge_start_plus_two_stale', [row('shop_purchase_result',2**200+2,result=0)], dict(BUY,start_packet=2**200))
case('buy_split_counts', [row('bag_add',11,item_id=42,count=1),row('bag_add',12,item_id=42,count=1),buy_rows()[0],buy_rows()[2]])
case('buy_large_total_no_overflow', [row('bag_add',11,item_id=42,count=2**200)])
case('sell_bool_and_float_equality', [row('gold_delta',11,delta=1.0),row('bag_sell',12,index=False,count=True),row('sale_notice',13,result=True)], dict(SELL,count=1,bag_slot=0,expected_gold_delta=1))
for value in [float('nan'), float('inf'), float('-inf'), -0.0]:
    for field in ['result', 'delta', 'count', 'inventory_reliable']:
        rows=buy_rows(); rows[{'result':2,'delta':0,'count':1,'inventory_reliable':1}[field]][field]=value
        case(f'nonfinite_{field}_{len(CASES)}',rows)
    case(f'nonfinite_descriptor_{len(CASES)}',buy_rows(),dict(BUY,expected_gold_delta=value))
for i in range(300):
    kind = RNG.choice(['buy','sell']); order = BUY if kind=='buy' else SELL
    rows = copy.deepcopy(buy_rows() if kind=='buy' else sell_rows())
    for _ in range(RNG.randrange(1,5)):
        op = RNG.randrange(5)
        if op == 0 and rows: rows.pop(RNG.randrange(len(rows)))
        elif op == 1 and rows: rows.insert(RNG.randrange(len(rows)+1),copy.deepcopy(RNG.choice(rows)))
        elif op == 2: RNG.shuffle(rows)
        elif op == 3: rows.append(row(RNG.choice(['gold_limit','bag_snapshot','ignored','shop_purchase_result','sale_notice']),RNG.randrange(8,15),result=RNG.randrange(3)))
        elif rows: RNG.choice(rows)[RNG.choice(['packet','gold_reliable','count','delta'])] = RNG.choice([None,False,0,1,12,42,1500])
    case(f'random_classification_{i}',rows,order)

hashes = {path:hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
          for path in ['wlre/services/world/npc_shop_evidence.py']}
MAX_OUTPUT_BYTES = 500_000
HEADER = ('// Generated by generate_npc_shop_evidence_vectors.py. Do not edit.\n'
          'namespace Lala.Core.Tests.World.Shop;\n\n'
          'public static partial class NpcShopEvidencePythonVectors\n{\n')
outputs = {'NpcShopEvidencePythonVectors.cs': HEADER +
    '    public const string SourceSha256 = "' + json.dumps(json.dumps(hashes,separators=(',',':')))[1:-1] + '";\n}\n'}
for name, values in [('Sequences',SEQUENCES),('Classifications',CASES)]:
    payload=json.dumps(values,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    output = HEADER + f'    private static readonly string {name}Json = ' + csharp_gzip_json(payload) + ';\n'
    output += f'    public static IEnumerable<object[]> {name}()\n    {{\n        foreach (var row in System.Text.Json.Nodes.JsonNode.Parse({name}Json)!.AsArray())\n            yield return [row![0]!.GetValue<string>(), row[1]!.ToJsonString()];\n    }}\n'
    outputs[f'NpcShopEvidencePythonVectors.{name}.cs'] = output + '}\n'
# Validate every file before writing any output. Keep the existing gzip streams intact.
for filename, output in outputs.items():
    size = len(output.encode('utf-8'))
    if size > MAX_OUTPUT_BYTES:
        raise ValueError(f'{filename}: {size} bytes exceeds the {MAX_OUTPUT_BYTES}-byte publication cap')
for filename, output in outputs.items():
    Path(__file__).with_name(filename).write_text(output,encoding='utf-8',newline='\n')
print(f'{len(SEQUENCES)} histories; {sum(len(s) for _,s in SEQUENCES)} full snapshots; {len(CASES)} classifications')
print('; '.join(f'{filename}: {len(output.encode("utf-8"))} bytes' for filename, output in outputs.items()))
