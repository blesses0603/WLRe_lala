"""場景欄位契約與公開控制器；合成資料不代表正式遊戲驗收。"""
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_official_resource_manager import Fixture, scene_source
from test_official_scene_references import model_asset, text_source, verified_main

from wlre.features.scene_data.controller import SceneDataController
from wlre.resources_runtime.official.contracts import (
    SCENE_DEFINITIONS,
    TEXT_DEFINITIONS,
    ResourceStatus,
)
from wlre.resources_runtime.official.manager import (
    OfficialResourceManager,
    ResourceRefreshError,
)
from wlre.resources_runtime.official.references import audit_scene_references
from wlre.resources_runtime.official.scene_fields import (
    assess_scene_fields,
    scene_field_summary,
)
from wlre.resources_runtime.parsers.scenes import parse_scene_table
from wlre.resources_runtime.parsers.texts import parse_text_table


def assessments():
    scenes = parse_scene_table(scene_source(11016, 12170))
    texts = parse_text_table(text_source((12016, '官方場景甲')))
    references = audit_scene_references(scenes, texts, verified_main(model_asset()))
    return assess_scene_fields(scenes.records, references)


class SceneFieldTests(unittest.TestCase):
    def test_names_models_and_dimensions_do_not_approve_navigation(self):
        first, second = assessments()
        self.assertTrue(first.label_ready)
        self.assertFalse(second.label_ready)
        self.assertEqual(first.status('model_manifest'), ResourceStatus.VALID)
        self.assertEqual(first.status('map_dimensions'), ResourceStatus.VALID)
        for row in (first, second):
            self.assertFalse(row.map_ready)
            self.assertFalse(row.navigation_ready)
            self.assertFalse(row.teleport_ready)
            self.assertEqual(row.status('coordinate_mapping'), ResourceStatus.UNKNOWN)
            self.assertEqual(row.status('dynamic_obstacles'), ResourceStatus.UNKNOWN)

    def test_zero_size_is_retained_as_missing_not_deleted_or_called_invalid(self):
        scene = {**dict(parse_scene_table(scene_source(11016)).records[0]), 'map_width': 0}
        refs = audit_scene_references(SimpleNamespace(records=(scene,)), None, verified_main())
        result = assess_scene_fields((scene,), refs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status('map_dimensions'), ResourceStatus.MISSING)
        self.assertFalse(result[0].map_ready)

    def test_foreign_or_ambiguous_reference_is_rejected(self):
        scenes = parse_scene_table(scene_source(11016))
        refs = audit_scene_references(scenes, None, verified_main())
        for references in ((), refs * 2, (replace(refs[0], model_id=42),),
                           (replace(refs[0], name_id=42),)):
            with self.subTest(references=references), self.assertRaises(ValueError):
                assess_scene_fields(scenes.records, references)

    def test_fields_are_immutable_and_unknown_field_is_not_valid(self):
        row = assessments()[0]
        with self.assertRaises(FrozenInstanceError):
            row.name = '改寫'
        with self.assertRaises(FrozenInstanceError):
            row.fields[0].code = '改寫'
        with self.assertRaises(KeyError):
            row.status('unreviewed_field')

    def test_summary_counts_each_missing_field_and_does_not_claim_readiness(self):
        summary = scene_field_summary(assessments())
        self.assertEqual(summary['fields']['name'], {'VALID': 1, 'MISSING': 1})
        self.assertEqual(summary['fields']['map_dimensions'], {'VALID': 2})
        self.assertEqual(summary['fields']['walkable_grid'], {'UNKNOWN': 2})
        self.assertEqual(summary['label_ready_count'], 1)
        self.assertEqual(summary['navigation_ready_count'], 0)
        self.assertEqual(summary['teleport_ready_count'], 0)
        self.assertEqual(scene_field_summary(())['fields']['name'], {})

    def test_query_and_receipt_have_same_fields_and_are_revoked_on_close(self):
        fixture = Fixture()
        with (tempfile.TemporaryDirectory() as root,
              patch('wlre.resources_runtime.parsers.unity_textasset._loader', fixture.loader),
              OfficialResourceManager(root, opener=fixture.open) as manager):
            service = manager.refresh('2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,))
            self.assertEqual(service.scene_field_summary(), manager.diagnose('scenes')['document']['scene_fields'])
            self.assertEqual(len(service.scene_assessments()), 2)
            summary = service.scene_field_summary()
            summary['fields']['name']['UNKNOWN'] = 99
            self.assertEqual(service.scene_field_summary()['fields']['name'], {'UNKNOWN': 2})
        for query in (service.scene_assessments, service.scene_field_summary):
            with self.assertRaises(ResourceRefreshError):
                query()


class SceneControllerTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.api.status.return_value = SimpleNamespace(phase='idle', job_id=0, snapshot_id=None, workers=0)
        self.controller = SceneDataController(self.api)
        self.window = Mock()
        self.window.winfo_exists.return_value = True
        self.controller.window = self.window

    def test_refresh_uses_explicit_current_scope_requirements_only(self):
        self.controller.refresh('2.0.0')
        self.api.refresh.assert_called_once_with('2.0.0', scope='scene_references',
                                                 requirements=(SCENE_DEFINITIONS, TEXT_DEFINITIONS))
        self.api.current.assert_not_called()

    def test_old_view_is_not_rendered_while_updating_or_failed(self):
        for phase in ('refreshing', 'failed', 'cancel_requested', 'cancelled'):
            self.api.status.return_value = SimpleNamespace(phase=phase, job_id=1, snapshot_id=None, workers=0)
            self.controller.tick()
            self.assertIsNone(self.window.render.call_args.args[1])
        self.api.current.assert_not_called()

    def test_current_renders_once_per_snapshot_and_cancel_clears_view(self):
        self.api.status.return_value = SimpleNamespace(phase='current', job_id=1, snapshot_id='abc', workers=0)
        self.controller.tick()
        self.controller.tick()
        self.window.render.assert_called_once()
        self.assertIs(self.window.render.call_args.args[1], self.api.current.return_value)
        self.api.status.return_value = SimpleNamespace(phase='cancelled', job_id=1, snapshot_id=None, workers=0)
        self.controller.cancel()
        self.api.cancel.assert_called_once()
        self.assertIsNone(self.window.render.call_args.args[1])

    def test_close_detaches_api_and_destroys_owned_window(self):
        self.controller.close()
        self.window.destroy.assert_called_once()
        self.assertIsNone(self.controller.window)
        self.assertIsNone(self.controller._api)


class ScenePublicationCancellationTests(unittest.TestCase):
    def test_close_during_atomic_commit_returns_without_waiting_and_never_grants_view(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        fixture = Fixture()
        entered, release = Event(), Event()
        with (tempfile.TemporaryDirectory() as root,
              patch('wlre.resources_runtime.parsers.unity_textasset._loader', fixture.loader),
              OfficialResourceManager(root, opener=fixture.open) as manager):
            commit = manager._store.commit

            def delayed_commit(*args, **kwargs):
                entered.set()
                if not release.wait(3):
                    raise AssertionError('提交競態測試未釋放')
                return commit(*args, **kwargs)

            with patch.object(manager._store, 'commit', side_effect=delayed_commit), ThreadPoolExecutor(2) as pool:
                refresh = pool.submit(manager.refresh, '2.0.0', scope='scenes', requirements=(SCENE_DEFINITIONS,))
                try:
                    self.assertTrue(entered.wait(2))
                    # 提交仍停在磁碟寫入，close 必須獨立返回，不等待該工作。
                    pool.submit(manager.close).result(timeout=0.5)
                finally:
                    release.set()
                with self.assertRaises(InterruptedError):
                    refresh.result(timeout=2)
            self.assertEqual(manager.diagnose('scenes')['status'], 'unverified_cache_diagnostic_only')
