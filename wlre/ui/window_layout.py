"""Shared centered popup sizing and single-border dialog policy.

The main dashboard retains its supported 1280x800 design; popup windows fit
their usable screen area and never add a redundant cyan glass outline.
"""


def dialog_geometry(width, height, screen_width, screen_height, *, margin=24):
    """Return fixed dimensions and centered coordinates for small screens."""
    usable_width = max(1, screen_width-margin)
    usable_height = max(1, screen_height-margin)
    w = max(1, min(width, 1240, usable_width))
    h = max(1, min(height, 760, usable_height))
    x = max(0, (screen_width-w)//2)
    y = max(0, (screen_height-h)//2)
    return w, h, x, y


def configure_dialog(window, width, height):
    # Default popups have one decoration layer rather than a double outline.
    # Preserve an explicitly assigned False for windows requesting an outline.
    if '_no_glass_border' not in vars(window):
        window._no_glass_border = True
    w, h, x, y = dialog_geometry(
        width, height, window.winfo_screenwidth(), window.winfo_screenheight())
    window.geometry(f'{w}x{h}+{x}+{y}')
    window.minsize(w, h)
    window.maxsize(w, h)
    window.resizable(False, False)
