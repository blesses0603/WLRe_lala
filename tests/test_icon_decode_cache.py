"""Decoded ZIP sprite cache and independent Tk image lifetime regressions."""
import io
import unittest
from unittest.mock import patch, Mock

from PIL import Image

from wlre.ui.crafting.icon_cache import DecodedSpriteCache, DECODED_SPRITES
from wlre.ui.crafting.item_icons import ItemIcons


def png(color):
    buffer = io.BytesIO()
    Image.new('RGBA', (4, 4), color).save(buffer, format='PNG')
    return buffer.getvalue()


class MemoryArchive:
    def __init__(self, members, filename=None):
        self.members = members
        self.filename = filename
        self.NameToInfo = {name: object() for name in members}
        self.calls = []
        self.closed = False

    def read(self, name):
        self.calls.append(name)
        return self.members[name]

    def close(self):
        self.closed = True


class DecodedItemSpriteCacheTests(unittest.TestCase):
    def test_bounded_cache_hits_without_repeat_zip_reads(self):
        files = {'one.png': png('red'), 'two.png': png('blue'),
                 'three.png': png('green')}
        archive = MemoryArchive(files)
        cache = DecodedSpriteCache(max_bytes=2 * 2 * 4 * 2, max_entries=2)
        first = cache.get(archive, 'one.png', 2)
        self.assertIs(first, cache.get(archive, 'one.png', 2))
        self.assertEqual(archive.calls, ['one.png'])
        cache.get(archive, 'two.png', 2)
        cache.get(archive, 'three.png', 2)
        self.assertLessEqual(cache.bytes_used, 32)
        self.assertEqual(len(cache), 2)
        # Oldest entry must be redecoded; the other two still reside in cache.
        cache.get(archive, 'one.png', 2)
        self.assertEqual(archive.calls.count('one.png'), 2)
        cache.clear()
        self.assertEqual(len(cache), 0)
        self.assertEqual(cache.bytes_used, 0)

    def test_oversized_sprite_is_never_retained(self):
        archive = MemoryArchive({'a.png': png('purple')})
        cache = DecodedSpriteCache(max_bytes=15)
        cache.get(archive, 'a.png', 2)
        cache.get(archive, 'a.png', 2)
        self.assertEqual(len(cache), 0)
        self.assertEqual(archive.calls, ['a.png', 'a.png'])

    def test_archive_identity_prevents_cross_archive_leakage(self):
        first = MemoryArchive({'a.png': png('red')})
        second = MemoryArchive({'a.png': png('blue')})
        cache = DecodedSpriteCache()
        self.assertNotEqual(cache.get(first, 'a.png', 3).getpixel((1, 1)),
                            cache.get(second, 'a.png', 3).getpixel((1, 1)))

    def test_windows_share_pixels_and_refresh_existing_handles(self):
        from types import SimpleNamespace
        from wlre.services.world.item_image_database import ItemImageCatalog
        read=Mock(return_value=png('red'))
        images=SimpleNamespace(database='/synthetic/items.sqlite3',catalog_key='a',models={1000,4321},png=read)
        catalog=ItemImageCatalog(images,{42:4321})
        runtime=SimpleNamespace(item_images=catalog)
        DECODED_SPRITES.clear()
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=runtime),patch(
                'wlre.ui.crafting.item_icons.ImageTk.PhotoImage',side_effect=lambda *a,**k:Mock()) as photos:
            a=ItemIcons('window-a');b=ItemIcons('window-b')
            photo=a.get(42,24);other=b.get(42,24)
            self.assertIsNot(photo,other);self.assertEqual(read.call_count,1)
            self.assertIs(photo,a.get(42,24))
            runtime.item_images=None
            a.refresh_source();self.assertEqual(photo.paste.call_count,1)
            self.assertEqual(photo.paste.call_args.args[0].getbbox(),None)
            runtime.item_images=ItemImageCatalog(SimpleNamespace(database=images.database,catalog_key='b',models=images.models,png=Mock(return_value=png('blue'))),{42:4321})
            a.refresh_source();self.assertEqual(photo.paste.call_count,2)
            self.assertEqual(photo.paste.call_args.args[0].getpixel((12,12)),(0,0,255,255))
            a.close();self.assertFalse(a.cache);self.assertIs(other,b.get(42,24));b.close()
        DECODED_SPRITES.clear()


if __name__ == '__main__':
    unittest.main()
