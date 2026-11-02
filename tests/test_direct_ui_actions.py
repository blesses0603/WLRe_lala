"""An explicit UI action submits once without an extra yes/no dialog."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.attribute_points_ui import AttributePointWindow
from wlre.ui.crafting_ui import CraftingPanel
from wlre.ui.crafting_plan_ui import PlanWindow
from wlre.ui.services_ui import PartyPanel, AlchemyPanel


class DirectUIActionsTests(unittest.TestCase):
    def setUp(self):
        confirmation=patch('tkinter.messagebox.askyesno',
                           side_effect=AssertionError('不應跳出二次確認'))
        confirmation.start();self.addCleanup(confirmation.stop)

    def test_crafting_add_keeps_material_validation_before_direct_submission(self):
        page=SimpleNamespace(state={'player':{'role_id':1}},status=Mock(),
                             app=SimpleNamespace(send=Mock()))
        with patch('wlre.ui.crafting_ui.recipe_plan') as preflight:
            CraftingPanel.add(page,100,2)
            preflight.assert_called_once()
            page.app.send.assert_called_once_with(
                {'type':'craft','action':'add','item_id':100,'count':2})
            page.app.send.reset_mock()
            preflight.side_effect=ValueError('材料不足')
            CraftingPanel.add(page,100,2)
            page.app.send.assert_not_called()
            page.status.set.assert_called_with('材料不足')

    def test_queue_delete_requires_selection_without_an_extra_prompt(self):
        page=SimpleNamespace(state={'crafting':{'revision':3}},status=Mock(),
                             app=SimpleNamespace(send=Mock()))
        CraftingPanel.command(page,'delete')
        page.app.send.assert_not_called()
        CraftingPanel.command(page,'delete',2)
        page.app.send.assert_called_once_with(
            {'type':'craft','action':'delete','index':2,'revision':3})

    def test_plan_clear_respects_edit_lock_and_start_keeps_revision_sequence(self):
        rows=[{'item_id':100,'count':2}]
        page=SimpleNamespace(rows=list(rows),editable=Mock(return_value=False),
            refresh=Mock(),status=Mock(),panel=SimpleNamespace(
                state={'crafting':{'local_plan':{'revision':3}}},
                app=SimpleNamespace(live_active=True,send=Mock())))
        PlanWindow.clear(page)
        self.assertEqual(page.rows,rows)
        page.editable.return_value=True
        PlanWindow.clear(page)
        self.assertEqual(page.rows,[])
        page.rows=list(rows)
        with patch('wlre.ui.crafting_plan_ui.validate_rows',return_value=rows):
            PlanWindow.start(page)
        self.assertEqual(page.panel.app.send.call_count,2)
        self.assertEqual(page.panel.app.send.call_args_list[0].args[0],
            {'type':'craft','action':'plan_set','rows':rows,'revision':3})
        self.assertEqual(page.panel.app.send.call_args_list[1].args[0],
            {'type':'craft','action':'plan_start','revision':4})

    def test_attribute_allocation_locks_after_direct_submission(self):
        page=SimpleNamespace(base={'str':10},add={'str':2},locked=lambda:False,
            queued=False,note=Mock(),show_values=Mock(),
            app=SimpleNamespace(send=Mock(return_value=True)))
        AttributePointWindow.confirm(page)
        page.app.send.assert_called_once_with({'type':'allocate_points',
            'baseline':{'str':10},'increments':{'str':2}})
        self.assertTrue(page.queued)
        page.app.send.reset_mock();page.locked=lambda:True
        AttributePointWindow.confirm(page)
        page.app.send.assert_not_called()

    def test_team_actions_need_selection_but_no_second_confirmation(self):
        page=SimpleNamespace(members=Mock(),act=Mock())
        page.members.selection.return_value=()
        PartyPanel.member_action(page,'kick')
        page.act.assert_not_called()
        page.members.selection.return_value=('123',)
        PartyPanel.member_action(page,'kick')
        page.act.assert_called_once_with('kick',role_id=123)
        page.act.reset_mock()
        PartyPanel.leave_team(page)
        page.act.assert_called_once_with('leave')

    def test_alchemy_keeps_preflight_and_does_not_submit_invalid_settings(self):
        page=SimpleNamespace(mode=Mock(),runs=Mock(),slots=[],
            app=SimpleNamespace(snapshot={},send=Mock(),root=None))
        page.mode.get.return_value='初級';page.runs.get.return_value='2'
        with patch('wlre.ui.services_ui.prepare') as preflight:
            AlchemyPanel.begin(page)
            preflight.assert_called_once()
            page.app.send.assert_called_once_with(
                {'type':'start_alchemy','mode':'初級','runs':2,'materials':[]})
            page.app.send.reset_mock()
            preflight.side_effect=ValueError('材料不足')
            with patch('tkinter.messagebox.showinfo') as error:
                AlchemyPanel.begin(page)
            error.assert_called_once()
            page.app.send.assert_not_called()


if __name__=='__main__':unittest.main()
