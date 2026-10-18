"""Bounded Kivy textures from bundled PNG archives; no desktop Tk dependency."""
import io
import json
import zipfile
from collections import OrderedDict
from kivy.core.image import Image as CoreImage
from kivy.uix.image import Image
from kivy.metrics import dp
from wlre.paths import RESOURCE_ROOT

_CACHE = OrderedDict()


def texture(archive, entry):
    key = archive, entry
    if key not in _CACHE:
        with zipfile.ZipFile(RESOURCE_ROOT / archive) as source:
            _CACHE[key] = CoreImage(io.BytesIO(source.read(entry)), ext='png')
    _CACHE.move_to_end(key)
    maps = [k for k in _CACHE if k[0] == 'smallmaps.zip']
    for old in maps[:-4]: _CACHE.pop(old, None)
    while len(_CACHE) > 100: _CACHE.popitem(last=False)
    return _CACHE[key].texture


def item_image(sid, size=40):
    if not hasattr(item_image, 'mapping'):
        item_image.mapping = json.loads((RESOURCE_ROOT/'item_icon_map.json').read_text(encoding='utf8'))['items']
    entry = item_image.mapping.get(str(sid), {}).get('icon', 's1000')+'.png'
    try: value = texture('item_icons.zip', entry)
    except (KeyError, OSError, ValueError): value = texture('item_icons.zip', 's1000.png')
    return Image(texture=value, size_hint=(None, None), size=(dp(size), dp(size)))


def emoji_entries():
    if not hasattr(emoji_entries, 'catalog'):
        emoji_entries.catalog = json.loads((RESOURCE_ROOT/'emoji_catalog.json').read_text(encoding='utf8'))['entries']
    return emoji_entries.catalog


def emoji_texture(index):
    data = emoji_entries().get(str(index))
    if not data or not data.get('available', True): return None
    try: return texture('emoji_images.zip', data['sprite']+'.png')
    except (KeyError, OSError, ValueError): return None
