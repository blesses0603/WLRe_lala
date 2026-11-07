"""Small offline unit_label / attack_lines oracle using the retained Python functions.

No copied formatter, catalog activation, transport, or UI. Run with --check to
verify the committed fixture without writing it. Inputs use received wire ranges.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import sys

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.services.battle import combat


MISSING = object()
cases = []


def effect(kind=25, value=1, sign=1, attribute=MISSING):
    result = {'kind': kind, 'value': value, 'sign': sign}
    if attribute is not MISSING:
        result['attribute'] = attribute
    return result


def target(col=1, row=1, attributes=()):
    return {'col': col, 'row': row, 'attack_result': 255, 'hit_action': 254,
            'attributes': list(attributes)}


def action(skill=10001, name=MISSING, targets=None, col=3, row=1):
    result = {'col': col, 'row': row, 'skill_id': skill, 'skill_level': 255,
              'fight_area': 254, 'targets': [target()] if targets is None else targets}
    if name is not MISSING:
        result['skill_name'] = name
    return result


def add(name, actions=(), state=None, labels=()):
    state = {} if state is None else state
    event = {'type': 'attack_result', 'actions': list(actions)}
    original = deepcopy((state, event))
    expected_labels = [{'col': col, 'row': row, 'expected': combat.unit_label(state, col, row)}
                       for col, row in labels]
    expected_lines = combat.attack_lines(event, state)
    assert (state, event) == original, 'Retained formatter mutated its inputs'
    cases.append({'name': name, 'state': state, 'event': event,
                  'labels': expected_labels, 'expected_lines': expected_lines})


add('no-actions-or-units', labels=[(0, 0), (255, 255), (3, 1)])
named = {'battle_units': {
    '3:1': {'name': '角色 星😀'}, '1:1': {'name': ''}, '1:2': {},
    '1:3': {'name': None}, '1:4': {'name': ' '},
    '0:255': {'name': 'A → B｜(0:255)、\n\t"quoted"'},
    '255:0': {'name': '同名'}, '255:255': {'name': '同名'}}}
add('names-are-verbatim-not-trimmed-or-reidentified', [action(targets=[
    target(1, 1), target(1, 2), target(1, 3), target(1, 4), target(0, 255),
    target(255, 0), target(255, 255), target(77, 88)])], named,
    [(3, 1), (1, 1), (1, 2), (1, 3), (1, 4), (0, 255), (255, 0), (255, 255), (77, 88)])

# Every fixed label must override a populated, empty, or missing received label.
for skill in [*combat.NORMALS, 60021, 60041, 10008]:
    for index, name in enumerate([MISSING, '', '不得覆蓋固定名稱']):
        add(f'fixed-skill-{skill}-fallback-{index}', [action(skill, name)])

for skill in [0, 10006, 60020, 60022, 60040, 60042, 65535]:
    for index, name in enumerate([MISSING, None, '', ' ', '自訂技能 星😀｜']):
        add(f'unknown-skill-{skill}-fallback-{index}', [action(skill, name)])

for sign in [0, 1, 2, 3, 4, 255]:
    add(f'effect-sign-{sign}-preserves-order-and-repeats', [action(65535, '效果', targets=[
        target(attributes=[effect(0, 0, sign, '不可顯示'), effect(25, 0, sign, 'ignored'),
                           effect(26, 4294967295, sign, 'ignored'), effect(0, 7, sign),
                           effect(255, 4294967295, sign, ''), effect(255, 3, sign, None),
                           effect(1, 1, sign, '自訂'), effect(1, 1, sign, '自訂')])])])

add('empty-and-no-op-effects-still-produce-one-line-per-target', [
    action(targets=[]), action(targets=[target(attributes=[]), target(attributes=[effect(0, 0)]),
        target(attributes=[effect(0, 0, 255, 'ignored'), effect(0, 0, 0, '')])])])
add('only-zero-kind-and-zero-value-is-omitted', [action(targets=[target(attributes=[
    effect(0, 0), effect(0, 1, 1, ' '), effect(25, 0), effect(26, 0),
    effect(255, 0, 1, ''), effect(1, 0, 1, '狀態')])])])
add('actions-targets-and-duplicates-are-not-sorted', [
    action(60041, targets=[target(255, 255), target(1, 4), target(255, 255)], col=255, row=0),
    action(60021, targets=[]), action(10008, targets=[target(3, 1)], col=1, row=4),
    action(60041, targets=[target(255, 255)], col=255, row=0)], named)

# Seeded mixed reports exercise cross-products rather than another implementation.
rng = random.Random(325031)
for index in range(16):
    actions = []
    for _ in range(rng.randrange(1, 4)):
        targets = []
        for _ in range(rng.randrange(4)):
            attributes = [effect(rng.choice([0, 1, 25, 26, 255]),
                                rng.choice([0, 1, 65535, 4294967295]),
                                rng.choice([0, 1, 2, 3, 255]),
                                rng.choice([MISSING, None, '', ' ', '灼傷😀']))
                          for _ in range(rng.randrange(5))]
            targets.append(target(rng.choice([0, 1, 3, 255]), rng.choice([0, 1, 4, 255]), attributes))
        actions.append(action(rng.choice([0, 10001, 10004, 60041, 65535]),
                              rng.choice([MISSING, None, '', ' ', '技能😀']), targets,
                              rng.choice([0, 1, 3, 255]), rng.choice([0, 1, 4, 255])))
    add(f'seeded-mixed-report-{index:02}', actions, named)

source = 'wlre/services/battle/combat.py'
source_hash = hashlib.sha256((ROOT / source).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
dump = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
data = '[\n' + ',\n'.join(dump(case) for case in cases) + '\n]'
output = f'''// Generated by generate_battle_display_vectors.py from retained Python, not C# output.
using System.Text.Json;

namespace Lala.Core.Tests.Battle;

public static class BattleDisplayPythonVectors
{{
    public const string SourcePath = "{source}";
    public const string SourceSha256 = "{source_hash}";
    public const int CaseCount = {len(cases)};
    public const int LabelCount = {sum(len(case['labels']) for case in cases)};
    public const int LineCount = {sum(len(case['expected_lines']) for case in cases)};

    public static IEnumerable<object[]> Cases()
    {{
        using var document = JsonDocument.Parse(Data);
        foreach (var row in document.RootElement.EnumerateArray())
            yield return [row.GetProperty("name").GetString()!, row.GetRawText()];
    }}

    private const string Data = """"
{data}
"""";
}}
'''
raw = output.encode('utf-8')
assert len(raw.replace(b'\n', b'\r\n')) <= 500000
destination = Path(__file__).with_name('BattleDisplayPythonVectors.cs')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true')
if parser.parse_args().check:
    if not destination.exists() or destination.read_bytes().replace(b'\r\n', b'\n') != raw:
        raise SystemExit('Battle display fixture is stale; rerun the generator.')
else:
    destination.write_bytes(raw)
print(f'{len(cases)} cases, {sum(len(c["labels"]) for c in cases)} labels, '
      f'{sum(len(c["expected_lines"]) for c in cases)} lines; '
      f'{len(raw)} LF bytes / {len(raw.replace(bytes([10]), bytes([13, 10])))} CRLF bytes')
