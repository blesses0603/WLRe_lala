"""Official WLRE play/pause pictograms shared by automatic controls.

These are UI-only images; state transitions and server commands remain owned
by the existing automation services. Missing files fall back to text buttons.
"""
from functools import lru_cache

from PIL import Image, ImageOps, ImageTk
from wlre.paths import RESOURCE_ROOT


ASSET_DIR = RESOURCE_ROOT / 'assets' / 'automation-controls'
ASSETS = {'play': 'Auto_Play.png', 'pause': 'Auto_Pause.png'}


@lru_cache(maxsize=6)
def control_icon_image(action, size=28):
    filename = ASSETS.get(action)
    if filename is None or type(size) is not int or not 12 <= size <= 96:
        return None
    try:
        with Image.open(ASSET_DIR / filename) as source:
            return ImageOps.contain(
                source.convert('RGBA'), (size, size),
                Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None


def control_icon_photo(widget, action, size=28):
    icon = control_icon_image(action, size)
    return ImageTk.PhotoImage(icon, master=widget) if icon is not None else None


def apply_control_icon(button, action, size=28):
    """Change *appearance only*. Keep the original button command and text."""
    icon = control_icon_photo(button, action, size)
    if icon is None:
        return False
    button.configure(image=icon, compound='none', width=0,
                     padding=(2, 1))
    button._automation_control_icon = icon
    return True
