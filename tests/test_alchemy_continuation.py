import copy
import itertools
import unittest
from test_release import setup
from wlre.services.items.alchemy import AutoAlchemy
from wlre.services.items.combat_resources import apply_live


def receipts(service):
    rows=copy.deepcopy(service.pending['consumption'])
    return ([{'type':'bag_delete','index':r['index'],'count':r['count']} for r in rows]+
            [{'type':'alchemy_result','item_id':10000,'count':1},
             {'type':'bag_add','source':3,'item':{'index':0,'item_id':10000,'count':1,'serial':999}}])


def feed(service,state,events,now):
    for event in events:
        apply_live(state,event);service.observe(event,state,now=now)


class AlchemyContinuation(unittest.TestCase):
    def test_seven_runs_wait_for_full_confirmation_and_one_second_gap(self):
        state,command=setup();command['runs']=7
        service=AutoAlchemy();self.assertEqual(len(service.start(state,command,0)),1)
        for run in range(7):
            now=run*2+.1
            feed(service,state,receipts(service),now)
            self.assertEqual(state.alchemy['completed'],run+1)
            self.assertEqual(service.tick(state,now+.5),[])
            if run<6:self.assertEqual(len(service.tick(state,now+1)),1)
        self.assertFalse(state.alchemy['enabled']);self.assertTrue(state.inventory['reliable'])
        self.assertFalse(service.pending)

    def test_any_receipt_order_completes_once_and_cannot_immediately_resubmit(self):
        for order in itertools.permutations(range(4)):
            with self.subTest(order=order):
                state,command=setup();service=AutoAlchemy();service.start(state,command,0)
                events=receipts(service)
                feed(service,state,[events[i] for i in order],.2)
                self.assertEqual(state.alchemy['completed'],1)
                self.assertEqual(service.tick(state,.21),[])
                self.assertEqual(len(service.tick(state,1.2)),1)

    def test_combat_and_supply_extend_quiet_interval_before_next_send(self):
        state,command=setup();service=AutoAlchemy();service.start(state,command,0)
        feed(service,state,receipts(service),.2)
        state.battle['active']=True;self.assertEqual(service.tick(state,10),[])
        state.battle['active']=False;state.inventory['field_supply']={'pending':True}
        self.assertEqual(service.tick(state,11),[])
        state.inventory['field_supply']['pending']=False
        self.assertEqual(service.tick(state,11.5),[])
        self.assertEqual(len(service.tick(state,12)),1)

    def test_timeout_names_missing_receipt_without_resending(self):
        state,command=setup();service=AutoAlchemy();service.start(state,command,0)
        events=receipts(service)
        feed(service,state,events[:2]+events[3:],.1)
        self.assertEqual(service.tick(state,16),[])
        self.assertIn('煉金結果',state.alchemy['status'])
        self.assertNotIn('材料扣除（格位',state.alchemy['status'])
        self.assertEqual(state.alchemy['completed'],0)
        self.assertFalse(state.inventory['reliable']);self.assertIsNone(service.pending)
