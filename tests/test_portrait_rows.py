import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from PIL import Image
from wlre.ui.portrait_rows import PortraitRows, placeholder, row_identity


def snapshot():
    return {'player': {'role_id': 1, 'sex': 1, 'head': 2, 'palette1': 444444444},
            'knowledge': {'active_npc_id': 101, 'companions': {
                '1': {'npc_id': 101, 'modeling': 202, 'stats': {'name': '夥伴'}}}}}


class PortraitIdentity(unittest.TestCase):
    def test_missing_identity_does_not_reuse_previous_character(self):
        self.assertIsNone(row_identity({}, 'player'))
        state = snapshot()
        self.assertEqual(row_identity(state, 'companion'), (1, 101, 202, None))
        state['knowledge']['active_npc_id'] = None
        self.assertIsNone(row_identity(state, 'companion'))

    def test_placeholder_is_only_a_neutral_transparent_ring(self):
        image = placeholder()
        self.assertEqual(image.size, (40, 40))
        self.assertEqual(image.getpixel((20, 20))[3], 0)
        self.assertEqual(image.getpixel((0, 0))[3], 0)


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'Requires a desktop')
class PortraitWidgets(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.geometry('430x110')
        self.rows = PortraitRows(self.root); self.rows.pack(fill='both', expand=True)
        self.root.update()
        self.state = snapshot()
        self.caption = '角色｜等級 147\nHP 10/20 SP 3/4\n夥伴（出戰）｜HP 8/9 SP 6/7'
        self.calls = []
        self.revision = 1
        def request(state, kind, size):
            self.calls.append((kind, size))
            # Synthetic solid pixels test UI ownership, never ship as artwork.
            return {'image': Image.new('RGBA', (40, 40), 'red'), 'revision': self.revision}
        self.provider = SimpleNamespace(request=request)

    def tearDown(self):
        self.root.destroy()

    def update(self, provider=None, live=True):
        self.rows.render_state(self.state, self.caption, live, provider)
        self.root.update()

    def test_two_images_are_left_of_separate_text_rows(self):
        self.update(self.provider)
        for kind in ('player', 'companion'):
            self.assertLess(self.rows.images[kind].winfo_x(), self.rows.texts[kind].winfo_x())
            self.assertEqual(self.rows.images[kind].cget('text'), '')
        self.assertLess(self.rows.images['player'].winfo_y(), self.rows.images['companion'].winfo_y())
        self.assertIn('角色', self.rows.texts['player'].cget('text'))
        self.assertIn('夥伴', self.rows.texts['companion'].cget('text'))

    def test_same_revision_keeps_handles_new_revision_rebuilds(self):
        self.update(self.provider); old = self.rows.photos.copy()
        self.update(self.provider)
        self.assertEqual(old, self.rows.photos)
        self.revision = 2; self.update(self.provider)
        self.assertIsNot(old['player'], self.rows.photos['player'])

    def test_role_and_companion_changes_clear_stale_image(self):
        self.update(self.provider); old = self.rows.photos['player']
        self.state['player']['role_id'] = 2; self.update(self.provider)
        self.assertIsNot(old, self.rows.photos['player'])
        self.state['knowledge']['active_npc_id'] = None; self.update(self.provider)
        self.assertIsNone(self.rows.keys['companion'][0])
        self.assertFalse(self.rows.keys['companion'][2])

    def test_missing_or_failed_provider_stays_pending_and_keeps_health(self):
        self.update()
        self.assertEqual(self.rows.images['player'].cget('text'), '待同步')
        self.assertIn('HP 10/20', self.rows.texts['player'].cget('text'))
        def fail(*args): raise ValueError('bad source')
        self.update(SimpleNamespace(request=fail))
        self.assertEqual(self.rows.images['player'].cget('text'), '待同步')

    def test_offline_and_no_login_are_distinct(self):
        self.update(self.provider, live=False)
        self.assertIn('最後同步', self.rows.texts['player'].full_text)
        self.state = {}; self.update(self.provider, live=False)
        self.assertEqual(self.rows.images['player'].cget('text'), '待同步')
        self.assertNotIn('最後同步', self.rows.texts['player'].full_text)

    def test_destroy_releases_only_window_handles_without_timer(self):
        self.update(self.provider)
        self.rows.destroy()
        self.assertTrue(self.rows.closed)
        self.assertFalse(self.rows.photos)
        self.assertFalse(self.rows.keys)

    def test_real_provider_pixels_arrive_without_widget_closing_source(self):
        from wlre.services.world.character_portraits import PortraitProvider
        import time
        catalog = SimpleNamespace(catalog_key='fixture', characters={(1, 2): 1}, npcs={},
                                  image=lambda *args: Image.new('RGBA', (32, 32), 'blue'))
        self.state['player']['palette5'] = 444444
        provider = PortraitProvider(source=lambda: catalog)
        try:
            for _ in range(50):
                self.update(provider)
                if self.rows.images['player'].cget('text') == '':
                    break
                time.sleep(.01)
            self.assertEqual(self.rows.images['player'].cget('text'), '')
            source = provider.request(self.state, 'player', 40)['image']
            self.rows.destroy()
            self.assertEqual(source.getpixel((0, 0)), (0, 0, 255, 255))
        finally:
            provider.close()

    def test_overview_owns_default_provider_but_not_injected_provider(self):
        from unittest.mock import Mock, patch
        from wlre.ui.overview_ui import OverviewPanel
        app = SimpleNamespace(open_resources=lambda: None, open_attributes=lambda: None)
        owned = Mock()
        with patch('wlre.services.world.character_portraits.PortraitProvider', return_value=owned):
            panel = OverviewPanel(self.root, app)
        job = panel.tick_job
        panel.destroy()
        owned.close.assert_called_once_with()
        self.assertNotIn(job, self.root.tk.call('after', 'info'))
        injected = Mock(); app.portrait_provider = injected
        panel = OverviewPanel(self.root, app)
        panel.destroy()
        injected.close.assert_not_called()
