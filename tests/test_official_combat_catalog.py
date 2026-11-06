import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wlre.services.world import combat_catalog as catalog
from wlre.services.world import official_combat_sources as sources
from wlre.services.items.live_combat_catalog import CurrentCombatCatalog, one_catalog
from wlre.services.items.combat_resources import apply_live,learned,field_context
from wlre.core.state import State


class CombatInputs(unittest.TestCase):
    def test_skill_layout_rejects_unknown_duplicate_and_trailing(self):
        layout=struct.Struct('<'+''.join(k for _,k in catalog.SKILL_FIELDS))
        values=[0]*len(catalog.SKILL_FIELDS)
        values[[n for n,_ in catalog.SKILL_FIELDS].index('ID')]=123
        values[[n for n,_ in catalog.SKILL_FIELDS].index('CostItemCount')]=7
        record=layout.pack(*values);raw=struct.pack('<I',1)+record
        with patch.object(catalog,'SKILL_SHA256',hashlib.sha256(raw).hexdigest()):
            self.assertEqual(catalog.parse_skills(raw)['123']['CostItemCount'],7)
        with self.assertRaises(ValueError):catalog.parse_skills(raw)
        for bad in (raw+b'x',struct.pack('<I',2)+record*2):
            with patch.object(catalog,'SKILL_SHA256',hashlib.sha256(bad).hexdigest()),self.assertRaises(ValueError):catalog.parse_skills(bad)

    def test_source_cache_cannot_replace_previous_input_before_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input';sources._save(path,b'old')
            self.assertIsNone(sources._cached(path,'0'*64,100))
            self.assertEqual(path.read_bytes(),b'old')
            sources._save(path,b'new')
            self.assertEqual(path.read_bytes(),b'new')
            self.assertEqual(next(Path(folder).glob('input.rejected-*')).read_bytes(),b'old')
            with self.assertRaises(ValueError):sources.load_inputs(folder,'future',download=True)

    def test_range_and_quota_fail_closed(self):
        class Response:
            status=200;headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return sources.APK_URL
            def read(self,n):return b'x'*n
        budget=sources.Budget(lambda *a,**k:Response())
        with self.assertRaises(ValueError):budget.get(sources.APK_URL,4,start=0)
        with self.assertRaises(ValueError):budget.get(sources.APK_URL,sources.MAX_DOWNLOAD+1)
        with self.assertRaises(ValueError):sources.RemoteZip(budget).seek(-1)

    def test_one_operation_pins_catalog_and_cold_start_is_empty(self):
        data=CurrentCombatCatalog()
        with patch('wlre.services.items.live_combat_catalog._source',return_value=None):self.assertEqual(data['skills'],{})
        @one_catalog
        def read():return data['skills'],data['items']
        with patch('wlre.services.items.live_combat_catalog._source',side_effect=[{'skills':{'1':{}},'items':{'2':{}}}]) as source:
            self.assertEqual(read(),({'1':{}},{'2':{}}));self.assertEqual(source.call_count,1)

    def test_server_keys_survive_cold_start_and_catalog_change_and_removal(self):
        state=State();state.player={'role_id':1};actor={'pid':1,'equips':[]}
        with patch('wlre.services.items.live_combat_catalog._source',return_value=None):
            apply_live(state,{'type':'player_combat_data','data':{'skills':[{'key':7,'level':2}]}})
            self.assertEqual(learned(state.snapshot(),actor),{})
        data={'skills':{},'items':{},'keys':{'7':123},'characters':[]}
        with patch('wlre.services.items.live_combat_catalog._source',return_value=data):
            self.assertIn('123',learned(state.snapshot(),actor))
            apply_live(state,{'type':'attribute_set','entity':'self','kind':110,'parameter':123,'value':0})
            self.assertNotIn('123',learned(state.snapshot(),actor))
            data['keys']['7']=456
            self.assertIn('456',learned(state.snapshot(),actor))

    def test_equipment_received_before_catalog_can_be_resolved(self):
        state=State();state.player={'role_id':1}
        with patch('wlre.services.items.live_combat_catalog._source',return_value=None):
            apply_live(state,{'type':'player_equip_data','equips':[{'item_id':22,'damage':3}]})
            self.assertEqual(state.knowledge['player']['unresolved_equips'][0]['item_id'],22)
            apply_live(state,{'type':'equip_damage','index':3,'npc_index':0,'damage':10})
        with patch('wlre.services.items.live_combat_catalog._source',return_value={'items':{'22':{'fit_type':3}},'npcs':{}}):
            _,actor=field_context(state.snapshot());self.assertEqual(actor['equips'][2],{'item_id':22,'damage':10})

    def test_saved_settings_survive_missing_catalog_without_authorizing_actions(self):
        from wlre.services.battle.auto_battle import defaults,validate
        from wlre.services.items.maintenance import validate as maintenance,cleanup_action,is_repair
        value=defaults();value['profiles']['player']['deadAction']['id']=12345
        with patch('wlre.services.items.live_combat_catalog._source',return_value=None):
            self.assertEqual(validate(value)['profiles']['player']['deadAction']['id'],12345)
            self.assertEqual(maintenance({'repair_items':[34104,0]})['repair_items'],[34104,0])
            self.assertFalse(is_repair(34104));self.assertIsNone(cleanup_action(34104))

    def test_rejected_lua_index_never_replaces_last_usable_index(self):
        metadata=b'synthetic metadata';digest=hashlib.sha256(metadata).hexdigest()
        source=b'synthetic cipher';sha=hashlib.sha256(source).hexdigest()
        md5=hashlib.md5(source).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)/'combat_sources';version=base/'1.3.23';version.mkdir(parents=True)
            (base/('metadata-'+digest)).write_bytes(metadata)
            for path in sources.LUA_PATHS:(version/Path(path).name).write_bytes(source)
            old='\n'.join(path+'|'+md5 for path in sources.LUA_PATHS).encode()
            changed=old.replace(md5.encode(),b'0'*32)
            (version/'LuaScriptPathList.txt').write_bytes(old)
            known={Path(path).name:(sha,'0'*64) for path in sources.LUA_PATHS}
            with patch.object(sources,'METADATA_SHA256',digest),patch.object(sources,'KNOWN_FILES',known), \
                 patch.object(sources.Budget,'get',return_value=changed),self.assertRaises(ValueError):
                sources.load_inputs(folder,'1.3.23',download=True,open_url=lambda:None)
            self.assertEqual((version/'LuaScriptPathList.txt').read_bytes(),old)
            self.assertTrue(list((base/'rejected').glob('index-*')))

    def test_companion_slots_survive_cold_start_without_inventing_learned_skills(self):
        state=State();state.player={'role_id':1}
        data={'index':1,'npc_id':9,'skill_slots':[{'level':2},{'level':0}], 'equips':[]}
        actor={'pid':9,'master_id':1,'npc_index':1,'equips':[]}
        with patch('wlre.services.items.live_combat_catalog._source',return_value=None):
            apply_live(state,{'type':'companion_snapshot','companions':[data]})
            self.assertEqual(learned(state.snapshot(),actor),{})
        with patch('wlre.services.items.live_combat_catalog._source',return_value={'npcs':{'9':{'skills':[123,456]}},'items':{},'skills':{},'characters':[]}):
            self.assertEqual(set(learned(state.snapshot(),actor)),{'123'})

    def test_failed_refresh_is_not_reported_as_successful_cached_update(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sources,'_load_inputs',side_effect=ValueError('new format')),self.assertRaises(ValueError):
                sources.load_inputs(folder,'1.3.23',download=True)
            with patch.object(sources,'_load_inputs') as read,self.assertRaisesRegex(ValueError,'等待重試'):
                sources.load_inputs(folder,'1.3.23')
            read.assert_not_called()
            with patch.object(sources,'_load_inputs',return_value=({},{})):
                self.assertEqual(sources.load_inputs(folder,'1.3.23',download=True),({},{}))
                self.assertEqual(sources.load_inputs(folder,'1.3.23'),({},{}))
