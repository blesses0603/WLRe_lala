"""Synthetic offline differential cases for ServerProtocol; no captures or credentials.
Run from repository root. All expected values and boundary behavior come from retained Python.
Unported service metadata is tested separately, not represented as decoder parity.
"""
import json
import random
import struct
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.network.protocol import decode, decode_outbound_movement
from wlre.network.wire import Packet, ProtocolError
from wlre.configuration import PROTOCOL_ENUMS

rng = random.Random(1262501)
PRIVATE = b'SYNTHETIC-CREDENTIAL-NEVER-RETAIN'

def p(fmt, *values): return struct.pack('<' + fmt, *values)
def invoke(main, sub, payload, outbound=False):
    return (decode_outbound_movement if outbound else decode)(Packet(main, sub, payload))
def outcome(main, sub, payload, outbound=False):
    try: return {'expected': invoke(main, sub, payload, outbound)}
    except ProtocolError: return {'throws': True}

vectors = []
def add(name, main, sub, payload=b'', outbound=False):
    expected = outcome(main, sub, payload, outbound)
    prefixes = []
    for length in range(len(payload)):
        result = outcome(main, sub, payload[:length], outbound)
        if 'expected' in result: prefixes.append(dict(length=length, **result))
    vectors.append(dict(name=name, main=main, sub=sub, hex=payload.hex().upper(), outbound=outbound,
                        **expected, prefixes=prefixes,
                        tail=outcome(main, sub, payload + b'\x7e', outbound)))

for main, sub, minimum in ((62,3,15),(62,64,0),(65,13,2),(23,74,5),(23,76,4),(62,70,4)):
    add(f'geometry_{main}_{sub}_minimum', main, sub, bytes(range(minimum)))
    add(f'geometry_{main}_{sub}_extension', main, sub, bytes(range(minimum)) + PRIVATE)
for sub in (1,2):
    for amount in (0,1,2**31,2**32-1):
        for flag in (0,1): add(f'gold_delta_{sub}_{amount}_{flag}',26,sub,p('IB',amount,flag))
    for flag in (2,255): add(f'gold_invalid_flag_{sub}_{flag}',26,sub,p('IB',1,flag))
for amount in (0,2**32-1): add(f'gold_snapshot_{amount}',26,4,p('I',amount))
add('gold_limit_empty',26,3)
add('gold_limit_discard',26,3,PRIVATE)
add('event_end_empty',20,8)
add('event_end_discard',20,8,PRIVATE)
for sub in (7,10,11,13,14,15,16,17):
    add(f'continue_empty_{sub}',20,sub)
    add(f'continue_extension_{sub}',20,sub,PRIVATE)
for sub in range(1,7):
    effect = p('BHBBBHB IHBH'.replace(' ',''),255,65535,254,253,252,65534,251,2**32-1,65533,250,65532)
    assert len(effect)==18
    add(f'effect_{sub}',20,sub,effect)
    add(f'effect_extension_{sub}',20,sub,effect+PRIVATE)
    add(f'effect_short_{sub}',20,sub,effect[:17])
for sub in (9,12,46,58,67,70):
    add(f'event_active_{sub}',20,sub,PRIVATE)
for reason in (0,1,2,3,4,255): add(f'event_rejected_{reason}',20,74,bytes([reason])+PRIVATE)
add('heartbeat',1,23)
add('initial_complete',1,11)
add('account_empty_echo',1,4,p('I',2**32-1)+bytes(3))
add('account_private_echo',1,4,p('I',42)+b''.join(bytes([len(PRIVATE)])+PRIVATE for _ in range(3)))
add('account_non_utf8_echo',1,4,p('I',42)+b'\x04\xff\xfe\x00\xd8'+bytes(2))
add('account_oversized_echo',1,4,p('I',42)+b'\xff'+PRIVATE)
for result,kind in ((0,0),(1,255),(255,1)):add(f'login_{result}_{kind}',63,7,p('BB',result,kind))
for kind in (0,1,255):add(f'movement_stop_{kind}',6,2,bytes([kind]))
for main in (7,12):
    for n,extension in enumerate((b'', b'\x00', b'\x03',b'\x04',b'\xff',b'\x00\x03',
            b'\xff\xee\x02',b'\xff\xee\x04',b'\xff\xee\x03\x02',b'\xff\xee\x03\x02\x03',
            b'\xff\xee\x03\x00\x03',b'\xff\xee\x03\x04\x03',b'\xff\xee\x03\x02\x04',PRIVATE)):
        add(f'position_{main}_{n}',main,1,p('IHHH',2**32-1,65535,65534,65533)+extension)
for length in range(15): add(f'battle_attribute_length_{length}',51,1,bytes(range(length)))
add('battle_attribute_unsigned_max',51,1,p('BBBI',255,254,253,2**32-1))
for value in (0,65535): add(f'round_{value}',52,1,p('H',value))
for payload in (b'\x00\xff',b'\x00\xff\xfe',b'\x00\xff\xfe\xfd'):
    add(f'unit_exit_length_{len(payload)}',11,1,payload)
add('attribute_allocation',8,4)
# Check every release-owned reverse attribute name, including colliding aliases and unknowns.
for kind in sorted(set(PROTOCOL_ENUMS['EAttribute'].values()) | {1,255}):
    sub=kind%3+1
    prefix = b'' if sub==1 else p('BH',255,65535) if sub==2 else p('I',2**32-1)
    add(f'attribute_name_{kind}',8,sub,prefix+p('BBII',kind,2,2**32-1,2**32-1))
for sub in (1,2,3):
    prefix=b'' if sub==1 else p('BH',0,0) if sub==2 else p('I',0)
    for sign in (0,1,2,255): add(f'attribute_sign_{sub}_{sign}',8,sub,prefix+p('BBII',25,sign,2**32-1,0))
for rid in (-2**31,-1,0,2**31-1):add(f'walk_{rid}',6,1,p('iHH',rid,65535,0))
for sub in (10,12):
    for value in (0,255):add(f'battle_byte_{sub}_{value}',11,sub,bytes([value]))
add('fight_exit',11,0,p('IH',2**32-1,65535))
add('attack_empty',50,1,b'\x00')
for skill in list(PROTOCOL_ENUMS['ESkill'].values()) + [0,65535]:
    add(f'attack_skill_{skill}',50,1,p('BBB HBBB'.replace(' ',''),1,255,254,skill,253,252,0))
actions=b''
for i in range(3):
    targets=b''
    for j in range(i+1):
        attrs=b''.join(p('BIB',kind,2**32-1,sign) for kind,sign in ((25,2),(220,0),(255,255)))
        targets+=p('BBBBB',j,255,254,253,3)+attrs
    actions+=p('BBHBBB',i,254,10001+i,253,252,i+1)+targets
add('attack_nested',50,1,bytes([3])+actions)
add('attack_hostile_count',50,1,b'\xff')
add('attack_hostile_target_count',50,1,p('BBBHBBB',1,1,1,10001,1,1,255))
for x,y in ((0,0),(65535,65535),(1234,5678)):add(f'outbound_{x}_{y}',6,1,p('HH',x,y),True)
add('outbound_login_ignored',63,7,PRIVATE,True)
add('outbound_unknown_ignored',255,255,PRIVATE,True)
for main,sub in ((255,255),(1,3),(20,255),(31,255),(2,255),(62,255),(13,2),(13,15),(7,4)):
    # Unknown discriminants must continue to metadata-only fallback rather than throw.
    add(f'unknown_{main}_{sub}',main,sub,(b'\xff' if (main,sub) in ((13,15),(7,4)) else b'')+PRIVATE)
# Exercise composition through existing decoders without asserting unported service parity.
add('dispatch_roles',63,1)
add('dispatch_battle_units',11,5,b'\x00')
add('dispatch_battle_start',11,250,b'\x00\xff\x00')
add('dispatch_social',13,1,p('I',2**32-1))
add('dispatch_activity_roles',23,122,p('IB',42,0))
add('dispatch_activity_self',62,67)
add('dispatch_activity_initial',7,4,p('BI',0,0))
add('dispatch_expedition',31,5,b'\x01')
add('dispatch_expedition_extension',31,15,PRIVATE)
add('dispatch_live',27,1,b'\x00')

payload='[\n'+',\n'.join(json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False) for v in vectors)+'\n]'
Path(__file__).with_name('PythonServerVectors.cs').write_text(
    '// Generated by generate_server_vectors.py; synthetic Python parity only.\n'
    'namespace Lala.Core.Tests.Protocol;\ninternal static class PythonServerVectors\n{\n'
    '    internal const string Json = """\n'+payload+'\n""";\n}\n',encoding='utf-8')
print(f'Generated {len(vectors)} cases and {sum(len(bytes.fromhex(v["hex"])) for v in vectors)} prefix boundaries.')
