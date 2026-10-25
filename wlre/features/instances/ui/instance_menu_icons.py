"""Optional authentic 1262 sidebar sprites.

The right-side menu icons in the supplied game screenshot are not included
in the currently tracked official function-icons subset. Do not upscale or
cut out screenshot pixels. The client uses text until these original
transparent Unity sprites are supplied as PNG files.
"""
from functools import lru_cache
from PIL import Image, ImageOps, ImageTk
from wlre.paths import RESOURCE_ROOT

MENU_ASSETS = {
    '副本': 'Menu_Dungeon.png',
    '主要': 'Menu_Dungeon.png',
    '協力': 'Menu_Cooperate.png',
    '任務': 'Menu_Tasks.png',
    '活動': 'Menu_Events.png',
    '公會委託': 'Menu_GuildCommission.png',
}


@lru_cache(maxsize=12)
def menu_icon_image(title, size=29):
    name = MENU_ASSETS.get(title)
    if not name:
        return None
    path = RESOURCE_ROOT / 'assets' / 'instance-menu' / name
    if not path.is_file():
        return None
    try:
        with Image.open(path) as original:
            return ImageOps.contain(original.convert('RGBA'),
                                    (size,size),Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None


def menu_icon_photo(widget, title, size=29):
    image = menu_icon_image(title, size)
    return ImageTk.PhotoImage(image, master=widget) if image is not None else None
