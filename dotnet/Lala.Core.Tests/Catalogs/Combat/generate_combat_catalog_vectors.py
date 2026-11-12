"""Retained combat_catalog Python oracle. Synthetic pin substitution is test-only.

Never executes Lua, downloads assets, activates caches, or changes production pins.
Raw Python results/errors are retained separately from explicit typed C# deltas.
"""
from contextlib import ExitStack
import base64
import hashlib
import json
from pathlib import Path
import random
import struct
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dotnet/Lala.Core.Tests/TestSupport'))
from gzip_json_fixture import gzip_json_bytes
from wlre.services import parser_diagnostics as diagnostics
from wlre.services.world import combat_catalog as source, normal_attack_catalog as normal, itemdata_v1 as items
from wlre.services.world.official_lua_codec import KNOWN_FILES

PINS = (source.SKILL_SHA256, normal.NPC_SHA256, source.ITEMDATA_1296_SHA256,
        items.ITEMDATA_1296_SHA256, KNOWN_FILES.copy())
u16 = lambda value: struct.pack('<H', value)
u32 = lambda value: struct.pack('<I', value)
text = lambda value: u16(len(value.encode('utf-16-le'))) + value.encode('utf-16-le')
table = lambda *records: u32(len(records)) + b''.join(records)


def npc(ident=321, name='NPC私密😀\0\0', skills=(101, 0, 65535, 4, 5)):
    fields = bytearray(bytes([0xa5]) * 203)
    struct.pack_into('<H', fields, 1, ident)
    struct.pack_into('<5H', fields, 75, *skills)
    return text(name) + text('別名\0') + fields


def item(ident=100, name='物品😀\0', kind=5, fit=3, special=140, link=101, restrict=65535):
    data = bytearray(text(name) + bytes([kind]) + text(''))
    data += struct.pack('<4H', ident, 7, 8, 9) + bytes(8)
    data += struct.pack('<HBiHBi', 25, 2, -2**31, 26, 255, 2**31-1)
    data += bytes([3, 4, fit, special]) + bytes(64)
    data += struct.pack('<BBII', 1, 2, 17, 9) + bytes(1) + u16(restrict) + bytes(9)
    data += struct.pack('<6H', link, 1, 2, 3, 4, 5)
    data += u16(2) + b'\x00\xd8'  # Source intentionally skips invalid description Unicode.
    data += bytes([1, 2, 3]) + bytes(2) + bytes([4, 5]) + bytes(15)
    data += struct.pack('<3H', 0, 0, 0) + bytes(33)
    data += bytes([2]) + bytes(24) + b'\x12\x34'
    return bytes(data)


def skill(ident=101, name=1001, key=11, values=None):
    row = dict(ID=ident, Name=name, Key=key, LvLimit=7, TargetKind=1)
    row.update(values or {})
    return struct.pack('<' + ''.join(kind for _, kind in source.SKILL_FIELDS),
                       *(row.get(field, 0) for field, _ in source.SKILL_FIELDS))


labels = ['None', 'Earth', 'Water', 'Fire', 'Wind']
define = 'EElementType = {' + ','.join(f'{label}={i}' for i, label in enumerate(labels)) + '}\n'
define += 'ERoleType={Male=1,Female=2}\nCHARACTER_DATAS={\n'
define += ',\n'.join(f'[{i}]={{sex=ERoleType.{"Male" if i % 2 else "Female"},headStyle={i},firstSkill={100+i},InitialEquip={200+i}}}' for i in range(1, 16)) + '\n}'
fight = 'elementAttackTimes={\n' + ',\n'.join('[EElementType.' + label + ']={' + ','.join(
    f'[EElementType.{other}]={1 + i/10 + j/100:.2f}' for j, other in enumerate(labels)) + '}'
    for i, label in enumerate(labels)) + '\n}'
skill_raw, npc_raw, item_raw = table(skill()), table(npc()), table(item())
texts = {1001: '  技能😀\0  ', 1002: '二'}
cases = []


def add(name, mode='constants-layout', d=define, f=fight, sk=skill_raw, np=npc_raw, it=item_raw,
        names=None, target=None, typed_error=None, projection_error=None):
    result = error = None
    run = diagnostics.DiagnosticRun('unused-in-memory-oracle')
    token = diagnostics._run.set(run)
    try:
        with ExitStack() as stack:
            if mode.endswith('-layout'):
                stack.enter_context(patch.dict(KNOWN_FILES, {
                    'Define.lua': ('unused-cipher', hashlib.sha256(d.encode()).hexdigest()),
                    'FightUnit.lua': ('unused-cipher', hashlib.sha256(f.encode()).hexdigest())}))
                if mode.startswith('build'):
                    stack.enter_context(patch.object(source, 'SKILL_SHA256', hashlib.sha256(sk).hexdigest()))
                    stack.enter_context(patch.object(normal, 'NPC_SHA256', hashlib.sha256(np).hexdigest()))
                    for module in (source, items):
                        stack.enter_context(patch.object(module, 'ITEMDATA_1296_SHA256', hashlib.sha256(it).hexdigest()))
            try:
                if mode.startswith('block'):
                    result = source._block(d, target)
                elif mode.startswith('enum'):
                    result = source._enum(d, target)
                elif mode.startswith('constants'):
                    characters, weights = source.parse_constants(d, f)
                    result = dict(characters=characters, element_weights=weights)
                else:
                    def build():
                        return source.build_catalog(sk, np, it, texts if names is None else names,
                                                    {'Define.lua': d, 'FightUnit.lua': f})
                    if mode == 'build-nested-layout':
                        def parent():
                            diagnostics.checkpoint(offset=7, field='outer')
                            return build()
                        parent.__module__ = 'synthetic'
                        parent.__name__ = 'combat_parent'
                        parent.__qualname__ = 'combat_parent'
                        result = diagnostics.diagnosed('parent-v1')(parent)()
                    else:
                        result = build()
            except (ValueError, KeyError, struct.error) as failure:
                error = {'type': type(failure).__name__, 'message': str(failure)}
        events = list(run.events.values())
        cases.append(dict(name=name, mode=mode, define=d, fight=f, target=target,
            skill=base64.b64encode(sk).decode() if mode.startswith('build') else None,
            npc=base64.b64encode(np).decode() if mode.startswith('build') else None,
            item=base64.b64encode(it).decode() if mode.startswith('build') else None,
            texts={str(k): v for k, v in (texts if names is None else names).items()},
            raw_expected=result, raw_error=error, typed_error=typed_error,
            projection_error=projection_error, raw_diagnostics=events))
    finally:
        diagnostics._run.reset(token)
    assert PINS == (source.SKILL_SHA256, normal.NPC_SHA256, source.ITEMDATA_1296_SHA256,
                    items.ITEMDATA_1296_SHA256, KNOWN_FILES)


add('base-constants')
add('base-catalog', 'build-layout')
for d, name in [('T={a={x=1},b=2} tail', 'nested'), ('T={"{"}', 'quoted-open-brace'),
                ('T={-- } rest}', 'comment-close-brace'), ('AT={wrong} T={good}', 'word-boundary'),
                ('T = {first} T={second}', 'first-assignment'), ('T={}', 'empty'),
                ('T={a={}', 'unterminated'), ('no table here', 'missing'),
                ('éT={wrong} .T={good}', 'unicode-word-boundary'), ('😀T={yes}', 'emoji-boundary'),
                ('𝔸T={wrong} T={good}', 'astral-word-boundary'), ('T\x1c=\x1f{ok}', 'python-whitespace'),
                ('a.b = {yes}', 'escaped-name')]:
    add('block-' + name, 'block-layout', d=d, target='a.b' if name == 'escaped-name' else 'T')
for d, name in [('T={A=1,B=2}', 'basic'), ('T={A=1,A=2}', 'duplicate'), ('T={A=1,B=1}', 'numeric-alias'),
                ('T={A=-1,B=1.5,C=2e3,D=0x10}', 'numeric-prefixes'), ('T={Á=1,字=２,𝔸=٣,²=4}', 'unicode'),
                ('T={Á=1,A=2}', 'combining-mark-not-word'), ('T={1name=12}', 'digit-name'),
                ('T={A=1,A=1}', 'duplicate-same-value'), ('T={A=1,a=2}', 'case-sensitive'),
                ('T={-- A=1\n B=2}', 'comment-not-removed'), ('T={ A=\x1c12 }', 'whitespace'),
                ('T={}', 'empty'), ('T={a={B=2}}', 'nested')]:
    add('enum-' + name, 'enum-layout', d=d, target='T')
add('enum-big-integer', 'enum-layout', d='T={A=' + '9'*100 + '}', target='T')
add('enum-decimal-limit', 'enum-layout', d='T={A=' + '9'*4301 + '}', target='T',
    typed_error='Combat integer exceeds decimal digit limit')
for needle, name in [('EElementType', 'elements'), ('ERoleType', 'sex'), ('CHARACTER_DATAS', 'characters')]:
    add('missing-' + name, d=define.replace(needle, 'missing' + needle, 1))
add('missing-matrix', f=fight.replace('elementAttackTimes', 'missingMatrix', 1))
add('duplicate-element-key', d=define.replace('None=0', 'None=0,None=1'))
add('duplicate-sex-key', d=define.replace('Male=1', 'Male=1,Male=1'))
add('element-alias-last-row', d=define.replace('Wind=4', 'Wind=4,Alias=0'),
    f=fight[:-1] + ',[EElementType.Alias]={' + ','.join(f'[EElementType.{x}]=2' for x in labels) + '}}')
add('duplicate-matrix-row-last-wins', f=fight[:-1] + ',[EElementType.None]={' + ','.join(f'[EElementType.{x}]=7' for x in labels) + '}}')
add('duplicate-matrix-cell-last-wins', f=fight.replace('[EElementType.None]=1.00', '[EElementType.None]=3,[EElementType.None]=4'))
add('unknown-row-enum', f=fight.replace('[EElementType.None]', '[EElementType.Unknown]', 1), typed_error='Unknown official enum key')
add('unknown-cell-enum', f=fight.replace('[EElementType.None]=1.00', '[EElementType.Unknown]=1.00'), typed_error='Unknown official enum key')
add('unknown-sex-enum', d=define.replace('sex=ERoleType.Male', 'sex=ERoleType.Unknown', 1), typed_error='Unknown official enum key')
for i, label in enumerate(labels):
    add('missing-matrix-row-' + label, f=fight.replace('[EElementType.' + label + ']={', '[wrong.' + label + ']={', 1))
    add('missing-matrix-cell-' + label, f=fight.replace(f'[EElementType.{label}]={1 + i/100:.2f}', f'[wrong.{label}]=1', 1))
for value in ['.', '1.2.3', '..', '1..']:
    add('invalid-float-' + value, f=fight.replace('=1.00', '=' + value, 1), typed_error='Invalid element weight')
for value in ['0', '.5', '1.', '００.５', '𝟙.𝟚', '1e3', '0x10', '+1', '-1']:
    add('float-token-' + value, f=fight.replace('=1.00', '=' + value, 1))
# JSON has no infinity; preserve raw Python via an explicit string only for that value.
add('infinite-weight', 'build-layout', f=fight.replace('=1.00', '=' + '9'*400, 1),
    projection_error='Nonfinite element weight cannot enter knowledge snapshot')
for i in range(1, 16):
    add(f'character-order-{i}', d=define.replace(f'[{i}]={{', f'[{i+1}]={{', 1))
for key in ['headStyle', 'firstSkill', 'InitialEquip', 'sex']:
    add('missing-character-' + key, d=define.replace(key + '=', 'not_' + key + '=', 1))
    add('duplicate-character-' + key, d=define.replace(key + '=', key + ('=ERoleType.Female,' if key == 'sex' else '=999,') + key + '=', 1))
add('character-missing-type', d=define.replace('sex=ERoleType.Male', 'sex=other.Male', 1))
add('character-short-table', d=define[:define.rfind(',\n[15]')] + '\n}')
add('character-extra', d=define[:-1] + ',[16]={sex=ERoleType.Male,headStyle=1,firstSkill=2,InitialEquip=3}}')
add('character-unicode-digits', d=define.replace('[1]={', '[١]={', 1).replace('headStyle=1,', 'headStyle=𝟚,', 1))
for key, value in [('headStyle', '2147483648'), ('firstSkill', '4294967296'), ('InitialEquip', '65536')]:
    add('projection-range-' + key, 'build-layout', d=define.replace(key + '=', key + '=' + value + ',ignored=', 1),
        projection_error='Character value exceeds knowledge snapshot range')
add('projection-range-sex', 'build-layout', d=define.replace('Male=1', 'Male=2147483648'),
    projection_error='Character value exceeds knowledge snapshot range')
add('very-large-character', d=define.replace('headStyle=1,', 'headStyle=' + '9'*100 + ',', 1))
add('crlf-preserved-not-normalized', d=define.replace('\n', '\r\n'), f=fight.replace('\n', '\r\n'))
add('comments-scanned', d='-- EElementType={None=0,Earth=1,Water=2,Fire=3,Wind=4}\n' + define)
add('matrix-label-case-sensitive', f=fight.replace('[EElementType.None]', '[EElementType.none]', 1), typed_error='Unknown official enum key')
add('enum-unicode-distinct-spellings', d=define.replace('Wind=4', 'Wind=4,é=7,é=8'))
add('constants-public', 'constants-public')
add('constants-public-empty', 'constants-public', d='', f='')
add('public-catalog', 'build-public')
add('public-catalog-empty', 'build-public', sk=b'', np=b'', it=b'')
add('empty-npc-name', 'build-layout', np=table(npc(name='')))
add('npc-trailing-nuls-only', 'build-layout', np=table(npc(name='\0\0')))
add('npc-interior-nul', 'build-layout', np=table(npc(name='A\0B\0')))
add('all-npc-skill-slots', 'build-layout', np=table(npc(skills=(1, 2, 3, 4, 5))))
add('name-missing', 'build-layout', names={})
add('name-null', 'build-layout', names={1001: None})
add('name-empty', 'build-layout', names={1001: ''})
add('name-spaces-preserved', 'build-layout', names={1001: '   '})
add('names-not-unique-source-allows', 'build-layout', sk=table(skill(), skill(ident=102, key=12)), names={1001: 'same'})
add('key-zero-omitted', 'build-layout', sk=table(skill(key=0), skill(ident=102, key=0)))
add('key-duplicate', 'build-layout', sk=table(skill(), skill(ident=102)))
add('key-max', 'build-layout', sk=table(skill(key=65535)))
add('name-before-ambiguous-key', 'build-layout', sk=table(skill(), skill(ident=102, name=1003)))
add('skill-zero-id', 'build-layout', sk=table(skill(ident=0)))
add('skill-duplicate-id', 'build-layout', sk=table(skill(), skill()))
add('skill-zero-count', 'build-layout', sk=u32(0))
add('skill-excess-count', 'build-layout', sk=u32(10001))
add('skill-trailing', 'build-layout', sk=skill_raw+b'!')
for length in range(4):
    add('skill-short-' + str(length), 'build-layout', sk=skill_raw[:length], typed_error='Invalid skill record size')
add('npc-before-item-layout-error', 'build-layout', np=table(npc(ident=0)), it=table(item(ident=0)))
add('item-before-skill-error', 'build-layout', it=table(item(ident=0)), sk=table(skill(ident=0)))
add('skill-before-lua-error', 'build-layout', sk=table(skill(ident=0)), d='bad')
add('names-before-lua-error', 'build-layout', names={}, d='bad')
add('nested-name-error-checkpoint', 'build-nested-layout', names={})
add('nested-key-error-checkpoint', 'build-nested-layout', sk=table(skill(), skill(ident=102)))
add('nested-constants-error-checkpoint', 'build-nested-layout', d='bad')
add('keys-before-lua-error', 'build-layout', sk=table(skill(), skill(ident=102)), d='bad')
for length in [0, 1, 3, 4, 5, len(npc_raw)-1]:
    add(f'npc-truncated-{length}', 'build-layout', np=npc_raw[:length])
for length in [0, 1, 3, 4, 5, len(item_raw)-1]:
    add(f'item-truncated-{length}', 'build-layout', it=item_raw[:length],
        typed_error='Catalog record truncated' if length > 4 else None)
add('all-skill-fields-max', 'build-layout', sk=table(skill(values={field: 2**({'B':8,'H':16,'I':32}[kind])-1
    for field, kind in source.SKILL_FIELDS})), names={2**32-1:'max'})
for offset in range(75, 85):
    raw = bytearray(npc_raw); raw[-203+offset] = 255
    add(f'npc-skill-byte-{offset}', 'build-layout', np=bytes(raw))
rng = random.Random(20261108)
for case in range(36):
    records = [skill(ident=i, name=1001, key=i if case % 2 else 0,
        values={field: rng.randrange(2**({'B':8,'H':16,'I':32}[kind]))
                for field, kind in source.SKILL_FIELDS if field not in ('ID','Name','Key')}) for i in range(1, rng.randrange(2, 9))]
    add(f'seeded-skills-{case}', 'build-layout', sk=table(*records))


def finite_json(value):
    if isinstance(value, float) and value == float('inf'): return 'Infinity'
    if isinstance(value, dict): return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [finite_json(v) for v in value]
    return value


output = Path(__file__).with_name('Fixtures'); output.mkdir(exist_ok=True)
references = []
for index, start in enumerate(range(0, len(cases), 64)):
    payload = json.dumps(finite_json(cases[start:start+64]), ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    packed = gzip_json_bytes(payload)
    assert len(packed) <= 500000
    name = f'combat-catalog-{index:02}.json.gz'
    (output / name).write_bytes(packed)
    references.append((name, hashlib.sha256(packed).hexdigest(), hashlib.sha256(payload.encode()).hexdigest()))
sources = ['wlre/services/world/combat_catalog.py', 'wlre/services/world/normal_attack_catalog.py',
           'wlre/services/world/itemdata_v1.py', 'wlre/services/world/item_stack_rules.py',
           'wlre/services/world/official_lua_codec.py', 'wlre/services/parser_diagnostics.py']
lines = ['// Generated synthetic retained-Python oracle. No official asset success is implied.',
         'using System.Text.Json;', 'using Lala.Core.Tests.TestSupport;',
         'namespace Lala.Core.Tests.Catalogs.Combat;', 'public static class CombatCatalogPythonVectors', '{',
         f'    public const int VectorCount = {len(cases)};', '    public static IEnumerable<object[]> Sources()', '    {']
for path in sources:
    digest = hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    lines.append(f'        yield return new object[] {{ "{path}", "{digest}" }};')
lines += ['    }', '    public static IEnumerable<object[]> Cases()', '    {', '        foreach (var fixture in new[]', '        {']
for name, compressed, decoded in references:
    lines.append(f'            ("{name}", "{compressed}", "{decoded}"),')
lines += ['        })', '        {', '            using var document = JsonDocument.Parse(GzipJson.DecodeResource(',
    '                "Lala.Core.Tests.Catalogs.Combat.Fixtures." + fixture.Item1, fixture.Item2, fixture.Item3));',
    '            foreach (var row in document.RootElement.EnumerateArray())',
    '                yield return new object[] { row.GetProperty("name").GetString()!, row.Clone() };',
    '        }', '    }', '}']
Path(__file__).with_name('CombatCatalogPythonVectors.cs').write_text('\n'.join(lines)+'\n', encoding='utf-8', newline='\n')
print(f'{len(cases)} retained-Python vectors; {len(references)} deterministic gzip resources; all pins restored')
