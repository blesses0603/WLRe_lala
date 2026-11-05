"""Runtime identity changes must invalidate every cached display/action snapshot."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.wire import ProtocolError
from wlre.services.world.dynamic_bundle_runtime import current_catalog_token
from wlre.ui.expedition.panel import ExpeditionPanel
from wlre.ui.expedition.planner import ExpeditionPlannerMixin
from wlre.ui.crafting_browser import CraftingBrowser
from wlre.ui.crafting_plan_ui import PlanWindow
from wlre.ui.bag_grid import BagGrid
from wlre.services.world.portal_travel import PortalTravel
from wlre.services.expedition.manager import Expedition


class RuntimeConsumerRefreshTests(unittest.TestCase):
    def test_token_distinguishes_prepublish_invalidated_and_republished_sources(self):
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=None) as current, \
             patch('wlre.services.world.dynamic_bundle_runtime.dynamic_attempted',return_value=False) as attempted:
            before=current_catalog_token()
            attempted.return_value=True
            failed=current_catalog_token()
            current.return_value=SimpleNamespace(catalog_identity=SimpleNamespace(key='a'*64))
            first=current_catalog_token()
            current.return_value=SimpleNamespace(catalog_identity=SimpleNamespace(key='b'*64))
            self.assertEqual(len({before,failed,first,current_catalog_token()}),4)

    def expedition_page(self):
        return SimpleNamespace(_catalog_token=(True,'a'),catalog={'tasks':{}},
            _load_catalog=Mock(return_value={'tasks':{'1':{'name':'new'}}}),
            signature='old',plan_key='old',plans={'1':'old'},
            plan_future=Mock(),plan_job='job',after_cancel=Mock(),
            render=Mock(),app=SimpleNamespace(snapshot={'expedition':{}}))

    def test_expedition_catalog_reload_cancels_old_prediction_and_timer(self):
        page=self.expedition_page()
        old_future=page.plan_future
        with patch('wlre.ui.expedition.panel.current_catalog_token',return_value=(True,'b')):
            self.assertTrue(ExpeditionPanel.refresh_runtime_catalog(page))
            self.assertFalse(ExpeditionPanel.refresh_runtime_catalog(page))
        old_future.cancel.assert_called_once_with()
        old_future.result.assert_not_called()
        page.after_cancel.assert_called_once_with('job')
        self.assertEqual(page.catalog['tasks']['1']['name'],'new')
        self.assertIsNone(page.signature)
        self.assertEqual(page.plans,{})
        page._load_catalog.assert_called_once_with()

    def test_background_expedition_result_cannot_restore_previous_catalog_plans(self):
        page=self.expedition_page()
        old_future=page.plan_future
        page.refresh_runtime_catalog=lambda:ExpeditionPanel.refresh_runtime_catalog(page)
        with patch('wlre.ui.expedition.panel.current_catalog_token',return_value=(True,'b')):
            ExpeditionPlannerMixin.collect_plans(page)
        old_future.cancel.assert_called_once_with()
        old_future.result.assert_not_called()
        page.render.assert_called_once_with(page.app.snapshot)

    def test_crafting_runtime_change_invalidates_cards_and_recovers_new_favorites_without_rewriting(self):
        from wlre.services.items.crafting import RECIPES
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'favorites.json'
            original='{"version":1,"items":[1,2]}'
            path.write_text(original)
            page=SimpleNamespace(_catalog_token=(True,'a'),grid_key='old',detail_key='old',
                tool_key='old',state_key='old',rows=[{'item_id':1}],selected=1,page=2,
                favorite_store=SimpleNamespace(path=path,ids=[1]))
            with patch.dict(RECIPES,{'2':{'item_id':2}},clear=True), \
                 patch('wlre.ui.crafting_browser.current_catalog_token',return_value=(True,'b')):
                self.assertTrue(CraftingBrowser.refresh_runtime_catalog(page))
                self.assertFalse(CraftingBrowser.refresh_runtime_catalog(page))
            self.assertEqual(page.favorite_store.ids,[1,2])
            self.assertEqual(path.read_text(),original)
            self.assertIsNone(page.selected)
            self.assertIsNone(page.grid_key)
            self.assertIsNone(page.detail_key)
            self.assertIsNone(page.tool_key)

    def test_bag_repaints_when_source_or_name_changes_without_inventory_revision(self):
        record={'index':1,'item_id':7,'count':3}
        inventory={'items':{'1':record},'ready':True,'reliable':True,'capacity':24}
        page=SimpleNamespace(index_selected=None,compact=False,page=0,page_size=24,
            columns=6,row_count=4,summary=Mock(),page_label=Mock(),_signature=None,_paint=Mock())
        with patch('wlre.ui.bag_grid.visible_items',return_value=[('1',record,'old')]) as rows, \
             patch('wlre.ui.bag_grid.available',return_value=3), \
             patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=(True,'a')) as token:
            BagGrid.render(page,inventory)
            BagGrid.render(page,inventory)
            self.assertEqual(page._paint.call_count,1)
            token.return_value=(True,'b')
            BagGrid.render(page,inventory)
            self.assertEqual(page._paint.call_count,2)
            rows.return_value=[('1',record,'new')]
            BagGrid.render(page,inventory)
            self.assertEqual(page._paint.call_count,3)

    def test_portal_catalog_reloads_on_same_numeric_revision_with_new_identity(self):
        old=SimpleNamespace(data={'source_revision':1286},for_scene=Mock(return_value=[]))
        new=SimpleNamespace(data={'source_revision':1286},for_scene=Mock(return_value=[]))
        state=State()
        state.player={'role_id':1,'scene':12170}
        with patch('wlre.services.world.portal_travel.current_catalog_token',return_value=(True,'a')) as token:
            travel=PortalTravel(old)
            token.return_value=(True,'b')
            with patch('wlre.services.world.portal_travel.Portals',return_value=new) as loader:
                with self.assertRaises(ProtocolError):
                    travel.start_direct(state,Mock(),7,0)
            loader.assert_called_once_with()
            old.for_scene.assert_not_called()
            self.assertIs(travel.catalog,new)

    def test_queued_old_portal_never_triggers_after_runtime_replacement(self):
        state=State()
        movement=Mock()
        with patch('wlre.services.world.portal_travel.current_catalog_token',return_value=(True,'a')) as token:
            travel=PortalTravel()
            travel.pending={'id':7}
            token.return_value=(True,'b')
            self.assertEqual(travel.tick(state,movement,0),[])
        self.assertIsNone(travel.pending)
        self.assertEqual(state.portal_travel['status'],'cancelled')
        movement.stop.assert_called_once()

    def test_expedition_never_dispatches_from_previous_catalog_after_replacement(self):
        state=State()
        state.expedition.update(enabled=True,uncertain=False)
        with patch('wlre.services.expedition.manager.current_catalog_token',return_value=(True,'a')) as token:
            service=Expedition()
            token.return_value=(True,'b')
            self.assertEqual(service.tick(state,100),[])
        self.assertFalse(state.expedition['enabled'])
        self.assertIn('官方資源已更新',state.expedition['status'])

    def test_item_metadata_uses_one_runtime_snapshot_for_name_price_and_revision(self):
        from wlre.services.items.catalog import verified_item_metadata
        item={'name':'new','price':100,'sell_price':50,'restrict':0,'open_used':0,'need_level':1}
        first=SimpleNamespace(items={7:item},revision=1286)
        second=SimpleNamespace(items={},revision=1287)
        with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
             patch('wlre.services.world.runtime_1275.active_runtime',side_effect=[first,second]) as active:
            metadata=verified_item_metadata(7)
        self.assertEqual(metadata['name'],'new')
        self.assertEqual(metadata['source_revision'],1286)
        active.assert_called_once_with()

    def test_feature_note_uses_live_sources_instead_of_obsolete_1275_classification(self):
        from wlre.services.world.feature_resource_index import describe_feature, FEATURE_TABLES
        names={name for tables in FEATURE_TABLES.values() for name in tables}
        runtime=SimpleNamespace(source_sha256={name:'a'*64 for name in names})
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime), \
             patch('wlre.services.world.feature_resource_index._current_index') as historical:
            for feature in FEATURE_TABLES:
                result=describe_feature(feature)
                self.assertEqual(result['state'],'verified_runtime')
                self.assertEqual(result['collected'],result['required'])
                self.assertFalse(result['can_send_packets'])
            historical.assert_not_called()

    def test_saved_crafting_plan_preserves_missing_item_without_keyerror(self):
        from wlre.services.items.crafting import RECIPES
        page=SimpleNamespace(rows=[{'item_id':7,'count':2}],row_images={},
            table=Mock(),window=Mock(),panel=SimpleNamespace(icons=Mock()))
        page.table.get_children.return_value=()
        with patch.dict(RECIPES,{},clear=True),patch('wlre.ui.crafting_plan_ui.item_name',return_value='物品7'):
            PlanWindow.refresh(page)
        self.assertEqual(page.table.insert.call_args.kwargs['values'][-1],'配方待更新')

    def test_auto_battle_item_labels_are_not_pinned_to_cached_names(self):
        from wlre.ui.auto_battle.model import action_label, action_entries
        with patch('wlre.ui.auto_battle.model.item_display_name',return_value='新名稱'), \
             patch('wlre.ui.auto_battle.model.supply_catalogue',return_value=((7,'舊名稱'),)):
            self.assertEqual(action_label({'kind':2,'id':7}),'新名稱 (7)')
            entries=action_entries({'inventory':{'items':{}}},'player',True)
        self.assertIn('新名稱',dict(entries)[7])
        self.assertNotIn('舊名稱',dict(entries)[7])
