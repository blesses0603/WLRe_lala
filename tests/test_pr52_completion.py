"""PR #52 installation lifecycle and 1275 optional-art cleanup regressions."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wlre.services.world import runtime_1275
from wlre.services.world.map_names import data as map_data,map_label


class RuntimeInstallation(unittest.TestCase):
    def tearDown(self):runtime_1275.clear_runtime_caches()
    def test_install_invalidates_prelogin_empty_map_and_instance_catalogues(self):
        from wlre.services.instance_browser import official_catalog
        runtime_1275.clear_runtime_caches()
        with patch.object(runtime_1275,'active_runtime',side_effect=runtime_1275.Runtime1275Unavailable('missing')):
            self.assertEqual(map_data()['maps'],{})
            self.assertFalse(official_catalog()['verified_source'])
        runtime_1275.clear_runtime_caches()
        self.assertEqual(official_catalog.cache_info().currsize,0)
        with patch.object(runtime_1275,'active_runtime',return_value=SimpleNamespace(
                stages={10000:{'name_id':1,'model_id':12910}},texts={1:'新版地圖'})):
            self.assertEqual(map_label(10000),'新版地圖(10000)')
    def test_staged_sources_are_verified_before_install_and_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=root/'data.zip';eve=root/'eve.zip'
            data.write_bytes(b'data');eve.write_bytes(b'eve');target=root/'install'
            preview=SimpleNamespace(revision=1275,items={},recipes={},scene_ids=[])
            def validate(a,b):
                if Path(a)==data:return preview
                self.assertEqual(Path(a).parent,target)
                self.assertEqual(Path(a).read_bytes(),b'data')
                self.assertEqual(Path(b).read_bytes(),b'eve')
                raise ValueError('staged source rejected')
            with patch('wlre.services.world.preview_1275.load_preview',side_effect=validate):
                with self.assertRaisesRegex(ValueError,'staged source'):
                    runtime_1275.install(data,eve,base=target,check_only=False)
            self.assertEqual(list(target.iterdir()),[])
            self.assertEqual(data.read_bytes(),b'data')


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires a desktop')
class OptionalArtworkCleanup(unittest.TestCase):
    def test_closing_settings_without_private_1275_art_has_no_callback_error(self):
        import tkinter as tk
        from wlre.ui.gui import App
        from wlre.ui.auto_battle_ui import SettingsEditor
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'LOCALAPPDATA':td}):
            root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
            try:
                app=App(root);editor=SettingsEditor(app)
                editor.window.destroy();root.update_idletasks()
                self.assertEqual(errors,[])
            finally:
                for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
                root.destroy()
            self.assertEqual(errors,[])
