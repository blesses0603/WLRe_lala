import struct
import unittest
from wlre.services.world.house_navigation import decode_floor_extension,update_context,resolve_house_stage
from wlre.services.world.navigation import NavigationError
from wlre.network.protocol import decode
from wlre.network.wire import Packet
from wlre.core.state import State


class HouseContextTests(unittest.TestCase):
    def packet(self,role=17,scene=63501,tail=b'\0\0\0\2\0'):
        return Packet(12,1,struct.pack('<IHHH',role,scene,100,200)+tail)

    def test_verified_floor_payload_and_mapping(self):
        event=decode(self.packet());self.assertEqual(event['house_floor'],dict(verified=True,floor=1,size=2,size_floor=1))
        context=update_context(None,63501,event['house_floor'])
        self.assertEqual(resolve_house_stage(63501,context),10298)
        with self.assertRaises(NavigationError):resolve_house_stage(63502,context)

    def test_missing_size_does_not_use_client_defaults(self):
        context=update_context(None,63501,decode_floor_extension(b'\1'))
        with self.assertRaises(NavigationError):resolve_house_stage(63501,context)
        context=update_context(context,63501,decode_floor_extension(b'\0\0\1\3\1'))
        self.assertEqual(resolve_house_stage(63501,context),10000)
        context=update_context(context,63501,decode_floor_extension(b'\0'))
        with self.assertRaises(NavigationError):resolve_house_stage(63501,context)

    def test_truncated_unknown_and_invalid_fields(self):
        for raw in (b'',b'\0\0',bytes(4),bytes(6),b'\4',b'\0\0\0\4\0',b'\0\0\0\1\4'):
            self.assertEqual(decode_floor_extension(raw),{'verified':False})

    def test_only_local_position_updates_scoped_context(self):
        state=State();state.player=dict(role_id=17,scene=10001,x=0,y=0)
        state.apply(decode(self.packet()));self.assertEqual(resolve_house_stage(63501,state.navigation['house_context']),10298)
        state.apply(decode(self.packet(role=18,scene=63502)))
        self.assertEqual(state.navigation['house_context']['scene'],63501)
        state.apply(decode(self.packet(scene=63502,tail=b'\0')))
        with self.assertRaises(NavigationError):resolve_house_stage(63502,state.navigation['house_context'])
        state.apply(decode(self.packet(scene=10001,tail=b'')))
        self.assertNotIn('house_context',state.navigation)

    def test_unknown_tail_invalidates_previous_context(self):
        state=State();state.player=dict(role_id=17,scene=63501,x=0,y=0)
        state.apply(decode(self.packet()));state.apply(decode(self.packet(tail=bytes(6))))
        self.assertFalse(state.navigation['house_context']['verified'])

    def test_instance_aliases_follow_verified_binary_order(self):
        import hashlib,json
        from unittest.mock import patch
        from wlre.services.world.house_navigation import instance_aliases
        rows={200:dict(max_members=4,room_capacity=2),100:dict(max_members=4,room_capacity=1)}
        digest=hashlib.sha256(json.dumps(list(rows),separators=(',',':')).encode()).hexdigest()
        with patch('wlre.services.world.house_navigation.REVIEWED_STAGE_ORDER',digest):
            self.assertEqual(instance_aliases(rows),{61501:200,61502:200,61503:100})
            with self.assertRaises(NavigationError):instance_aliases(dict(sorted(rows.items())))
            rows[200]['room_capacity']=256
            with self.assertRaises(NavigationError):instance_aliases(rows)

    def test_floor_ack_does_not_invent_a_floor(self):
        event=decode(Packet(62,64,b''))
        self.assertEqual(event['reason'],'house_floor_changed')
        self.assertNotIn('house_floor',event)


if __name__=='__main__':unittest.main()
