"""User-supplied official 1275 Texture2D pictograms in LaLa tab style.

Only the transparent pictogram shapes are stored under assets/instance-menu.
The same circular backing plate, border and 34 px tab size are used as the
other dashboard tabs. No protocol or tab-navigation behavior changes.
"""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageOps, ImageTk

from wlre.paths import RESOURCE_ROOT


MENU_ASSETS = {
    '副本': 'Menu_Dungeon.png',
    '主要': 'Menu_Dungeon.png',
    '協力': 'Menu_Cooperate.png',
    '任務': 'Menu_Tasks.png',
    '活動': 'Menu_Events.png',
    '公會委託': 'Menu_GuildCommission.png',
}


@lru_cache(maxsize=24)
def menu_icon_image(title, size=34):
    """Render a transparent official glyph on the existing round tab badge."""
    name = MENU_ASSETS.get(title)
    if not name:
        return None
    path = RESOURCE_ROOT / 'assets' / 'instance-menu' / name
    if not path.is_file():
        return None
    try:
        with Image.open(path) as original:
            glyph = original.convert('RGBA')
        bounds = glyph.getchannel('A').getbbox()
        if not bounds:
            return None
        glyph = glyph.crop(bounds)
        # Keep palette, border, padding and supersampling identical to
        # function_icons.icon_image() for all other dashboard tabs.
        scale = 3
        badge = Image.new('RGBA', (size * scale, size * scale))
        draw = ImageDraw.Draw(badge)
        draw.ellipse((2, 2, size * scale - 3, size * scale - 3),
                     fill=(45, 81, 101, 230),
                     outline=(180, 225, 235, 235),
                     width=scale)
        foreground = ImageOps.contain(
            glyph, (size * scale - 20, size * scale - 20),
            Image.Resampling.LANCZOS)
        badge.alpha_composite(
            foreground,
            ((badge.width - foreground.width) // 2,
             (badge.height - foreground.height) // 2))
        return badge.resize((size, size), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None


def menu_icon_photo(widget, title, size=34):
    icon = menu_icon_image(title, size)
    return ImageTk.PhotoImage(icon, master=widget) if icon is not None else None
