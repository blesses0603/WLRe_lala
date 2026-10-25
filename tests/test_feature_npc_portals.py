"""P3 NPC/portal UI extraction retains guarded public callbacks."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.home_map import HomeMap
from wlre.features.npc.panel import NPCInteractionMixin
from wlre.features.portals.panel import PortalInteractionMixin


class FeatureOwnershipContracts(unittest.TestCase):
    def test_legacy_npc_and_portal_callbacks_still_available(self):
        for name in ('choose_npc', 'select_npc', 'update_npc_buttons',
                     'interact_npc', 'next_npc', 'show_npc_shop',
                     'close_npc_shop_dialog', 'show_npc_choices',
                     'choose_npc_reply', 'close_npc_option',
                     'view_npc_text', 'view_npc_history',
                     'show_dialogue_status'):
            with self.subTest(method=name):
                self.assertIs(getattr(HomeMap, name),
                              getattr(NPCInteractionMixin, name))
        for name in ('update_portal_button', 'choose_portal',
                     'select_portal', 'go_portal', 'show_audit'):
            with self.subTest(method=name):
                self.assertIs(getattr(HomeMap, name),
                              getattr(PortalInteractionMixin, name))

    def test_disabled_npc_interaction_never_sends(self):
        page = NPCInteractionMixin()
        page.selected_npc = {'scene': 1, 'npc_index': 2, 'npc_id': 3,
                             'x': 4, 'y': 5}
        page.npc_talk_button = SimpleNamespace(cget=lambda key: 'disabled')
        page.on_npc = Mock()
        with patch('wlre.features.npc.panel.messagebox.askyesno') as confirm:
            page.interact_npc()
            confirm.assert_not_called()
        page.on_npc.assert_not_called()

    def test_npc_next_requires_explicit_enabled_control(self):
        page = NPCInteractionMixin()
        page.npc_next_button = SimpleNamespace(cget=lambda key: 'disabled')
        page.on_npc_next = Mock()
        page.next_npc()
        page.on_npc_next.assert_not_called()
        page.npc_next_button = SimpleNamespace(cget=lambda key: 'normal')
        page.next_npc()
        page.on_npc_next.assert_called_once_with({'type': 'npc_next'})

    def test_empty_portal_cannot_trigger_travel(self):
        page = PortalInteractionMixin()
        page.selected_portal = None
        page.on_portal = Mock()
        self.assertFalse(page.go_portal())
        page.on_portal.assert_not_called()

    def test_unverified_portal_target_stays_blocked(self):
        page = PortalInteractionMixin()
        page.selected_portal = {'id': 99}
        page.portals = Mock()
        page.maps = Mock()
        page.state = {'player': {'scene': 10000}}
        page.portal_status = Mock()
        page.on_portal = Mock()
        with patch('wlre.features.portals.panel.destination_problem',
                   return_value='目的地沒有可信場景對照'):
            self.assertFalse(page.go_portal())
        page.on_portal.assert_not_called()
        page.portals.direct_target.assert_not_called()
        self.assertIn('可信場景', page.portal_status.set.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
