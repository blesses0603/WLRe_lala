import unittest,copy
from unittest.mock import patch
from types import SimpleNamespace
from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.items.alchemy import material_problem,category,prepare,AutoAlchemy
from wlre.services.world.alchemy_metadata import CurrentAlchemyMetadata
from alchemy_runtime_fixtures import rows


class OfficialAlchemyMetadata(unittest.TestCase):
    def state(self):
        s=State();s.player.update(role_id=1,scene=12000)
        s.inventory.update(ready=True,reliable=True,capacity=7,items={str(i):{'index':i,'item_id':sid,'count':10,'serial':i} for i,sid in enumerate((10001,10031),1)},server_stackable={'10000':True})
        command={'runs':2,'materials':[{'index':i,'item_id':sid,'count':1} for i,sid in enumerate((10001,10031),1)]}
        return s,command
    def test_cold_and_partial_fields_do_not_fall_back_to_seed(self):
        with patch('wlre.services.world.alchemy_metadata._source',return_value=(None,{})),patch('wlre.storage.bundled_database.load_bundled_json',side_effect=AssertionError('no seed')):
            self.assertIsNotNone(material_problem({'item_id':10001}))
            with self.assertRaises(ProtocolError):prepare(*self.state())
        with patch('wlre.services.world.alchemy_metadata._source',return_value=('partial',{10001:{'spares':[1]*5}})):
            self.assertIsNone(CurrentAlchemyMetadata().get('10001'))
    def test_official_field_categories_and_forbidden_materials(self):
        data=rows();item={'item_id':10001}
        with patch('wlre.services.world.alchemy_metadata._source',return_value=('a',data)):
            self.assertIsNone(material_problem(item));self.assertEqual(category(item),'normal')
            for special,spare,kind,expected in [(141,1,1,'book'),(149,73,1,'partner'),(0,1,20,'pet'),(213,4,1,'design'),(213,5,1,'recipe')]:
                data[10001].update(special=special,spares=[spare,0,0,0,0],kind=kind)
                self.assertIsNone(material_problem(item));self.assertEqual(category(item),expected)
            for changes in ({'restrict':4},{'kind':52},{'kind':54},{'spares':[0]*5},{'special':142},{'special':162},{'special':163},{'special':197},{'special':149}):
                data[10001]=rows()[10001];data[10001].update(changes)
                self.assertIsNotNone(material_problem(item))
    def test_capacity_is_occupied_slots_and_metadata_is_same_version(self):
        data=rows();data[10001].update(item_w=20,item_h=20)
        with patch('wlre.services.world.alchemy_metadata._source',return_value=('a',data)):
            state,command=self.state();plan=prepare(state,command)
            self.assertEqual(plan['catalog_key'],'a')
            state.inventory['capacity']=6
            with self.assertRaisesRegex(ProtocolError,'5'):prepare(state,command)
    def test_version_change_stops_next_round_after_receipts(self):
        from wlre.services.items.combat_resources import apply_live
        source=['a',rows()]
        with patch('wlre.services.world.alchemy_metadata._source',side_effect=lambda:tuple(source)):
            state,command=self.state();service=AutoAlchemy();self.assertEqual(len(service.start(state,command,0)),1)
            events=[{'type':'bag_delete','index':r['index'],'count':r['count']} for r in service.pending['consumption']]
            events += [{'type':'alchemy_result','item_id':10000,'count':1},{'type':'bag_add','source':3,'item':{'index':3,'item_id':10000,'count':1,'serial':99}}]
            for event in events:apply_live(state,event);service.observe(event,state,now=.1)
            self.assertIsNone(service.pending)
            state.inventory['capacity']=8;source[0]='b'
            self.assertEqual(service.tick(state,2),[])
            self.assertFalse(state.alchemy['enabled']);self.assertIn('已更新',state.alchemy['status'])
