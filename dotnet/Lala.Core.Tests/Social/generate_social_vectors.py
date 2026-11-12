"""Retained Python receive-decoder parity; deterministic synthetic packets only.
Run from repository root: python dotnet/Lala.Core.Tests/Social/generate_social_vectors.py
Never imports send/runtime functions for execution or reads accounts/captures/resources.
"""
import json
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from wlre.network.protocol import decode as decode_server
from wlre.network.wire import Packet, ProtocolError
from wlre.services.social.chat import decode_chat
from wlre.services.social.guild import decode_guild
from wlre.services.social.guild_actions import decode_actions

rng = random.Random(12623985)
NAMES = ['', '星河😀\0', 'A\0B\0\0', 'ΩЖ한글', '界' * 127]
valid, invalid, ignored = [], [], []


def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)


def raw(size):
    return bytes(rng.randrange(256) for _ in range(size))


def text(value):
    value = value.encode('utf-16le')
    return pack('B', len(value)) + value


def item():
    return (pack('HBBBIIIHddBBHHBHI', 65535, 255, 254, 253, 0xffffffff,
                 0x80000000, 0, 65535, -123.5, 1e-100, 255, 254, 65535, 65534,
                 253, 65533, 0xffffffff) +
            b''.join(pack('BH', i, 65535 - i) for i in range(4)) + pack('BBBB', 3, 255, 254, 253))


def chat_profile(name='星河😀\0', card=0, equipment=3):
    result = text(name) + raw(16) + pack('B', card)
    if card == 0:
        result += raw(7) + text('PRIVATE-CARD-SYNTHETIC') + pack('B', equipment) + raw(equipment * 2)
    return result


def chat_body(sub, contents='聊天😀', links=0, reply=0, reply_items=3, reply_at=255):
    result = pack('B', links) + b''.join(pack('B', i) + item() for i in range(links))
    result += text(contents) + pack('I', reply)
    if reply:
        if sub in (27, 28):
            result += pack('H', 65535)
        result += text('引用😀\0') + pack('BB', reply_at, reply_items)
        result += b''.join(pack('H', (65535 - i)) for i in range(reply_items))
    return result


def chat_packet(sub, name='星河😀\0', card=0, sender=0xffffffff, local=42,
                links=0, reply=0, contents='聊天😀', reply_items=3):
    result = pack('H', 65535) if sub == 28 else b''
    result += pack('I', sender)
    if sub == 17 or (sub == 3 and sender == local):
        result += pack('I', 123)
    if sub in (10, 17):
        result += chat_profile(name, card)
    elif sub == 28:
        result += text(name) + raw(16)
    return result + chat_body(sub, contents, links, reply, reply_items)


def guild_profile(name='成員😀\0', equipment=3):
    return (text(name) + raw(15) + pack('B', equipment) + raw(equipment * 6) + raw(8) +
            text('PRIVATE-SIGNATURE-SYNTHETIC') + raw(8))


def roster(ids, name='組織😀\0'):
    result = text(name) + text('首領😀\0') + pack('B', len(ids))
    for i, rid in enumerate(ids):
        result += pack('I', rid) + guild_profile(NAMES[i % len(NAMES)], i % 4) + raw(13)
    return (result + text('PRIVATE-RULES-SYNTHETIC') + raw(2) + pack('B', 255) +
            raw(16 + 10 + 11) + pack('I', 0xffffffff))


def decode(family, main, sub, payload, local):
    packet = Packet(main, sub, payload)
    if family == 'chat':
        return decode_chat(packet, local)
    return (decode_guild if family == 'guild' else decode_actions)(packet)


def outcome(family, main, sub, payload, local):
    try:
        return {'expected': decode(family, main, sub, payload, local)}
    except ProtocolError as exc:
        return {'error': str(exc)}


def add(name, family, main, sub, payload, local=None):
    sample = dict(name=name, family=family, main=main, sub=sub, hex=payload.hex(), local=local)
    result = outcome(family, main, sub, payload, local)
    sample.update(result)
    if 'error' in result:
        # Known packet errors must retain service precedence in the actual Python dispatcher.
        try:
            decode_server(Packet(main, sub, payload), local)
        except ProtocolError as exc:
            assert str(exc) == result['error'], name
        else:
            raise AssertionError('Dispatcher unexpectedly accepted ' + name)
        invalid.append(sample)
    elif result['expected'] is None:
        ignored.append(sample)
    else:
        assert decode_server(Packet(main, sub, payload), local) == result['expected'], name
        sample['accepted_prefixes'] = {}
        for length in range(len(payload)):
            prefix = outcome(family, main, sub, payload[:length], local)
            if 'error' not in prefix:
                sample['accepted_prefixes'][str(length)] = prefix['expected']
        sample['tail'] = outcome(family, main, sub, payload + b'\x7e', local)
        valid.append(sample)


for sub in (1, 2, 3, 5, 6, 10, 17, 27, 28):
    for variant, name in enumerate(NAMES):
        local = 42 if variant % 2 else 0xffffffff
        add(f'chat_{sub}_{variant}', 'chat', 2, sub,
            chat_packet(sub, name, card=variant % 3, local=local, links=variant % 3,
                        reply=0xffffffff if variant % 2 else 0, contents=name), local)
for sub in (10, 17, 28):
    add(f'chat_{sub}_empty_reply_links', 'chat', 2, sub,
        chat_packet(sub, reply=1, reply_items=0), 42)
add('chat_max_reply_links', 'chat', 2, 27, chat_packet(27, reply=1, reply_items=255), 42)
add('chat_zero_sender_and_local', 'chat', 2, 3, chat_packet(3, sender=0, local=0), 0)
for sender in (0, 1, 0xffffffff):
    for suffix in (b'', b'\xff', b'\x03\x00\xd8truncated-PRIVATE-SYNTHETIC'):
        add(f'chat_missing_local_{sender}_{len(suffix)}', 'chat', 2, 3, pack('I', sender) + suffix)
for sub in (18, 19):
    add(f'profile_{sub}_missing', 'chat', 2, sub, pack('I', 0))
    for card in (0, 1, 255):
        for online in (0, 1, 2, 255):
            add(f'profile_{sub}_{card}_{online}', 'chat', 2, sub,
                pack('IB', 0xffffffff, online) + chat_profile(card=card))
for result in (0, 1, 2, 3, 255):
    add(f'chat_result_{result}', 'chat', 2, 13, pack('B', result))
for target in (0, 1, 0xffffffff):
    add(f'chat_offline_{target}', 'chat', 2, 21, pack('I', target))
for name, contents in (('empty', b''), ('ascii', b'Hello\x00\x1f\x7f'), ('unknown', b'\xff\xa4'),
                       ('utf16_not_guessed', '你好'.encode('utf-16le'))):
    add('announcement_' + name, 'chat', 2, 0, pack('I', 0xffffffff) + contents)

for ids in ([], [1], [0xffffffff, 1, 0x80000000, 2]):
    add(f'roster_{len(ids)}', 'guild', 39, 2, roster(ids))
for sub in (6, 8, 60):
    for rid in (0, 1, 0xffffffff):
        payload = pack('I', rid) + (guild_profile(equipment=255 if rid == 1 else 0) if sub == 60 else b'')
        add(f'guild_{sub}_{rid}', 'guild', 39, sub, payload)
for result in (0, 1, 255):
    add(f'guild_leave_{result}', 'guild', 39, 7, pack('BI', result, 0xffffffff))
    add(f'guild_disband_{result}', 'guild', 39, 10, pack('B', result))

for state in range(4):
    add(f'sign_state_{state}', 'actions', 39, 85, pack('B', state))
for sub in (15, 86):
    for value in (0, 1, 2, 3, 255):
        add(f'guild_action_{sub}_{value}', 'actions', 39, sub, pack('B', value))
for remaining in (0, 1, 255):
    for allow in (0, 1):
        add(f'donate_{remaining}_{allow}', 'actions', 39, 87, pack('BB', remaining, allow))
for kind in (0, 3):
    add(f'sell_kind_{kind}', 'actions', 10, 5, pack('B', kind))
for index in (0, 1, 255):
    add(f'sell_update_{index}', 'actions', 10, 5, pack('BBB', 1, index, 255))
for count in (0, 1, 100, 255):
    add(f'sell_snapshot_{count}', 'actions', 10, 5, pack('BB', 2, count) + raw(count))

# Invalid discriminants, UTF-16, linked item floats, duplicated IDs, and special branch tails.
for sub in (18, 19):
    add(f'missing_profile_tail_{sub}', 'chat', 2, sub, pack('I', 0) + b'\0')
for name, bad_text in (('odd', b'\x01x'), ('surrogate', b'\x02\x00\xd8'), ('short', b'\x02\x00')):
    add('chat_text_' + name, 'chat', 2, 1, pack('IB', 1, 0) + bad_text + bytes(4))
    add('chat_profile_' + name, 'chat', 2, 18, pack('IB', 1, 1) + bad_text)
    add('guild_profile_' + name, 'guild', 39, 60, pack('I', 1) + bad_text)
    add('guild_roster_' + name, 'guild', 39, 2, bad_text)
add('chat_missing_sender', 'chat', 2, 3, b'\0\0\0')
add('chat_outbound_missing_target', 'chat', 2, 3, pack('I', 42), 42)
for name, value in (('nan', float('nan')), ('infinity', float('inf')), ('negative_infinity', -float('inf'))):
    for offset in (19, 27):
        linked = bytearray(item())
        struct.pack_into('<d', linked, offset, value)
        add(f'chat_item_{name}_{offset}', 'chat', 2, 1,
            pack('IBB', 1, 1, 255) + linked + text('text') + bytes(4))
for ids in ([0], [1, 1], [0xffffffff, 0xffffffff]):
    add('guild_invalid_ids_' + '_'.join(map(str, ids)), 'guild', 39, 2, roster(ids))
for state in (4, 127, 255):
    add(f'sign_invalid_{state}', 'actions', 39, 85, pack('B', state))
for allow in (2, 127, 255):
    add(f'donate_invalid_{allow}', 'actions', 39, 87, pack('BB', 255, allow))
for kind in (4, 127, 255):
    add(f'sell_invalid_{kind}', 'actions', 10, 5, pack('B', kind))

# Unknown keys must not parse malformed content or collide with adjacent families.
for sub in range(256):
    if sub not in (0, 1, 2, 3, 5, 6, 10, 13, 17, 18, 19, 21, 27, 28):
        add(f'chat_unknown_{sub}', 'chat', 2, sub, b'\xff')
    if sub not in (2, 6, 7, 8, 10, 60):
        add(f'guild_unknown_{sub}', 'guild', 39, sub, b'\xff')
    if sub not in (15, 85, 86, 87):
        add(f'action_unknown_{sub}', 'actions', 39, sub, b'\xff')
for family, main, sub in (('chat', 3, 3), ('guild', 38, 2), ('actions', 10, 4), ('actions', 11, 5)):
    add(f'{family}_wrong_key_{main}_{sub}', family, main, sub, b'\xff')

output = {'valid': valid, 'invalid': invalid, 'ignored': ignored}
serialized = json.dumps(output, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
Path(__file__).with_name('PythonSocialVectors.cs').write_text(
    'namespace Lala.Core.Tests.Social;\ninternal static class PythonSocialVectors\n{\n'
    '    internal const string Json = """\n' + serialized + '\n""";\n}\n', encoding='utf-8')
print(f'{len(valid)} valid, {len(invalid)} invalid, {len(ignored)} ignored social vectors')
