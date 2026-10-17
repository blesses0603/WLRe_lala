import json,os,tempfile,unittest
from pathlib import Path
from wlre.storage import account_settings as store,server_lines
from wlre.services.battle.auto_battle import defaults


class ServerAccountSettings(unittest.TestCase):
    def test_official_lines_share_while_accounts_and_servers_stay_separate(self):
        lines=server_lines.load();earth=[r for r in lines if r['id']//100==1];mercury=next(r for r in lines if r['id']//100==2)
        def key(row,account='fixture'):return store.identity(row['host'],row['port'],account,row['id'])
        self.assertEqual(key(earth[0]),key(earth[1]))
        self.assertNotEqual(key(earth[0]),key(mercury))
        self.assertNotEqual(key(earth[0]),key(earth[0],'another-account'))
        self.assertNotEqual(key(earth[0]),store.identity('custom.invalid',16988,'fixture',earth[0]['id']))

    def test_latest_legacy_line_is_migrated_without_deleting_or_overwriting_old_files(self):
        lines=[r for r in server_lines.load() if r['id']//100==1]
        with tempfile.TemporaryDirectory() as directory:
            originals={}
            for index,row in enumerate(lines[:2]):
                old=store._hash([row['host'],row['port'],'fixture',row['id']])
                value=defaults();value['field_heal']=bool(index)
                store.save(old,value,directory);file=store.settings_file(old,directory)
                os.utime(file,ns=(1000000000+index,1000000000+index));originals[file]=file.read_bytes()
            first,second=lines[:2];key=store.identity(first['host'],first['port'],'fixture',first['id'])
            legacy=store.legacy_identities(first['host'],first['port'],'fixture',first['id'])
            self.assertTrue(store.load(key,directory,legacy)['field_heal'])
            value=defaults();store.save(key,value,directory)
            second_key=store.identity(second['host'],second['port'],'fixture',second['id'])
            self.assertFalse(store.load(second_key,directory,store.legacy_identities(second['host'],second['port'],'fixture',second['id']))['field_heal'])
            for file,before in originals.items():self.assertEqual(file.read_bytes(),before)

    def test_corrupt_legacy_profile_is_reported_without_creating_shared_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            key=store.identity('fixture',123,'account')
            legacy=store.legacy_identities('fixture',123,'account',3)
            file=store.settings_file(legacy[0],directory);file.parent.mkdir(parents=True);file.write_text('[]')
            with self.assertRaises(ValueError):store.load(key,directory,legacy)
            self.assertFalse(store.settings_file(key,directory).exists());self.assertEqual(file.read_text(),'[]')
