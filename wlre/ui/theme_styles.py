"""ttk style registrations for LaLa's shared glass palette.

This module defines widget styles and Tk option database values only.
Window background alignment, drawing, and native chrome stay in theme.py.
"""
from tkinter import font as tkfont


def apply_styles(style, root, font, *, bg, panel, ink, muted, cyan):
    # Preserve the original palette's names inside the unchanged registrations.
    BG, PANEL, TEXT, MUTED, CYAN = bg, panel, ink, muted, cyan
    s = style
    s.theme_use('clam')
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont','TkSmallCaptionFont'):
        tkfont.nametofont(name,root=root).configure(family=font,size=-14)
    s.configure('.', font=(font, -14), background=PANEL, foreground=TEXT,
                bordercolor='#397c98', lightcolor=PANEL, darkcolor=PANEL,
                troughcolor=BG, selectbackground='#32617e', selectforeground=TEXT)
    s.configure('TFrame', background=PANEL)
    s.configure('TLabel', background=PANEL, foreground=TEXT)
    s.configure('Title.TLabel', font=(font, -22, 'bold'), foreground=TEXT)
    s.configure('Heading.TLabel', font=(font, -16, 'bold'), foreground='#c5f1ff')
    s.configure('Section.TLabel', font=(font, -14, 'bold'), foreground='#c5f1ff')
    # Dedicated typography for the pre-login official-version result card.
    # This affects neither the dashboard nor other dialog headings.
    s.configure('VersionAlertHeading.TLabel', font=(font, -20, 'bold'),
                foreground='#ffe2b0')
    s.configure('VersionAlertMessage.TLabel', font=(font, -16),
                foreground='#eff7ff')
    s.configure('Muted.TLabel', foreground=MUTED, font=(font, -14))
    s.configure('TButton', padding=(7, 4), borderwidth=0, focusthickness=0, foreground=TEXT,
                background='#233d52', focuscolor=CYAN)
    s.map('TButton', foreground=[('disabled', '#7292a4')],
          background=[('pressed', '#142638'), ('active', '#365770')])
    s.configure('TEntry', fieldbackground='#16364b', foreground=TEXT,
                insertcolor=TEXT, bordercolor='#3b9db9', padding=4)
    s.configure('TSpinbox', fieldbackground='#16364b', foreground=TEXT,
                insertcolor=TEXT, arrowsize=13, padding=3)
    s.configure('TCombobox', font=(font, -16), fieldbackground=PANEL, foreground=TEXT,
                background='#233d52', arrowcolor=CYAN, padding=4)
    s.map('TCombobox', fieldbackground=[('readonly', PANEL), ('disabled', BG)],
          foreground=[('disabled', '#7292a4'), ('readonly', TEXT)],
          selectbackground=[('readonly', '#32617e')], selectforeground=[('readonly', TEXT)])
    for name in ('TCheckbutton', 'TRadiobutton'):
        s.configure(name, background=PANEL, foreground=TEXT, padding=(2, 3),
                    indicatorbackground='#16364b', indicatorforeground=CYAN)
        s.map(name, background=[('active', '#233d52')],
              foreground=[('disabled', '#7292a4')],
              indicatorbackground=[('selected', '#398aab'), ('disabled', '#203446')])
    s.configure('TLabelframe', background=PANEL, borderwidth=1, relief='flat')
    s.configure('TLabelframe.Label', background=PANEL, foreground='#c5f1ff',
                font=(font, -14, 'bold'))
    s.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(3, 3, 3, 4))
    s.configure('TNotebook.Tab', padding=(12, 6), background='#162f44', foreground=MUTED)
    s.map('TNotebook.Tab', background=[('selected', '#275972'), ('active', '#24465e')],
          foreground=[('selected', TEXT), ('active', TEXT)])
    s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                borderwidth=0, rowheight=26, font=(font, -14))
    s.configure('Treeview.Heading', background='#243d52', foreground='#c5f1ff',
                padding=(2, 0), font=(font, -14, 'bold'), relief='flat')
    s.map('Treeview', background=[('selected', '#32617e')], foreground=[('selected', TEXT)])
    s.map('Treeview.Heading', background=[('active', '#365770')])
    for name in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        s.configure(name, background='#28526b', troughcolor=BG, borderwidth=0,
                    arrowcolor=CYAN, arrowsize=12, width=11)
        s.map(name, background=[('active', '#398aa7'), ('pressed', '#62c9e0')])
    s.configure('TPanedwindow', background=BG, sashwidth=6)
    for pattern, value in {
        '*Menu.font': (font, -14),
        '*TCombobox.font': (font, -16),
        '*TEntry.font': (font, -14),
        '*TSpinbox.font': (font, -14),
        '*TCombobox*Listbox.font': (font, -16),
        '*TCombobox*Listbox.background': PANEL,
        '*TCombobox*Listbox.foreground': TEXT,
        '*TCombobox*Listbox.selectBackground': '#32617e',
        '*TCombobox*Listbox.selectForeground': TEXT,
        '*Text.background': PANEL, '*Text.foreground': TEXT,
        '*Text.insertBackground': TEXT, '*Text.selectBackground': '#32617e',
        '*Listbox.background': PANEL, '*Listbox.foreground': TEXT,
        '*Listbox.selectBackground': '#32617e', '*Listbox.selectForeground': TEXT,
        '*Canvas.background': BG,
    }.items():
        root.option_add(pattern, value)

