"""Regression for real Smith persistence and truthful dynamic gate display."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from wlre.services.world.resource_database import record_inventory, read_catalog_tables
from wlre.services.world.smith_candidate import parse_smith_records
from wlre.services.world.resource_rebuilder import read_processing_summary
from wlre.ui.version_gate_controller import VersionGateController, _is_verified_login_result


def smith(record_size=35,keys=(1,),item=7,seconds=5):
    rows=[]
    for key in keys:
        row=bytearray(33)
        struct.pack_into('<H',row,0,item)
        row[7]=1
        struct.pack_into('<HB',row,8,8,2)
        row[23]=1
        struct.pack_into('<H',row,24,seconds)
        rows.append((struct.pack('<H',key) if record_size==35 else b'')+row)
    return struct.pack('<i',len(rows))+b''.join(rows)


class RecipePersistenceTests(unittest.TestCase):
    def test_both_reviewed_layouts_are_indexed_from_raw_tables(self):
        for size in (33,35):
            with self.subTest(size=size),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'inventory.sqlite3'
                raw=smith(size)
                report=record_inventory(path,'a'*64,{'tables/a/SmithData_C.bytes':raw})
                self.assertEqual(report['smith_rows']['status'],'parsed')
                self.assertEqual(report['smith_rows']['count'],1)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM parsed_resource_rows WHERE source='smith_v1'").fetchone()[0],1)
                retry=record_inventory(path,'a'*64,{'tables/a/SmithData_C.bytes':raw})
                self.assertEqual(retry['smith_rows'],report['smith_rows'])

    def test_duplicate_products_preserve_recipe_identity_and_version_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inventory.sqlite3'
            record_inventory(path,'a'*64,{'tables/a/SmithData_C.bytes':smith(keys=(1,2))})
            result=record_inventory(path,'b'*64,{'tables/a/SmithData_C.bytes':smith(keys=(1,3),seconds=9)})
            self.assertEqual(result['smith_rows']['count'],2)
            self.assertEqual(result['smith_rows']['added'],['3'])
            self.assertEqual(result['smith_rows']['changed'],['1'])
            self.assertEqual(result['smith_rows']['removed'],['2'])

    def test_unknown_layout_reports_failure_without_losing_other_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inventory.sqlite3'
            with patch('wlre.services.world.npc_talk.parse_talk_data',return_value={1:{'text':'fixture'}}):
                report=record_inventory(path,'a'*64,{
                    'tables/a/SmithData_C.bytes':smith()+b'trailing',
                    'tables/a/TalkData_C.bytes':b'talk'})
            self.assertEqual(report['smith_rows']['status'],'parse_failed')
            self.assertEqual(report['other_rows']['talk_v1']['status'],'parsed')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM resources').fetchone()[0],2)

    def test_reader_uses_both_layouts_and_same_catalog_item_references(self):
        for size in (33,35):
            with self.subTest(size=size),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'inventory.sqlite3'
                with patch('wlre.services.world.itemdata_v1.parse_itemdata',return_value={7:{},8:{}}):
                    record_inventory(path,'a'*64,{
                        'tables/a/SmithData_C.bytes':smith(size),'tables/a/ItemData_C.bytes':b'items'})
                    rows=read_catalog_tables(path,'a'*64,['recipes'])['recipes']
                    self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]['materials'],[{'item_id':8,'count':2}])
                with patch('wlre.services.world.itemdata_v1.parse_itemdata',return_value={7:{}}):
                    with self.assertRaises(ValueError):
                        read_catalog_tables(path,'a'*64,['recipes'])

    def test_duplicate_recipe_keys_and_unknown_layout_fail_closed(self):
        for raw in (smith(keys=(1,1)),smith()+b'X',b''):
            with self.subTest(raw_length=len(raw)),self.assertRaises(ValueError):
                parse_smith_records(raw)

    def test_processing_summary_counts_smith_success_and_failure_accurately(self):
        for state,expected in (('parsed','已解析'),('parse_failed','格式待處理')):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as directory:
                key='a'*64
                root=Path(directory)
                (root/key).mkdir()
                doc={'other_rows':{source:{'status':'parsed'} for source in (
                    'eve_npc_v1','eve_interact_v1','talk_v1','text_v1','scenes_v1')},
                     'item_rows':{'status':'parsed'},'smith_rows':{'status':state,'count':2}}
                member='candidate_indexes/table_changes.json'
                raw=json.dumps(doc).encode()
                meta={'catalog_key':key,'formal_approved':False,
                      'entries':{member:{'source':'derived_unapproved','size':len(raw),
                                         'sha256':hashlib.sha256(raw).hexdigest()}}}
                with ZipFile(root/key/'verified_raw_inventory.zip','w') as archive:
                    archive.writestr('inventory.json',json.dumps(meta))
                    archive.writestr(member,raw)
                summary=read_processing_summary(key,candidate_root=root)
                self.assertEqual(len(summary),7)
                self.assertEqual(summary['製作'],expected)
                self.assertEqual(sum(s=='已解析' for s in summary.values()),7 if state=='parsed' else 6)


class Var:
    def __init__(self,value=''):
        self.value=value
    def set(self,value):
        self.value=value
    def get(self):
        return self.value


class RuntimeGateDisplayTests(unittest.TestCase):
    def render(self,status):
        result={'status':status,'blocked':status!='database_matches_official','dynamic_runtime':'verified' if status=='database_matches_official' else 'unavailable',
                'baseline_label':'DataPackage 1286／MainPackage 1284','database_comparison':'same',
                'remote':{'status':'resources_changed','resource_path':'1.3.22.1','packages':{
                    'DataPackage':{'remote':'1286_full','comparison':'newer'},
                    'MainPackage':{'remote':'1284_full','comparison':'newer'}}}}
        if status=='database_matches_official':
            result.update(login_allowed=True,database_verified=True,data_compatibility='compatible',
                          protocol_compatibility='unverified')
            result['remote'].update(official_exe_version='1.3.0',newer_official_client=False)
            result['runtime_identity']={'data_ver':'1.3.22.1','exe_version':'1.3.0',
                'packages':[{'name':p,'full_version':v['remote']} for p,v in result['remote']['packages'].items()]}
        fake=SimpleNamespace(version_window=Mock(),_version_gate_result=result,
                             version_gate_state='ready' if status=='database_matches_official' else 'blocked',_launcher_catalog_status='',
                             _version_progress=Mock(),_version_continue_button=Mock())
        for name in ('baseline','main','data','path','remote','heading'):
            setattr(fake,'_version_'+name,Var())
        VersionGateController._render_version_window(fake)
        return fake

    def test_verified_runtime_does_not_display_old_baseline_or_zip_error(self):
        fake=self.render('database_matches_official')
        self.assertIn('可以登入',fake._version_heading.get())
        self.assertNotIn('版本異動',fake._version_heading.get())
        self.assertNotIn('1275',fake._version_baseline.get())
        self.assertIn('1284',fake._version_main.get())
        self.assertIn('Runtime 核對',fake._version_data.get())
        self.assertNotIn('ZIP',fake._version_remote.get())
        fake._version_continue_button.configure.assert_called_with(text='進入登入畫面',state='normal')

    def test_runtime_failure_is_actionable_and_distinct_from_protocol_pending(self):
        fake=self.render('runtime_unavailable')
        self.assertIn('Runtime 尚未就緒',fake._version_heading.get())
        self.assertNotIn('等待 LaLa 更新',fake._version_heading.get())

    def test_runtime_result_cannot_spoof_legacy_login_permission(self):
        result={'blocked':False,'status':'version_identifiers_match','dynamic_runtime':'verified',
                'protocol_compatibility':'unverified','remote':{'status':'same_resources','packages':{
                    p:{'comparison':'same'} for p in ('DataPackage','MainPackage')}}}
        self.assertFalse(_is_verified_login_result(result))
