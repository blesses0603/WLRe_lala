"""Bounded, cross-window cache of decoded Pillow item sprites.

Only decoded RGBA pixels are shared, never Tk PhotoImage handles; Tk images
must remain owned by their respective window/interpreter. Cache misses still
read only the requested ZIP member, and no ZIP archive handle is retained.
"""
import io
from collections import OrderedDict

from PIL import Image


class DecodedSpriteCache:
    def __init__(self, *, max_bytes=8 * 1024 * 1024, max_entries=128):
        if max_bytes <= 0 or max_entries <= 0:
            raise ValueError('sprite cache limits must be positive')
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self.bytes_used = 0

    def get(self, archive, name, size):
        # A disk path is stable across independent ZipFile instances; in-memory
        # archives use their object identity to prevent cross-archive leakage.
        location = getattr(archive, 'filename', None)
        source = str(location) if location is not None else id(archive)
        key = (source, name, size)
        if key in self._entries:
            self._entries.move_to_end(key)
            return self._entries[key]
        with Image.open(io.BytesIO(archive.read(name))) as raw:
            icon = raw.convert('RGBA')
            icon.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (size, size))
            canvas.alpha_composite(icon,
                                   ((size - icon.width) // 2, (size - icon.height) // 2))
        size_bytes = canvas.width * canvas.height * 4
        if size_bytes <= self.max_bytes:
            while (self._entries and
                   (len(self._entries) >= self.max_entries or
                    self.bytes_used + size_bytes > self.max_bytes)):
                _, old = self._entries.popitem(last=False)
                self.bytes_used -= old.width * old.height * 4
            self._entries[key] = canvas
            self.bytes_used += size_bytes
        return canvas

    def clear(self):
        self._entries.clear()
        self.bytes_used = 0

    def __len__(self):
        return len(self._entries)


DECODED_SPRITES = DecodedSpriteCache()
