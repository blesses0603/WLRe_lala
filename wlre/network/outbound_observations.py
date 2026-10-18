"""Recognize effects of locally sent packets without assuming a server ACK.

Game wire bytes are unchanged; the caller applies observations only after
sendall completes. An incomplete candidate payload is rejected before sending.
"""
from wlre.network.wire import ProtocolError
from wlre.network.protocol import decode_outbound_movement


def observed_outbound(packet):
    key = (packet.main, packet.sub)
    raw = packet.payload
    minimum = {
        (50, 1): 6, (50, 2): 9,
        (23, 15): 8, (23, 147): 5,
    }.get(key)
    if minimum is not None and len(raw) < minimum:
        raise ProtocolError(f'outbound {packet.main}-{packet.sub} payload incomplete')
    if key in ((50, 1), (50, 2)):
        event = {
            'type': 'battle_command_sent',
            'col': raw[0], 'row': raw[1],
            'target_col': raw[2], 'target_row': raw[3],
            'skill_id': int.from_bytes(raw[4:6], 'little') if packet.sub == 1 else 10024,
        }
        if packet.sub == 2:
            event.update(item_id=int.from_bytes(raw[4:6], 'little'), bag_index=raw[8])
        return event
    if key == (23, 15):
        return {'type': 'field_item_sent', 'bag_index': raw[0],
                'item_id': int.from_bytes(raw[1:3], 'little'), 'npc_index': raw[7]}
    if key == (23, 147):
        return {'type': 'field_storage_sent',
                'resource': 'hp' if raw[0] == 3 else 'sp',
                'npc_index': raw[2], 'amount': int.from_bytes(raw[3:5], 'little')}
    return decode_outbound_movement(packet)
