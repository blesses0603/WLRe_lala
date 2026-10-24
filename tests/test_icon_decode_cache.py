"""Decoded ZIP sprite cache and independent Tk image lifetime regressions."""
import io
import unittest
from unittest.mock import patch

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

    def test_windows_share_pixels_not_tk_photo_objects_or_zip_lifetimes(self):
        files = {'shared.png': png('red'), 's1000.png': png('black')}
        first = MemoryArchive(files, filename='/fixture/item_icons.zip')
        second = MemoryArchive(files, filename='/fixture/item_icons.zip')
        photos = []
        def photo(_pixels, master):
            result = object()
            photos.append((master, result))
            return result
        DECODED_SPRITES.clear()
        with patch('wlre.services.world.runtime_1275.baseline_revision',
                   return_value='1262'), \
             patch('wlre.ui.crafting.item_icons.zipfile.ZipFile',
                   side_effect=[first, second]), \
             patch('wlre.ui.crafting.item_icons.ICON_MAP',
                   {'42': {'icon': 'shared'}}), \
             patch('wlre.ui.crafting.item_icons.ImageTk.PhotoImage', side_effect=photo):
            a = ItemIcons(master='window-a')
            b = ItemIcons(master='window-b')
            item_a = a.get(42, 24)
            self.assertIs(item_a, a.get(42, 24))
            item_b = b.get(42, 24)
            self.assertIsNot(item_a, item_b)
            self.assertEqual(photos[0][0], 'window-a')
            self.assertEqual(photos[1][0], 'window-b')
            self.assertEqual(first.calls, ['shared.png'])
            self.assertEqual(second.calls, [])
            a.close()
            self.assertTrue(first.closed)
            self.assertFalse(second.closed)
            self.assertIs(item_b, b.get(42, 24))
            b.close()
            self.assertTrue(second.closed)
        DECODED_SPRITES.clear()


if __name__ == '__main__':
    unittest.main()
