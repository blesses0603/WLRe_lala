"""S23/S26/S27 evidence: no server nonce, no speculative settlement."""
import unittest
from wlre.core.state import State
from wlre.network.wire import Packet
from wlre.network.protocol import decode
from wlre.services.world.npc_shop_evidence import classify, defaults, MAX_EVENTS


class ShopEvidenceTests(unittest.TestCase):
    def ready_state(self):
        state=State()
        state.apply({'type':'bag_snapshot','capacity':40,'items':[]})
        state.apply(decode(Packet(26,4,(5000).to_bytes(4,'little'))))
        self.assertTrue(state.inventory['reliable'])
        self.assertTrue(state.gold['reliable'])
        return state

    def test_purchase_response_order_independent_not_payment_authorization(self):
        s=self.ready_state()
        before=s.packet_count
        # Gold may arrive before S27 success, while S23 is delayed.
        s.apply(decode(Packet(26,2,(1500).to_bytes(4,'little')+b'\x00')))
        s.apply({'type':'bag_add','item':{'index':1,'item_id':32297,'count':2}})
        s.apply(decode(Packet(27,1,b'\x00')))
        audit=classify(s.shop_evidence,kind='buy',start_packet=before,
                       item_id=32297,count=2,expected_gold_delta=-1500)
        self.assertEqual(audit['status'],'observed_consistent')
        self.assertIn('缺少伺服器交易識別碼',audit['reason'])
        self.assertEqual(s.gold['amount'],3500)
        self.assertTrue(s.inventory['reliable'])
        self.assertEqual(len(s.shop_evidence['events']),5)

    def test_missing_result_stays_pending_and_failure_is_rejected(self):
        s=self.ready_state()
        before=s.packet_count
        args=dict(kind='buy',start_packet=before,item_id=32297,
                  count=1,expected_gold_delta=-750)
        self.assertEqual(classify(s.shop_evidence,**args)['status'],'pending')
        s.apply(decode(Packet(27,1,b'\x01')))
        self.assertEqual(classify(s.shop_evidence,**args)['status'],'rejected')
        # This is an inconsistency, but we do not infer a successful payment.
        self.assertNotEqual(classify(s.shop_evidence,**args)['status'],'observed_consistent')
        s.apply(decode(Packet(26,2,(750).to_bytes(4,'little')+b'\0')))
        self.assertEqual(classify(s.shop_evidence,**args)['status'],'uncertain')

    def test_duplicate_reply_and_mismatched_amount_fail_closed(self):
        s=self.ready_state()
        start=s.packet_count
        s.apply(decode(Packet(26,2,(600).to_bytes(4,'little')+b'\0')))
        s.apply({'type':'bag_add','item':{'index':1,'item_id':32297,'count':1}})
        s.apply(decode(Packet(27,1,b'\x00')))
        args=dict(kind='buy',start_packet=start,item_id=32297,
                  count=1,expected_gold_delta=-750)
        self.assertEqual(classify(s.shop_evidence,**args)['status'],'uncertain')
        s.apply(decode(Packet(27,1,b'\x00')))
        self.assertEqual(classify(s.shop_evidence,**args)['status'],'uncertain')

    def test_s27_sale_gold_field_is_not_authoritative_balance(self):
        s=self.ready_state()
        s.apply({'type':'bag_add','item':{'index':7,'item_id':32297,'count':1}})
        start=s.packet_count
        s.apply(decode(Packet(27,6,(99999).to_bytes(4,'little')+b'\x07\x01')))
        self.assertEqual(s.gold['amount'],5000)
        self.assertEqual(s.shop_evidence['events'][-1]['s27_gold_field'],99999)
        s.apply(decode(Packet(27,8,b'\x01')))
        s.apply(decode(Packet(26,1,(8).to_bytes(4,'little')+b'\0')))
        audit=classify(s.shop_evidence,kind='sell',start_packet=start,
                       item_id=32297,count=1,expected_gold_delta=8,bag_slot=7)
        self.assertEqual(audit['status'],'observed_consistent')
        self.assertEqual(s.gold['amount'],5008)
        self.assertNotIn('7',s.inventory['items'])

    def test_s27_sale_without_s26_is_pending(self):
        s=self.ready_state()
        s.apply({'type':'bag_add','item':{'index':7,'item_id':32297,'count':1}})
        start=s.packet_count
        s.apply(decode(Packet(27,6,(8).to_bytes(4,'little')+b'\x07\x01')))
        s.apply(decode(Packet(27,8,b'\x01')))
        audit=classify(s.shop_evidence,kind='sell',start_packet=start,
                       item_id=32297,count=1,expected_gold_delta=8,bag_slot=7)
        self.assertEqual(audit['status'],'pending')

    def test_history_bound_role_switch_and_uncertain_inventory(self):
        s=self.ready_state()
        for n in range(150):
            s.apply(decode(Packet(27,1,b'\x00')))
        self.assertEqual(len(s.shop_evidence['events']),MAX_EVENTS)
        self.assertEqual(s.shop_evidence['events'][-1]['packet'],s.packet_count)
        audit=classify(s.shop_evidence,kind='buy',start_packet=1,
                       item_id=32297,count=1,expected_gold_delta=-750)
        self.assertEqual(audit['status'],'uncertain')
        s.apply({'type':'role_list_available','roles':[]})
        self.assertEqual(s.shop_evidence,defaults())
        self.assertFalse(s.gold['ready'])

    def test_s23_invalid_bag_and_s26_limit_are_uncertain(self):
        s=self.ready_state()
        start=s.packet_count
        s.apply({'type':'bag_delete','index':77,'count':1,'show_message':0})
        self.assertFalse(s.inventory['reliable'])
        s.apply(decode(Packet(26,3,b'')))
        result=classify(s.shop_evidence,kind='buy',start_packet=start,
                        item_id=32297,count=1,expected_gold_delta=-750)
        self.assertEqual(result['status'],'uncertain')

    def test_capture_is_bounded_and_contains_no_private_account_data(self):
        s=self.ready_state()
        s.apply({'type':'bag_add','item':{
            'index':2,'item_id':32297,'count':1,
            'private_token':'NEVER_LEAK_THIS'}})
        entry=s.shop_evidence['events'][-1]
        self.assertEqual(entry['item_id'],32297)
        self.assertNotIn('private_token',repr(entry))
        self.assertLessEqual(len(s.shop_evidence['events']),MAX_EVENTS)
