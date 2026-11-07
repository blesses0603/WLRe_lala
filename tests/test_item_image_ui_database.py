import io,os,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image

@unittest.skipUnless(os.environ.get('DISPLAY'),'Tk display required')
class ItemImageUI(unittest.TestCase):
    def test_existing_photo_refresh_and_destroy_cancel_timer(self):
        import tkinter as tk
        from wlre.ui.crafting.item_icons import ItemIcons
        from wlre.services.world.item_image_database import ItemImageCatalog
        def catalog(key,color):
            stream=io.BytesIO();Image.new('RGBA',(8,8),color).save(stream,format='PNG')
            images=SimpleNamespace(database='/synthetic/items.sqlite3',catalog_key=key,models={1000},png=lambda sid:stream.getvalue())
            return ItemImageCatalog(images,{79:1000})
        runtime=SimpleNamespace(item_images=catalog('a','red'))
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime):
            root=tk.Tk();self.addCleanup(root.destroy);window=tk.Toplevel(root)
            icons=ItemIcons(window);photo=icons.get(79,8);label=tk.Label(window,image=photo);label.pack()
            root.update();self.assertEqual(root.tk.call(str(photo),'get',0,0),(255,0,0))
            runtime.item_images=catalog('b','blue');icons.get(79,8)
            self.assertEqual(root.tk.call(str(photo),'get',0,0),(0,0,255))
            runtime.item_images=None;icons.get(79,8)
            self.assertTrue(root.tk.call(str(photo),'transparency','get',0,0))
            window.destroy();self.assertTrue(icons.closed)
            self.assertFalse(icons.cache)
