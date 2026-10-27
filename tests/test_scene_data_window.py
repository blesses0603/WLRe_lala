"""官方場景唯讀頁：原生 Tk，沒有任何遊戲連線或正式 Bundle 下載。"""
import os
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from _tk_native_pump import create_root
from test_scene_fields import assessments

from wlre.features.scene_data.window import SceneDataWindow
from wlre.resources_runtime.official.scene_fields import scene_field_summary


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', '需要桌面顯示環境')
class SceneWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = create_root()
        self.controller = Mock()
        self.window = SceneDataWindow(self.root, self.controller)
        self.rows = assessments()
        self.service = SimpleNamespace(
            scene_assessments=lambda: self.rows,
            scene_field_summary=lambda: scene_field_summary(self.rows), validated_at='合成測試時間',
            versions=SimpleNamespace(observed_exe_version='2.0.0', data_version='9.8.7',
                                     data_package_version='合成 Data', main_package_version='合成 Main'))
        self.current = SimpleNamespace(phase='current', workers=0)
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def test_disposed_standalone_window_never_reaches_native_background_gc(self):
        import subprocess
        from pathlib import Path

        script = """
import gc, sys, tkinter as tk
from threading import Thread
from wlre.features.scene_data.window import SceneDataWindow
class Controller:
    def cancel(self): pass
gc.disable()
def cycle():
    root = tk.Tk()
    window = SceneDataWindow(root, Controller())
    root.destroy()
cycle()
errors = []
sys.unraisablehook = errors.append
worker = Thread(target=gc.collect)
worker.start(); worker.join(15)
if worker.is_alive() or errors:
    raise RuntimeError('window resources reached background GC')
print('scene-window owner cleanup passed')
"""
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                text=True, timeout=25, check=False,
                                cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('scene-window owner cleanup passed', result.stdout)

    def test_unknown_initial_version_does_not_start_a_download(self):
        self.window.refresh()
        self.controller.refresh.assert_not_called()
        self.assertIn('完整', self.window.phase.get())
        self.window.exe_version.set('2.0.0')
        self.window.refresh()
        self.controller.refresh.assert_called_once_with('2.0.0')

    def test_status_detail_separates_manifest_identity_and_geometry(self):
        self.window.render(self.current, self.service)
        self.window.tree.selection_set('11016')
        self.window.select()
        self.assertIn('僅資產索引已核對', self.window.detail.get())
        self.assertIn('官方掃描網格：尚未驗證', self.window.detail.get())
        self.assertIn('0 筆', self.window.summary.get())
        self.assertIn('合成 Data', self.window.source.get())

    def test_failed_refresh_immediately_clears_previous_scene_list(self):
        self.window.render(self.current, self.service)
        self.assertEqual(len(self.window.tree.get_children()), 2)
        self.window.render(SimpleNamespace(phase='failed', workers=0), None)
        self.assertEqual(self.window.tree.get_children(), ())
        self.assertEqual(self.window._rows, ())
        self.assertIn('先前快取不視為目前資料', self.window.phase.get())
        self.assertNotIn('合成 Data', self.window.source.get())

    def test_pagination_and_filter_do_not_drop_scenes(self):
        self.rows = tuple(replace(self.rows[0], scene_id=index) for index in range(237))
        self.window.render(self.current, self.service)
        self.assertEqual(len(self.window.tree.get_children()), 100)
        self.window.turn(1)
        self.assertEqual(self.window.tree.get_children()[0], '100')
        self.window.turn(1)
        self.assertEqual(len(self.window.tree.get_children()), 37)
        self.window.search.set('236')
        self.window.filter_rows()
        self.assertEqual(self.window.tree.get_children(), ('236',))
        self.window.search.set('官方場景甲')
        self.window.filter_rows()
        self.assertEqual(len(self.window._filtered), 237)

    def test_busy_disables_duplicate_download_and_enables_cancel(self):
        self.window.render(SimpleNamespace(phase='refreshing', workers=1), None)
        self.assertEqual(str(self.window.refresh_button['state']), 'disabled')
        self.assertEqual(str(self.window.cancel_button['state']), 'normal')
        self.window.cancel_button.invoke()
        self.controller.cancel.assert_called_once()

    def test_columns_are_fixed_and_no_horizontal_scrollbar_is_added(self):
        for column in self.window.tree['columns']:
            self.assertFalse(self.window.tree.column(column, 'stretch'))
        self.window.tree.identify_region = lambda x, y: 'separator'
        self.assertEqual(self.window._lock_separator(SimpleNamespace(x=1, y=1)), 'break')
        self.assertFalse(self.window.tree.cget('xscrollcommand'))


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt' or sys.platform == 'darwin', '需要桌面顯示環境')
class SceneDesktopPipelineTests(unittest.TestCase):
    def test_public_gui_refresh_reaches_scene_rows_without_game_commands(self):
        import tempfile
        import time
        import tkinter as tk
        import zlib
        from unittest.mock import patch

        from test_official_resource_manager import Fixture
        from test_official_scene_references import combined_manifest, text_source

        from wlre.resources_runtime.official.contracts import (
            SCENE_DEFINITIONS,
            TEXT_DEFINITIONS,
        )
        from wlre.resources_runtime.official.module import OfficialResourceModule
        from wlre.ui.application_host import DesktopHost

        fixture = Fixture()
        raw = combined_manifest()
        fixture.files[fixture.base + 'DataPackage.bytes'] = raw
        fixture.files[fixture.base + 'DataPackage.hash'] = zlib.crc32(raw).to_bytes(4, 'little').hex().encode()
        sources = {SCENE_DEFINITIONS.asset_path: fixture.raw,
                   TEXT_DEFINITIONS.asset_path: text_source((12016, '合成場景甲'), (13170, '合成場景乙'))}

        def loader(path):
            return SimpleNamespace(container={asset: SimpleNamespace(type=SimpleNamespace(name='TextAsset'),
                read=lambda data=data, asset=asset: SimpleNamespace(
                    name=asset.rsplit('/', 1)[1].removesuffix('.bytes'), script=data))
                for asset, data in sources.items()})

        with (tempfile.TemporaryDirectory() as cache,
              patch('wlre.ui.version_gate_controller.VersionGateController.start_version_check'),
              patch('wlre.resources_runtime.parsers.unity_textasset._loader', loader)):
            root = create_root()
            host = DesktopHost(root, resource_module=OfficialResourceModule(cache, opener=fixture.open))
            try:
                host.start()
                app = host.module.app
                app.open_official_scene_data()
                window = app._official_scene_data.window
                window.exe_version.set('2.0.0')
                window.refresh_button.invoke()
                done = tk.BooleanVar(root, value=False)
                deadline = time.monotonic() + 5

                def check():
                    if window.tree.exists('12170') or time.monotonic() >= deadline:
                        done.set(True)
                    else:
                        root.after(10, check)

                root.after(0, check)
                root.wait_variable(done)
                self.assertEqual(window.tree.item('12170', 'values')[1], '合成場景乙')
                self.assertTrue(app.commands.empty(), '唯讀資源核對不能產生遊戲指令')
                window.tree.selection_set('12170')
                window.select()
                root.update_idletasks()
                self.assertLessEqual(window.footer_label.winfo_rooty() + window.footer_label.winfo_height(),
                                     window.winfo_rooty() + window.winfo_height())
                view = host.resources.api.current()
            finally:
                host.finish()
            from wlre.resources_runtime.official.manager import ResourceRefreshError
            with self.assertRaises(ResourceRefreshError):
                view.scene_assessments()
