"""Shared centered popup sizing and single-border dialog policy.

All dialogs use the main dashboard's center instead of the screen center.
Clamp popups to the visible display; fixed geometry cannot be resized.
"""


def dialog_geometry(width, height, screen_width, screen_height, *, margin=24):
    usable_width = max(1, screen_width-margin)
    usable_height = max(1, screen_height-margin)
    w = max(1, min(width, 1240, usable_width))
    h = max(1, min(height, 760, usable_height))
    x = max(0, (screen_width-w)//2)
    y = max(0, (screen_height-h)//2)
    return w, h, x, y


def center_on_main(window, main, width, height, *, margin=24):
    """Size and center a toplevel on the dashboard; keep it on screen."""
    sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
    w, h, _, _ = dialog_geometry(width, height, sw, sh, margin=margin)
    # The dashboard already has a geometry even while initially withdrawn.
    try:
        mx, my = main.winfo_x(), main.winfo_y()
        mw, mh = main.winfo_width(), main.winfo_height()
        if mw <= 1 or mh <= 1:
            mw, mh = 1280, 800
        x = max(0, min(sw-w, mx+(mw-w)//2))
        y = max(0, min(sh-h, my+(mh-h)//2))
    except (AttributeError, TypeError):
        x, y = max(0, (sw-w)//2), max(0, (sh-h)//2)
    window.geometry(f'{w}x{h}+{x}+{y}')
    window.minsize(w, h)
    window.maxsize(w, h)
    window.resizable(False, False)
    return w, h, x, y


def configure_dialog(window, width, height):
    if '_no_glass_border' not in vars(window):
        window._no_glass_border = True
    root = window._root()
    center_on_main(window, root, width, height)
