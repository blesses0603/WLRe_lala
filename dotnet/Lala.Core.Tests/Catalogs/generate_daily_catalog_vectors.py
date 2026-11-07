"""Synthetic differential fixtures from the retained daily-task parsers/binder only.

No game resources, network, filesystem loaders, source-verification overrides or
runtime activation. Run from any directory; emits the sibling C# fixture file.
"""
import base64
import json
from pathlib import Path
import random
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.services.world.daily_task_1275 import parse_daily_tasks
from wlre.services.world.daily_task_catalog import bind_catalog, goal, parse_rewards


def award(kind=12, ident=1, value=10):
    return dict(kind=kind, id=ident, value=value)


def task(**changes):
    result = dict(index=1, group=1, id=1, mission_name_text_id=38681,
                  condition_kind=1, condition_params=[7, 8, 9], function_kind=13,
                  function_arg1=17, function_arg2=19, awards=[award(), award(0, 0, 0)])
    result.update(changes)
    return result


def reward(**changes):
    result = dict(id=1, kind=1, value=30, mark=1,
                  awards=[award(), award(0, 0, 0), award(0, 0, 0), award(0, 0, 0)])
    result.update(changes)
    return result


def task_bytes(groups=None, tasks=None):
    if groups is None:
        groups = [(1, 1, 1)]
    if tasks is None:
        tasks = [task()]
    data = bytearray(struct.pack('<i', len(groups)))
    for group in groups:
        data += struct.pack('<3B', *group)
    data += struct.pack('<i', len(tasks))
    for row in tasks:
        data += struct.pack('<HBBIB3H3B', row['index'], row['group'], row['id'],
                            row['mission_name_text_id'], row['condition_kind'],
                            *row['condition_params'], row['function_kind'],
                            row['function_arg1'], row['function_arg2'])
        for item in row['awards']:
            data += struct.pack('<BII', item['kind'], item['id'], item['value'])
    return bytes(data)


def reward_bytes(rows=None):
    if rows is None:
        rows = [reward()]
    data = bytearray(struct.pack('<i', len(rows)))
    for row in rows:
        data += struct.pack('<HBII', row['id'], row['kind'], row['value'], row['mark'])
        for item in row['awards']:
            data += struct.pack('<BII', item['kind'], item['id'], item['value'])
    return bytes(data)


def expected(fn, *args):
    try:
        return json.dumps(fn(*args), ensure_ascii=True, separators=(',', ':'))
    except ValueError:
        return None


def b64(raw):
    return base64.b64encode(raw).decode('ascii')


cases = dict(Tasks=[], Rewards=[], Bind=[], Goals=[])


def add_task(name, data):
    cases['Tasks'].append([name, b64(data), expected(parse_daily_tasks, data)])


def add_reward(name, data):
    cases['Rewards'].append([name, b64(data), expected(parse_rewards, data)])


def add_bind(name, groups=None, tasks=None, rewards=None, texts=None, items=None):
    data = task_bytes(groups, tasks)
    reward_data = reward_bytes(rewards)
    if texts is None:
        texts = {38681: ' 任務😀\n'}
    if items is None:
        items = set()
    output = expected(bind_catalog, parse_daily_tasks(data), parse_rewards(reward_data), texts, items)
    cases['Bind'].append([name, b64(data), b64(reward_data),
                          json.dumps(texts, ensure_ascii=True), json.dumps(sorted(items)), output])


base = task_bytes()
add_task('one', base)
add_task('empty', task_bytes([], []))
add_task('groups-only', task_bytes([(0, 1, 0), (255, 2, 255)], []))
add_task('missing-groups-sorted-distinct', task_bytes([], [task(group=g, index=i) for i, g in enumerate([255, 9, 9, 0])]))
add_task('cross-group-index', task_bytes([(1, 1, 1), (1, 2, 2)], [task(), task(group=2)]))
add_task('zero-indices-parser-only', task_bytes(tasks=[task(index=0, id=0)]))
add_task('max-fields', task_bytes([(255, 2, 255)], [task(index=65535, group=255, id=255,
    mission_name_text_id=4294967295, condition_kind=255, condition_params=[65535]*3,
    function_kind=255, function_arg1=255, function_arg2=255, awards=[award(255, 4294967295, 4294967295)]*2)]))
add_task('duplicate-index', task_bytes(tasks=[task(), task(id=2)]))
add_task('duplicate-groups', task_bytes([(1, 1, 1), (9, 2, 1)]))
for cycle in [0, 3, 255]:
    add_task('bad-cycle-' + str(cycle), task_bytes([(1, cycle, 1)]))
for offset in range(len(base)):
    add_task('truncated-' + str(offset), base[:offset])
for tail in [b'\0', b'\xff'*36]:
    add_task('tail-' + str(len(tail)), base + tail)
for count in [-2147483648, -1, 1, 999, 1000, 1001, 2147483647]:
    add_task('group-count-' + str(count), struct.pack('<ii', count, 0))
for count in [-2147483648, -1, 1, 49999, 50000, 50001, 2147483647]:
    add_task('task-count-' + str(count), struct.pack('<ii', 0, count))

base_reward = reward_bytes()
add_reward('one', base_reward)
add_reward('all-kinds-marks', reward_bytes([reward(id=m, kind=k, mark=m, value=4294967295) for k in range(1, 5) for m in range(1, 9)]))
add_reward('wide-awards', reward_bytes([reward(id=65535, value=4294967295, awards=[award(255, 4294967295, 4294967295)]*4)]))
for key, values in [('id', [0]), ('kind', [0, 5, 255]), ('mark', [0, 9, 4294967295]), ('value', [0])]:
    for value in values:
        add_reward('bad-' + key + '-' + str(value), reward_bytes([reward(**{key: value})]))
add_reward('duplicate-id', reward_bytes([reward(), reward(mark=2)]))
add_reward('duplicate-mark', reward_bytes([reward(), reward(id=2)]))
add_reward('same-id-different-kind', reward_bytes([reward(), reward(kind=2)]))
for offset in range(len(base_reward)):
    add_reward('truncated-' + str(offset), base_reward[:offset])
add_reward('tail', base_reward + b'\0')
for count in [-2147483648, -1, 0, 1, 999, 1000, 1001, 2147483647]:
    add_reward('count-' + str(count), struct.pack('<i', count))

add_bind('one')
add_bind('wide-bound-identifiers', groups=[(1, 2, 255)], tasks=[task(index=65535, group=255, id=12, mission_name_text_id=4294967295)], texts={4294967295: '最大'})
add_bind('zero-group-is-allowed', groups=[(1, 1, 0)], tasks=[task(group=0)])
add_bind('wide-reward-threshold', rewards=[reward(id=65535, kind=4, mark=8, value=4294967295)])
add_bind('weekly-twelfth', groups=[(1, 2, 1)], tasks=[task(id=12)])
add_bind('daily-eighth', tasks=[task(id=8)])
add_bind('empty-tasks', groups=[], tasks=[])
add_bind('missing-group', groups=[])
add_bind('non-daily-only', groups=[(2, 1, 1)])
add_bind('skip-non-daily-before-metadata', groups=[(1, 1, 1), (255, 2, 2)],
         tasks=[task(), task(group=2, index=0, id=0, mission_name_text_id=999, awards=[award(10, 999), award(11, 998)])])
for ident in [0, 9, 255]:
    add_bind('daily-slot-' + str(ident), tasks=[task(id=ident)])
for ident in [0, 13, 255]:
    add_bind('weekly-slot-' + str(ident), groups=[(1, 2, 1)], tasks=[task(id=ident)])
add_bind('zero-index', tasks=[task(index=0)])
add_bind('duplicate-slot', tasks=[task(), task(index=2)])
add_bind('duplicate-global-index', groups=[(1, 1, 1), (1, 2, 2)], tasks=[task(), task(group=2)])
add_bind('slots-distinct-groups', groups=[(1, 1, 1), (1, 2, 2)], tasks=[task(), task(group=2, index=2)])
add_bind('missing-name', texts={})
for index, text in enumerate([None, '', ' ', '\t\r\n', '\u001c\u001d\u001e\u001f', '\u0085\u00a0\u3000', '\ufeff', '\u200b', '\x00', ' X ', '\u001cX\u001f']):
    add_bind('name-' + str(index), texts={38681: text})
for kind in [0, 1, 10, 11, 12, 255]:
    for ident in [0, 42, 4294967295]:
        awards = [award(kind, ident, 0), award(0, 0, 0)]
        add_bind(f'task-item-missing-{kind}-{ident}', tasks=[task(awards=awards)])
        add_bind(f'task-item-present-{kind}-{ident}', tasks=[task(awards=awards)], items={ident})
        add_bind(f'chest-item-missing-{kind}-{ident}', rewards=[reward(awards=awards*2)])
        add_bind(f'chest-item-present-{kind}-{ident}', rewards=[reward(awards=awards*2)], items={ident})

rng = random.Random(1275)
for index in range(40):
    rows = [task(index=n+1, id=n+1, condition_kind=rng.randrange(256),
                 condition_params=[rng.randrange(65536) for _ in range(3)],
                 function_kind=rng.randrange(256), function_arg1=rng.randrange(256), function_arg2=rng.randrange(256),
                 awards=[award(rng.choice([0,1,12,255]), rng.randrange(2**32), rng.randrange(2**32)) for _ in range(2)])
            for n in range(rng.randint(1, 8))]
    add_task('random-' + str(index), task_bytes(tasks=rows))
    add_bind('random-' + str(index), tasks=rows)
for kind in range(256):
    for first, second, third in [(0,0,0), (1,2,3), (6,65535,65534), (4,2,65535)]:
        cases['Goals'].append([kind, first, second, third, goal(dict(condition_kind=kind, condition_params=[first, second, third]))])
for first in [2,3,5,7,65535]:
    cases['Goals'].append([13, first, 12, 34, goal(dict(condition_kind=13, condition_params=[first,12,34]))])

assert len(parse_daily_tasks(task_bytes([], [task(index=i, group=0) for i in range(50000)]))['tasks']) == 50000
assert len(parse_daily_tasks(task_bytes([(1, 2, i) for i in range(256)], []))['groups']) == 256
for count in (257, 1000):
    assert expected(parse_daily_tasks, task_bytes([(1, 1, i % 256) for i in range(count)], [])) is None
assert expected(parse_rewards, reward_bytes([reward(id=i+1, mark=i%8+1) for i in range(1000)])) is None

lines = ['// Generated by generate_daily_catalog_vectors.py from retained Python. Synthetic data only.',
         'namespace Lala.Core.Tests.Catalogs;', 'public static class PythonDailyCatalogVectors', '{']
for name, rows in cases.items():
    lines += [f'    public static IEnumerable<object?[]> {name}()', '    {']
    for row in rows:
        values = ['null' if x is None else json.dumps(x, ensure_ascii=True) for x in row]
        lines.append('        yield return new object?[] { ' + ', '.join(values) + ' };')
    lines += ['    }']
lines += ['}']
Path(__file__).with_name('PythonDailyCatalogVectors.cs').write_text('\n'.join(lines) + '\n')
print({name: len(rows) for name, rows in cases.items()})
