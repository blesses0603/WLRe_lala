import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from emoji_fixtures import catalog
class EmojiUI(unittest.TestCase):
    def test_cold_start_current_png_same_key_update_and_invalidation(self):
        import tkinter as tk
        from wlre.ui.chat_emoji import EmojiImages
        try:root=tk.Tk()
        except tk.TclError as e:self.skipTest(str(e))
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            runtime=SimpleNamespace(emoji_catalog=None,catalog_identity=SimpleNamespace(key='a'))
            with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime),patch('wlre.storage.bundled_database.load_bundled_bytes',side_effect=AssertionError('old')):
                images=EmojiImages(root);self.assertIsNone(images.get('[Emoji1]'))
                runtime.emoji_catalog=catalog(Path(directory)/'db');one=images.get('[Emoji1]');self.assertIsNotNone(one)
                runtime.emoji_catalog=catalog(Path(directory)/'db','b'*64,'green');two=images.get('[Emoji1]');self.assertIsNot(one,two)
                runtime.emoji_catalog=None;self.assertIsNone(images.get('[Emoji1]'));self.assertFalse(images.cache)
    def test_open_picker_is_closed_and_messages_redrawn_on_source_loss(self):
        import tkinter as tk
        from wlre.ui.chat_ui import ChatPanel
        try:root=tk.Tk()
        except tk.TclError as e:self.skipTest(str(e))
        self.addCleanup(root.destroy)
        with tempfile.TemporaryDirectory() as directory:
            runtime=SimpleNamespace(emoji_catalog=catalog(Path(directory)/'db'),catalog_identity=SimpleNamespace(key='a'))
            with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime):
                panel=ChatPanel(root,SimpleNamespace());panel.pack();root.update()
                panel.show_emoji_picker();root.update();self.assertTrue(panel.emoji_picker.winfo_exists())
                runtime.emoji_catalog=None
                panel.after_cancel(panel.emoji_timer);panel.refresh_emoji_source();root.update()
                self.assertFalse(panel.emoji_picker.winfo_exists());self.assertFalse(panel.emojis.catalog)
                panel.destroy()
