"""Display names never fall back to old seed or guess shared model identity."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from wlre.services.world import map_names


def runtime():
    return SimpleNamespace(revision=1296,stages={1:{'name_id':11,'model_id':9},2:{'name_id':12,'model_id':9},3:{'name_id':13,'model_id':8}},texts={11:'first',12:'second',13:'third'})

class OfficialMapNamesTests(unittest.TestCase):
    def test_same_version_names_and_ambiguous_models(self):
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=runtime()):
            self.assertEqual(map_names.map_label(1),'first(1)')
            self.assertEqual(map_names.model_label(8),'third(8)')
            self.assertEqual(map_names.model_label(9),'多個場景共用模型(9)')
            self.assertEqual(map_names.map_choices(),['first(1)','second(2)','third(3)'])
            saved=map_names.data();saved['maps']['1']='bad'
            self.assertEqual(map_names.map_label(1),'first(1)')

    def test_runtime_change_and_failure_never_keep_old_names(self):
        old=runtime();new=runtime();new.texts[11]='renamed'
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=old):
            self.assertEqual(map_names.map_label(1),'first(1)')
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=new):
            self.assertEqual(map_names.map_label(1),'renamed(1)')
        with patch('wlre.services.world.runtime_1275.active_runtime',side_effect=ValueError('unavailable')),patch('wlre.storage.bundled_database.load_bundled_json',side_effect=AssertionError('seed read')):
            self.assertEqual(map_names.map_label(1),'未知地圖(1)')
            self.assertEqual(map_names.map_choices(),[])

    def test_unresolved_text_and_model_do_not_invent_labels(self):
        value=runtime();value.texts={};value.stages[1]['model_id']=True
        with patch('wlre.services.world.runtime_1275.active_runtime',return_value=value):
            self.assertFalse(map_names.data()['maps'])
            self.assertEqual(map_names.model_label(9),'未命名場景(9)')
