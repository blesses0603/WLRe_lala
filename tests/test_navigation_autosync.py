import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from wlre.services.world.navigation_autosync import NavigationAutoSync
from wlre.services.world.navigation_preview import REVIEWED_COORDINATE_CATALOGS


def runtime():
    return SimpleNamespace(catalog_identity=SimpleNamespace(key=next(iter(REVIEWED_COORDINATE_CATALOGS))),
                           stages={12170: {'model_id': 12170}, 10001: {'model_id': 10001}})


def state(scene=12170):
    return {'phase': 'world_ready', 'player': {'role_id': 1, 'scene': scene}}


class AutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.runtime = runtime()
        self.source = [self.runtime]
        self.cache = {}
        self.loader = Mock(side_effect=lambda path, key, model: self.cache.get((key, model)))
        self.sync = Mock(side_effect=lambda identity, model, **kw: self.cache.update({(identity.key, model): {}}))
        self.job = NavigationAutoSync(runtime_getter=lambda: self.source[0], loader=self.loader, sync=self.sync)
        self.addCleanup(self.job.close)

    def finish(self):
        self.job.worker.join(2)
        self.assertFalse(self.job.worker.is_alive())

    def test_missing_model_downloads_once_and_never_replays_action(self):
        self.assertEqual(self.job.update(state(), enabled=True)['status'], 'working')
        self.finish()
        for _ in range(30):
            value = self.job.update(state(), enabled=True)
        self.assertEqual(value['status'], 'ready')
        self.assertIn('不會自動移動', value['message'])
        self.sync.assert_called_once()
        self.assertEqual(self.sync.call_args.args[1], 12170)
        self.assertFalse(hasattr(self.job, 'commands'))
        self.assertEqual(set(value), {'status', 'message'})

    def test_existing_cache_is_validated_without_fetch(self):
        self.cache[(self.runtime.catalog_identity.key, 12170)] = {}
        self.job.update(state(), enabled=True); self.finish()
        self.sync.assert_not_called()
        self.assertEqual(self.loader.call_count, 2)

    def test_error_explicit_no_automatic_retry_or_fallback(self):
        self.sync.side_effect = OSError('offline')
        self.job.update(state(), enabled=True); self.finish()
        for _ in range(5):
            value = self.job.update(state(), enabled=True)
        self.assertEqual(value['status'], 'error')
        self.assertIn('未使用舊版資料', value['message'])
        self.sync.assert_called_once()
        self.job.update(state(), enabled=True, retry=True); self.finish()
        self.assertEqual(self.sync.call_count, 2)

    def test_integrity_error_does_not_fetch_or_silently_replace(self):
        self.loader.side_effect = ValueError('integrity failure')
        self.job.update(state(), enabled=True); self.finish()
        self.assertEqual(self.job.update(state(), enabled=True)['status'], 'error')
        self.sync.assert_not_called()

    def block(self):
        self.entered = threading.Event(); self.release = threading.Event()
        def sync(identity, model, *, cancelled, **kw):
            self.entered.set(); self.release.wait(2)
            if cancelled():
                raise ValueError('cancelled')
            self.cache[(identity.key, model)] = {}
        self.sync.side_effect = sync
        self.job.update(state(), enabled=True)
        self.assertTrue(self.entered.wait(1))
        self.addCleanup(self.release.set)

    def test_concurrent_polls_and_retries_do_not_spawn_more_workers(self):
        self.block()
        for _ in range(10):
            self.job.update(state(), enabled=True, retry=True)
        self.sync.assert_called_once()
        self.release.set(); self.finish()

    def test_scene_change_drops_old_result_and_then_downloads_new_model(self):
        self.block()
        self.assertEqual(self.job.update(state(10001), enabled=True)['status'], 'cancelling')
        self.release.set(); self.finish()
        self.assertNotIn((self.runtime.catalog_identity.key, 12170), self.cache)
        self.job.update(state(10001), enabled=True); self.finish()
        self.assertEqual(self.job.update(state(10001), enabled=True)['status'], 'ready')
        self.assertEqual(self.sync.call_args.args[1], 10001)

    def test_cancel_does_not_restart_until_explicit_retry(self):
        self.block(); self.job.cancel(); self.release.set(); self.finish()
        self.assertEqual(self.job.update(state(), enabled=True)['status'], 'cancelled')
        self.sync.assert_called_once()
        self.job.update(state(), enabled=True, retry=True); self.finish()
        self.assertEqual(self.sync.call_count, 2)

    def test_offline_or_resource_hold_cancels_without_using_completed_result(self):
        self.block()
        self.assertEqual(self.job.update(state(), enabled=False)['status'], 'blocked')
        self.release.set(); self.finish()
        self.assertEqual(self.cache, {})
        self.job.update(state(), enabled=False, retry=True)
        self.sync.assert_called_once()

    def test_close_and_runtime_change_discard_inflight_results(self):
        self.block(); self.source[0] = runtime()
        self.release.set(); self.finish()
        self.assertEqual(self.cache, {})
        self.job.close()
        self.assertEqual(self.job.update(state(), enabled=True)['status'], 'closed')

    def test_unknown_scene_house_unknown_version_and_missing_runtime_fail_closed(self):
        for scene in (99999, 63501):
            self.assertEqual(self.job.update(state(scene), enabled=True)['status'], 'blocked')
        self.runtime.catalog_identity.key = 'unknown'
        self.assertEqual(self.job.update(state(), enabled=True)['status'], 'blocked')
        self.source[0] = None
        self.assertEqual(self.job.update(state(), enabled=True)['status'], 'blocked')
        self.sync.assert_not_called(); self.loader.assert_not_called()

    def test_ui_hold_and_offline_gate_and_manual_retry(self):
        from wlre.ui.gui import App
        app = SimpleNamespace(navigation_sync=Mock(), home_map=SimpleNamespace(navigation_status=Mock()),
                              live_active=True, stop_event=threading.Event(),
                              _session_resource_hold=threading.Event(), snapshot=state())
        app.navigation_sync.update.return_value = {'message': 'test'}
        App.poll_navigation_sync(app, retry=True)
        self.assertTrue(app.navigation_sync.update.call_args.kwargs['enabled'])
        self.assertTrue(app.navigation_sync.update.call_args.kwargs['retry'])
        app._session_resource_hold.set()
        App.poll_navigation_sync(app)
        self.assertFalse(app.navigation_sync.update.call_args.kwargs['enabled'])
        app._session_resource_hold.clear(); app.live_active=False
        App.poll_navigation_sync(app)
        self.assertFalse(app.navigation_sync.update.call_args.kwargs['enabled'])


class SyncCancellationTests(unittest.TestCase):
    def test_cancel_before_start_never_observes_fetches_or_imports(self):
        import tempfile
        from wlre.services.world.navigation_sync import sync_model
        identity = SimpleNamespace(key=next(iter(REVIEWED_COORDINATE_CATALOGS)), packages=[])
        observe, fetch = Mock(), Mock()
        with tempfile.TemporaryDirectory() as root, patch('wlre.services.world.navigation_sync.import_cache') as publish:
            with self.assertRaisesRegex(ValueError, '取消'):
                sync_model(identity, 12170, root=root, cancelled=lambda: True, observe=observe, fetch=fetch)
        observe.assert_not_called(); fetch.assert_not_called(); publish.assert_not_called()

    def test_same_model_preview_and_auto_sync_are_serialized(self):
        from wlre.services.world.navigation_sync import sync_model
        entered, release = threading.Event(), threading.Event()
        identity = SimpleNamespace(key='test')
        calls = []
        def work(*args, **kwargs):
            calls.append(1); entered.set(); release.wait(2)
        with patch('wlre.services.world.navigation_sync._sync_model', side_effect=work):
            first = threading.Thread(target=lambda: sync_model(identity, 12170))
            first.start(); self.assertTrue(entered.wait(1))
            # A competing cancelled preview must not reach the inner importer.
            with self.assertRaisesRegex(ValueError, '取消'):
                sync_model(identity, 12170, cancelled=lambda: True)
            release.set(); first.join(2)
        self.assertEqual(calls, [1])

    def test_navigation_entry_buttons_are_wired(self):
        import ast
        from pathlib import Path
        tree = ast.parse(Path('wlre/ui/home_map.py').read_text())
        buttons = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'Button':
                kwargs = {k.arg: k.value for k in node.keywords}
                if isinstance(kwargs.get('text'), ast.Constant) and 'command' in kwargs:
                    buttons[kwargs['text'].value] = ast.unparse(kwargs['command'])
        self.assertEqual(buttons['導航預覽'], 'self.on_navigation')
        self.assertEqual(buttons['同步導航'], 'on_sync')
        self.assertEqual(buttons['取消同步'], 'on_cancel_sync')


if __name__ == '__main__':
    unittest.main()
