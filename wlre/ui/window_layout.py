"""Shared centered popup sizing and single-border dialog policy.

All dialogs use the main dashboard's center instead of the screen center.
Clamp popups to the visible display; fixed geometry cannot be resized.
"""
import tkinter as tk


def _fit_mapped_display(window):
    """WM 加上原生框架後，再依實際位置限制可見內容大小。"""
    if '_display_fit_binding' in vars(window):
        return
    pending = None

    def fit():
        nonlocal pending
        pending = None
        try:
            if not window.winfo_exists() or not window.winfo_ismapped():
                return
            width, height = window.winfo_width(), window.winfo_height()
            # 原生座標／內容尺寸可能各自四捨五入，保留一個實體座標單位。
            available_width = max(1, window.winfo_screenwidth() - max(0, window.winfo_x()) - 1)
            available_height = max(1, window.winfo_screenheight() - max(0, window.winfo_y()) - 1)
            fitted = min(width, available_width), min(height, available_height)
            if fitted == (width, height):
                return
            minimum = window.minsize()
            window.minsize(min(minimum[0], fitted[0]), min(minimum[1], fitted[1]))
            if not any(window.resizable()):
                window.maxsize(*fitted)
            # 只改內容尺寸，保留 WM 已決定的位置，避免標題列偏移重複累加。
            window.geometry(f'{fitted[0]}x{fitted[1]}')
        except tk.TclError:
            try:
                alive = window.winfo_exists()
            except tk.TclError:
                alive = False
            if alive:
                raise

    def schedule(event):
        nonlocal pending
        if event.widget is window and pending is None:
            pending = window.after_idle(fit)

    window.bind('<Map>', schedule, add='+')
    window._display_fit_binding = True


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
        # 保留邊緣空間供原生標題列／視窗框，避免 WM 映射後把內容推到螢幕外。
        x = max(0, min(sw-w-margin, mx+(mw-w)//2))
        y = max(0, min(sh-h-margin, my+(mh-h)//2))
    except (AttributeError, TypeError):
        x, y = max(0, (sw-w)//2), max(0, (sh-h)//2)
    window.geometry(f'{w}x{h}+{x}+{y}')
    window.minsize(w, h)
    window.maxsize(w, h)
    window.resizable(False, False)
    _fit_mapped_display(window)
    return w, h, x, y


def configure_dialog(window, width, height):
    if '_no_glass_border' not in vars(window):
        window._no_glass_border = True
    root = window._root()
    center_on_main(window, root, width, height)
