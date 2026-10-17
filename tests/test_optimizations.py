import json,multiprocessing,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch


def concurrent_writer(directory,index,barrier):
    from wlre.storage import login_memory
    from wlre.services.items.crafting_browser_model import Favorites
    from wlre.services.items.crafting import RECIPES
    original=login_memory._read
    def slow_read(file):
        value=original(file);time.sleep(0.04);return value
    login_memory._read=slow_read
    favorites=Favorites(Path(directory)/'favorites.json')
    barrier.wait(timeout=15)
    login_memory.save('fixture',16988,f'account-{index}',None,True,False,file=Path(directory)/'login.json')
    favorites.toggle(int(list(RECIPES)[index]))


def crash_with_lock(file,ready):
    from wlre.storage.atomic import file_lock
    with file_lock(file):
        ready.set();os._exit(0)


class SharedFiles(unittest.TestCase):
    def test_two_processes_preserve_accounts_and_favorites(self):
        context=multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as directory:
            barrier=context.Barrier(2)
            workers=[context.Process(target=concurrent_writer,args=(directory,index,barrier)) for index in range(2)]
            try:
                for worker in workers:worker.start()
                for worker in workers:worker.join(30);self.assertEqual(worker.exitcode,0)
                self.assertEqual(len(json.loads((Path(directory)/'login.json').read_text())['entries']),2)
                self.assertEqual(len(json.loads((Path(directory)/'favorites.json').read_text())['items']),2)
                self.assertFalse(list(Path(directory).glob('*.tmp')))
            finally:
                for worker in workers:
                    if worker.is_alive():worker.terminate();worker.join()

    def test_crashed_process_does_not_leave_permanent_lock(self):
        from wlre.storage.atomic import file_lock
        context=multiprocessing.get_context('spawn')
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'settings.json';ready=context.Event()
            worker=context.Process(target=crash_with_lock,args=(file,ready));worker.start()
            try:
                self.assertTrue(ready.wait(15));worker.join(15);self.assertEqual(worker.exitcode,0)
                with file_lock(file,timeout=0.2):pass
            finally:
                if worker.is_alive():worker.terminate();worker.join()

    def test_stale_favorite_views_merge_distinct_changes(self):
        from wlre.services.items.crafting_browser_model import Favorites
        from wlre.services.items.crafting import RECIPES
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'favorites.json';a=Favorites(file);b=Favorites(file)
            ids=list(RECIPES);a.toggle(int(ids[0]));b.toggle(int(ids[1]))
            self.assertEqual(set(Favorites(file).ids),set(map(int,ids[:2])))
            c=Favorites(file);d=Favorites(file)
            c.toggle(int(ids[2]));d.toggle(int(ids[2]))
            self.assertIn(int(ids[2]),Favorites(file).ids)


class AccountPreferences(unittest.TestCase):
    def test_account_and_line_preferences_are_isolated_without_credentials(self):
        from wlre.storage import account_settings as store
        from wlre.services.battle.auto_battle import defaults
        with tempfile.TemporaryDirectory() as directory:
            a=store.identity('fixture',123,'private-account-a',1)
            b=store.identity('fixture',123,'private-account-b',1)
            c=store.identity('fixture',123,'private-account-a',2)
            settings=defaults();settings['field_heal']=True
            settings['recovery']['hp']['player_percent']=37
            settings['party_guard']={'enabled':True,'members':[{'role_id':99,'name':'fixture-member'}]}
            store.save(a,settings,directory);store.save(b,defaults(),directory)
            self.assertTrue(store.load(a,directory)['field_heal'])
            self.assertEqual(store.load(a,directory)['recovery']['hp']['player_percent'],37)
            self.assertFalse(store.load(b,directory)['field_heal'])
            self.assertNotEqual(a,c)
            for file in Path(directory).rglob('*.json'):
                self.assertNotIn('private-account',file.read_text())
            with patch('wlre.services.battle.party_guard.load',return_value={'enabled':False,'members':[]}):
                self.assertFalse(store.load(c,directory)['field_heal'])

    def test_invalid_settings_do_not_overwrite_saved_preferences(self):
        from wlre.storage import account_settings as store
        from wlre.services.battle.auto_battle import defaults
        with tempfile.TemporaryDirectory() as directory:
            key=store.identity('fixture',123,'fixture');store.save(key,defaults(),directory)
            file=store.settings_file(key,directory);before=file.read_bytes()
            with self.assertRaises(ValueError):store.save(key,{'password':'do-not-store'},directory)
            self.assertEqual(before,file.read_bytes())
            file.write_text('[]')
            with self.assertRaises(ValueError):store.load(key,directory)
            self.assertEqual(file.read_text(),'[]')


class HealthLogs(unittest.TestCase):
    def test_metrics_are_numeric_and_logs_rotate_per_process(self):
        from wlre.core.diagnostics import Diagnostics
        with tempfile.TemporaryDirectory() as directory:
            health=Diagnostics(directory)
            handler=health.logger.handlers[0];handler.maxBytes=180
            for index in range(8):
                health.last=0;health.poll(index,100,12.5,True);health.error()
            health.close()
            files=list(Path(directory).glob('health-*'))
            self.assertLessEqual(len(files),3)
            self.assertTrue(all(str(os.getpid()) in f.name for f in files))
            content=''.join(f.read_text() for f in files)
            self.assertIn('ui_',content)
            self.assertNotIn('password',content)

    def test_unwritable_log_location_does_not_stop_client(self):
        from wlre.core.diagnostics import Diagnostics
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'not-a-directory';file.write_text('fixture')
            health=Diagnostics(file);health.poll(1,2,3,False);health.close()
