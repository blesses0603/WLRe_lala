"""Non-modal function windows, each positioned at the dashboard's center."""
from tkinter import ttk
from wlre.ui.window_layout import center_on_main

# All dimensions are fixed *per display*. No user-resizable or draggable panes.
WINDOWS = {
    'party': ('組隊', 950, 620),
    'companion': ('夥伴出戰', 1040, 650),
    'expedition': ('遠征', 1080, 650),
    'instance': ('副本／協力房間管理', 1040, 600),
    'alchemy': ('煉金', 1040, 650),
    'crafting': ('製作', 1080, 650),
    'efficiency': ('經驗效率', 960, 610),
}


def make_feature(app, key, label, panel_type, *, align='left'):
    """Create a persistent hidden window and a lightweight tab launcher."""
    import tkinter as tk

    launcher = ttk.Frame(app.left_tabs, padding=16)
    app.left_tabs.add(launcher, text=label, align=align)
    ttk.Label(launcher, text=label + '管理', style='Heading.TLabel').pack(
        anchor='w', pady=(0, 8))
    ttk.Label(launcher, text='功能已移至獨立視窗，點擊下方按鈕即可開啟。',
              style='Muted.TLabel', wraplength=430).pack(
                  anchor='w', fill='x', pady=(0, 12))
    ttk.Button(launcher, text='開啟' + label + '視窗',
               command=lambda: app.open_feature(key)).pack(anchor='w')
    window = tk.Toplevel(app.root)
    window.withdraw()
    window.title('飄流Re:LaLa · ' + WINDOWS[key][0])
    center_on_main(window, app.root, *WINDOWS[key][1:])
    window.protocol('WM_DELETE_WINDOW', lambda: app.hide_feature(key))
    panel = panel_type(window, app)
    panel.pack(fill='both', expand=True)
    app.feature_windows[key] = window
    app.feature_launchers[key] = launcher
    return launcher, panel
