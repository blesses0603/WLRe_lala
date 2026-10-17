"""EXP Monitor artwork and cyan glass styling, shared by every client window.

Widget backplates are cropped from one composited window image, so rounded
corners show the same background instead of a contrasting rectangular block.
No network, command queues, or game state are involved in this module.
"""
from wlre.paths import RESOURCE_ROOT
import copy
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from PIL import Image, ImageDraw, ImageOps, ImageTk

BG = '#101c2b'
PANEL = '#142638'
TEXT = '#eff7ff'
MUTED = '#a7cbdc'
CYAN = '#62c9e0'
ASSETS = RESOURCE_ROOT.joinpath('assets')


class GlassGroup(ttk.Frame):
    """A captioned frame without the native labelframe's opaque title strip."""
    def __init__(self, parent, text='', padding=10, **kwargs):
        if isinstance(padding, (int, float)):
            left = top = right = bottom = padding
        else:
            values = tuple(padding)
            left = values[0]
            top = values[1] if len(values) > 1 else left
            right = values[2] if len(values) > 2 else left
            bottom = values[3] if len(values) > 3 else top
        caption_height=tkfont.nametofont('TkDefaultFont',root=parent).metrics('linespace')
        super().__init__(parent, padding=(left, top+caption_height+8, right, bottom), **kwargs)
        self.caption = ttk.Label(self, text=text, style='Section.TLabel')
        self.caption.place(x=12, y=4, bordermode='outside')


def group(parent, **kwargs):
    if not hasattr(parent, 'tk'):
        return ttk.LabelFrame(parent, **kwargs)
    return GlassGroup(parent, **kwargs)


def install(root):
    """Install once per Tcl interpreter; also discover later popup windows."""
    if not hasattr(root, 'tk'):
        return None
    if getattr(root, '_exp_theme', None):
        return root._exp_theme
    theme = GlassTheme(root)
    root._exp_theme = theme
    return theme


class GlassTheme:
    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        self.windows = {}
        self.serial = 0
        self.art = Image.open(ASSETS / 'exp_background.png').convert('RGB')
        with Image.open(ASSETS / 'app.ico') as source:
            icon=source.convert('RGBA')
        self.icon=ImageTk.PhotoImage(icon,master=root)
        self.title_icon=ImageTk.PhotoImage(icon.resize((24,24),Image.Resampling.LANCZOS),master=root)
        families=set(tkfont.families(root))
        candidates=('Microsoft JhengHei UI','Noto Sans CJK TC','Noto Serif CJK TC','WenQuanYi Micro Hei')
        self.font=next((name for name in candidates if name in families),tkfont.nametofont('TkDefaultFont',root=root).actual('family'))
        root.tk.call('tk', 'scaling', 1.0)
        self.configure_styles()
        root.bind_all('<Map>', self.mapped, add='+')
        self.attach(root)

    def configure_styles(self):
        s = self.style
        s.theme_use('clam')
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont','TkSmallCaptionFont'):
            tkfont.nametofont(name,root=self.root).configure(family=self.font,size=-16)
        s.configure('.', font=(self.font, -16), background=PANEL, foreground=TEXT,
                    bordercolor='#397c98', lightcolor=PANEL, darkcolor=PANEL,
                    troughcolor=BG, selectbackground='#32617e', selectforeground=TEXT)
        s.configure('TFrame', background=PANEL)
        s.configure('TLabel', background=PANEL, foreground=TEXT)
        s.configure('Title.TLabel', font=(self.font, -24, 'bold'), foreground=TEXT)
        s.configure('Heading.TLabel', font=(self.font, -18, 'bold'), foreground='#c5f1ff')
        s.configure('Section.TLabel', font=(self.font, -16, 'bold'), foreground='#c5f1ff')
        s.configure('Muted.TLabel', foreground=MUTED, font=(self.font, -16))
        s.configure('TButton', padding=(9, 5), borderwidth=0, foreground=TEXT,
                    background='#233d52', focuscolor=CYAN)
        s.map('TButton', foreground=[('disabled', '#7292a4')],
              background=[('pressed', '#142638'), ('active', '#365770')])
        s.configure('TEntry', fieldbackground='#16364b', foreground=TEXT,
                    insertcolor=TEXT, bordercolor='#3b9db9', padding=4)
        s.configure('TSpinbox', fieldbackground='#16364b', foreground=TEXT,
                    insertcolor=TEXT, arrowsize=13, padding=3)
        s.configure('TCombobox', font=(self.font, -18), fieldbackground=PANEL, foreground=TEXT,
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
                    font=(self.font, -16, 'bold'))
        s.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(3, 3, 3, 4))
        s.configure('TNotebook.Tab', padding=(12, 6), background='#162f44', foreground=MUTED)
        s.map('TNotebook.Tab', background=[('selected', '#275972'), ('active', '#24465e')],
              foreground=[('selected', TEXT), ('active', TEXT)])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    borderwidth=0, rowheight=30, font=(self.font, -16))
        s.configure('Treeview.Heading', background='#243d52', foreground='#c5f1ff',
                    padding=6, font=(self.font, -16, 'bold'), relief='flat')
        s.map('Treeview', background=[('selected', '#32617e')], foreground=[('selected', TEXT)])
        s.map('Treeview.Heading', background=[('active', '#365770')])
        for name in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
            s.configure(name, background='#28526b', troughcolor=BG, borderwidth=0,
                        arrowcolor=CYAN, arrowsize=12, width=11)
            s.map(name, background=[('active', '#398aa7'), ('pressed', '#62c9e0')])
        s.configure('TPanedwindow', background=BG, sashwidth=6)
        for pattern, value in {
            '*Menu.font': (self.font, -16),
            '*TCombobox.font': (self.font, -18),
            '*TEntry.font': (self.font, -16),
            '*TSpinbox.font': (self.font, -16),
            '*TCombobox*Listbox.font': (self.font, -18),
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
            self.root.option_add(pattern, value)

    def mapped(self, event):
        widget = event.widget
        if isinstance(widget, (tk.Tk, tk.Toplevel)):
            self.attach(widget)
        try:
            top = widget.winfo_toplevel()
            if str(top) in self.windows:
                self.schedule(top)
        except (tk.TclError, AttributeError):
            pass

    def attach(self, window):
        key = str(window)
        if key in self.windows:
            return
        window.configure(background=BG)
        window.iconphoto(True,self.icon)
        if os.name=='nt':
            window.iconbitmap(str(ASSETS / 'app.ico'))
        self.windows[key] = {'job': None, 'signature': None, 'widgets': {}}
        self.add_chrome(window)
        window.bind('<Configure>', lambda event: self.configured(window,event), add='+')
        window.bind('<Destroy>', lambda event: self.destroyed(window, event), add='+')
        self.schedule(window)

    def add_chrome(self, window):
        """Keep the existing WM_DELETE_WINDOW behavior, including login handoff."""
        packed = [w for w in window.winfo_children() if w.winfo_manager() == 'pack']
        bar = ttk.Frame(window, height=44, padding=(12, 6))
        options = {'fill': 'x'}
        if packed:
            options['before'] = packed[0]
        bar.pack(**options)
        bar.pack_propagate(False)
        badge=ttk.Label(bar,image=self.title_icon)
        badge.pack(side='left',padx=(0,8))
        caption = ttk.Label(bar, text=window.title(), style='Heading.TLabel')
        caption.pack(side='left')
        def close():
            script = window.protocol('WM_DELETE_WINDOW')
            if script:
                window.tk.eval(script)
            else:
                window.destroy()
        ttk.Button(bar, text='×', width=3, command=close, takefocus=True).pack(side='right', padx=(6, 0))
        ttk.Button(bar, text='—', width=3, command=lambda: self.minimize(window)).pack(side='right')
        origin = []
        def start(event):
            origin[:] = [event.x_root, event.y_root, window.winfo_x(), window.winfo_y()]
        def drag(event):
            if origin:
                x, y, wx, wy = origin
                window.geometry(f'+{wx+event.x_root-x}+{wy+event.y_root-y}')
        for item in (bar, badge, caption):
            item.bind('<Button-1>', start)
            item.bind('<B1-Motion>', drag)
            item.bind('<ButtonRelease-1>', lambda event: origin.clear())
        window.overrideredirect(True)
        window.bind('<Map>', lambda event: self.restore(window, event), add='+')
        window._glass_chrome = bar
        window.after_idle(lambda: self.windows_chrome(window))

    def windows_chrome(self, window):
        if os.name != 'nt' or not window.winfo_exists():
            return
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        user.GetParent.argtypes = [wintypes.HWND]
        user.GetParent.restype = wintypes.HWND
        hwnd = user.GetParent(window.winfo_id()) or window.winfo_id()
        get = getattr(user, 'GetWindowLongPtrW', user.GetWindowLongW)
        put = getattr(user, 'SetWindowLongPtrW', user.SetWindowLongW)
        get.argtypes = [wintypes.HWND, ctypes.c_int]
        get.restype = ctypes.c_ssize_t
        put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        put.restype = ctypes.c_ssize_t
        # Login remains a transient tool window while the main page is visible.
        root_data = self.windows.get(str(self.root))
        root_visible = self.root.winfo_viewable() if root_data else False
        if window is self.root or not root_visible:
            put(hwnd, -20, (get(hwnd, -20) & ~0x80) | 0x40000)
            user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)
        window._glass_hwnd = hwnd
        rect = wintypes.RECT()
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetWindowRect(hwnd, ctypes.byref(rect))
        gdi = ctypes.windll.gdi32
        gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi.CreateRoundRectRgn.restype = wintypes.HRGN
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        region = gdi.CreateRoundRectRgn(0, 0, rect.right-rect.left+1, rect.bottom-rect.top+1, 32, 32)
        if region and not user.SetWindowRgn(hwnd, region, True):
            gdi.DeleteObject(region)

    def minimize(self, window):
        if os.name == 'nt' and getattr(window, '_glass_hwnd', None):
            import ctypes
            ctypes.windll.user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            ctypes.windll.user32.ShowWindow(window._glass_hwnd, 6)
        else:
            window._glass_restore = True
            window.overrideredirect(False)
            window.iconify()

    def restore(self, window, event):
        if event.widget is not window:
            return
        if getattr(window, '_glass_restore', False):
            window._glass_restore = False
            window.after_idle(lambda: window.overrideredirect(True))
        window.after_idle(lambda: self.windows_chrome(window))

    def destroyed(self, window, event):
        if event.widget is window:
            data = self.windows.pop(str(window), None)
            if data and data['job']:
                try:
                    self.root.after_cancel(data['job'])
                except tk.TclError:
                    pass

    def configured(self, window, event):
        data=self.windows.get(str(window))
        if not data:return
        # Window moves do not alter any window-relative background crop.
        geometry=(event.width,event.height) if event.widget is window else (event.x,event.y,event.width,event.height)
        key=str(event.widget)
        previous=data.setdefault('geometry',{}).get(key)
        if previous==geometry:return
        data['geometry'][key]=geometry
        self.schedule(window)

    def schedule(self, window):
        data = self.windows.get(str(window))
        if not data or data['job']:
            return
        data['job'] = self.root.after(25, lambda: self.paint(window))

    def descendants(self, window):
        for child in window.winfo_children():
            if isinstance(child, tk.Toplevel):
                continue
            yield child
            yield from self.descendants(child)

    def paint(self, window):
        data = self.windows.get(str(window))
        if not data:
            return
        data['job'] = None
        if not window.winfo_exists() or window.state() in ('iconic','withdrawn'):
            return
        width, height = window.winfo_width(), window.winfo_height()
        if width < 10 or height < 10:
            return
        children = [w for w in self.descendants(window) if w.winfo_ismapped()]
        wx, wy = window.winfo_rootx(), window.winfo_rooty()
        boxes = []
        for w in children:
            x, y = w.winfo_rootx()-wx, w.winfo_rooty()-wy
            a, b = w.winfo_width(), w.winfo_height()
            bounds = [max(0, x), max(0, y), min(width, x+a), min(height, y+b)]
            ancestor = w.master
            while ancestor is not window:
                ax, ay = ancestor.winfo_rootx()-wx, ancestor.winfo_rooty()-wy
                bounds = [max(bounds[0], ax), max(bounds[1], ay),
                          min(bounds[2], ax+ancestor.winfo_width()),
                          min(bounds[3], ay+ancestor.winfo_height())]
                ancestor = ancestor.master
            if bounds[0] < bounds[2] and bounds[1] < bounds[3]:
                boxes.append((w, x, y, a, b))
        signature = (width, height, tuple((str(w), x, y, a, b) for w, x, y, a, b in boxes))
        if signature == data['signature']:
            return
        data['signature'] = signature
        # One image transform per window size. Every transparent control takes
        # the same absolute crop; nested panels never recolor/rescale the picture.
        if data.get('background_size') != (width,height):
            background = ImageOps.fit(self.art,(width,height),method=Image.Resampling.LANCZOS)
            background = Image.blend(background,Image.new('RGB',background.size,'#071526'),.46)
            backing=background.convert('RGBA')
            layer=Image.new('RGBA',backing.size)
            ImageDraw.Draw(layer).rounded_rectangle((1,1,width-2,height-2),radius=20,
                outline=(98,201,224,200),width=1)
            data['background']=Image.alpha_composite(backing,layer)
            data['background_size'] = (width,height)
        backing = data['background']
        new_styles = False
        for w, x, y, a, b in boxes:
            if a < 2 or b < 2:
                continue
            cls = w.winfo_class()
            if cls in ('TFrame', 'TLabel', 'TLabelframe', 'TButton', 'TCheckbutton', 'TRadiobutton'):
                if cls == 'TLabelframe' and not hasattr(w, '_glass_label') and w.cget('text'):
                    w._glass_label = ttk.Label(w, text=w.cget('text'), style='Section.TLabel')
                    w.configure(labelwidget=w._glass_label)
                crop_key=(width,height,x,y,a,b)
                record=data['widgets'].get(str(w))
                if record is None or record.get('crop_key')!=crop_key:
                    new_styles = self.skin(w, data, backing.crop((x, y, x+a, y+b)), cls) or new_styles
                    record=data['widgets'].get(str(w))
                    if record is not None:record['crop_key']=crop_key
            elif cls == 'Canvas' and hasattr(w, 'set_glass_background'):
                w.set_glass_background(backing.crop((x, y, x+a, y+b)))
            elif cls == 'Text':
                w.configure(background=PANEL, foreground=TEXT, insertbackground=TEXT,
                            selectbackground='#32617e', relief='flat', borderwidth=0)
            elif cls == 'Listbox':
                w.configure(background=PANEL, foreground=TEXT, selectbackground='#32617e',
                            selectforeground=TEXT, relief='flat', borderwidth=0, highlightthickness=0)
        # Old tab content is released when its widgets are destroyed.
        for key, record in list(data['widgets'].items()):
            if not record['widget'].winfo_exists():
                data['widgets'].pop(key)
                data.get('geometry',{}).pop(key,None)
        if new_styles:
            # Assigning a new ttk layout can settle its internal padding after
            # this pass even when outer widget geometry does not change.
            data['signature'] = None
            self.schedule(window)

    def skin(self, widget, data, crop, cls):
        # Widgets briefly shrink during page switches; inset borders need room.
        if crop.width < 3 or crop.height < (7 if cls == 'TLabelframe' else 3):return False
        key = str(widget)
        record = data['widgets'].get(key)
        if record is None:
            self.serial += 1
            original = widget.cget('style') or cls
            style_name = f'Glass{self.serial}.{original}'
            element = f'Glass{self.serial}.plate'
            layout = copy.deepcopy(self.style.layout(original))
            if not layout:
                return
            record = {'widget': widget, 'images': [], 'style': style_name, 'element': element}
            data['widgets'][key] = record
            record['layout'] = [(element, {'sticky': 'nswe'}), *layout[0][1].get('children', [])]
            if cls in ('TCheckbutton', 'TRadiobutton'):
                record['layout'] = [(element, {'sticky': 'nswe'}), *layout]
            record['original'] = original
        images = []
        states = ('normal', 'active', 'pressed', 'disabled') if cls == 'TButton' else ('normal',)
        for state in states:
            surface = crop.copy()
            if cls == 'TLabelframe' or type(widget).__name__ in ('HomeMap', 'GlassGroup'):
                overlay = Image.new('RGBA', crop.size)
                d = ImageDraw.Draw(overlay)
                d.rounded_rectangle((1, 5 if cls == 'TLabelframe' else 1,
                                     crop.width-2, crop.height-2), radius=14,
                                    outline=(98, 201, 224, 150))
                surface = Image.alpha_composite(surface, overlay)
            if cls == 'TButton':
                overlay = Image.new('RGBA', crop.size)
                d = ImageDraw.Draw(overlay)
                fill = {'normal': (12, 40, 63, 205), 'active': (38, 88, 114, 235),
                        'pressed': (9, 27, 47, 240), 'disabled': (13, 30, 44, 195)}[state]
                d.rounded_rectangle((1, 1, crop.width-2, crop.height-2), radius=crop.height//2 if record['original']=='Pill.Tab.TButton' else 9,
                                    fill=fill, outline=(98, 201, 224, 120 if state=='disabled' else 220))
                surface = Image.alpha_composite(surface, overlay)
            images.append(surface)
        first = not record['images']
        if first:
            photos = [ImageTk.PhotoImage(value, master=self.root) for value in images]
            spec = [photos[0]]
            if cls == 'TButton':
                spec += [('disabled', photos[3]), ('pressed', photos[2]), ('selected', photos[1]), ('active', photos[1])]
            self.style.element_create(record['element'], 'image', *spec, sticky='nswe', width=0, height=0)
            self.style.layout(record['style'], record['layout'])
            widget.configure(style=record['style'])
            record['images'] = photos
        else:
            # Updating existing image objects avoids accumulating Tcl elements.
            for old, new in zip(record['images'], images):
                # Keep the Tcl image referenced by the ttk element while resizing.
                old.tk.call(str(old),'configure','-width',crop.width,'-height',crop.height)
                old.paste(new)
        if cls == 'TButton' and hasattr(widget, 'halo_owner'):
            widget.halo_owner.set_button_surfaces(images,record['images'])
        widget.event_generate('<Expose>')
        return first
