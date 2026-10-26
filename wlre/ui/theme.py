"""EXP Monitor artwork and cyan glass styling, shared by every client window.

Widget backplates are cropped from one composited window image, so rounded
corners show the same background instead of a contrasting rectangular block.
No network, command queues, or game state are involved in this module.
"""
from wlre.paths import RESOURCE_ROOT
from wlre.ui.button_art import button_image, button_kind
from wlre.ui.theme_styles import apply_styles
from wlre.ui.theme_surfaces import (artwork_canvas, window_background, visible_bounds,
                                    widget_crop, draw_section, section_layers)
import copy
import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

BG = '#101c2b'
PANEL = '#142638'
TEXT = '#eff7ff'
MUTED = '#a7cbdc'
CYAN = '#62c9e0'
ASSETS = RESOURCE_ROOT.joinpath('assets')


def native_titlebar(window):
    """Aqua 的 borderless 會關閉 resizable，原生視窗須保留 WM 裝飾。"""
    try:
        return window.tk.call('tk', 'windowingsystem') == 'aqua'
    except AttributeError:
        return False


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
        caption_height=tkfont.nametofont('TkDefaultFont',root=parent).metrics('linespace')+8 if text else 0
        super().__init__(parent, padding=(left, top+caption_height, right, bottom), **kwargs)
        self.caption = None
        if text:
            self.caption = ttk.Label(self, text=text, style='Section.TLabel')
            self.caption.place(x=12, y=4, bordermode='outside')


def group(parent, **kwargs):
    if not hasattr(parent, 'tk'):
        return ttk.LabelFrame(parent, **kwargs)
    return GlassGroup(parent, **kwargs)


def install(root):
    from wlre.ui.resource_lifetime import install_root_lifetime
    install_root_lifetime(root)
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
        self.wallpaper = artwork_canvas(self.art)
        with Image.open(ASSETS / 'app.ico') as source:
            icon=source.convert('RGBA')
        self.icon=ImageTk.PhotoImage(icon,master=root)
        self.title_icon=ImageTk.PhotoImage(icon.resize((24,24),Image.Resampling.LANCZOS),master=root)
        families=set(tkfont.families(root))
        candidates=('Microsoft JhengHei UI','Noto Sans CJK TC','Noto Serif CJK TC','WenQuanYi Micro Hei')
        self.font=next((name for name in candidates if name in families),tkfont.nametofont('TkDefaultFont',root=root).actual('family'))
        root.tk.call('tk', 'scaling', 1.0)
        self.configure_styles()
        for sequence in ('<Button-1>', '<Double-Button-1>', '<Motion>'):
            root.bind_class('LockedTableColumns', sequence, self.lock_table_separator)
        root.bind_all('<Map>', self.mapped, add='+')
        self.attach(root)

    def configure_styles(self):
        """Install the shared ttk style declarations (painting remains here)."""
        apply_styles(self.style, self.root, self.font,
                     bg=BG, panel=PANEL, ink=TEXT, muted=MUTED, cyan=CYAN)

    @staticmethod
    def lock_table_separator(event):
        if event.widget.identify_region(event.x, event.y) == 'separator':
            return 'break'

    def mapped(self, event):
        widget = event.widget
        if isinstance(widget, ttk.Treeview) and 'LockedTableColumns' not in widget.bindtags():
            widget.bindtags(('LockedTableColumns',) + widget.bindtags())
        if isinstance(widget, tk.Tk) or (
                isinstance(widget, tk.Toplevel) and widget.winfo_viewable()):
            # Avoid painting withdrawn feature windows before the user opens them.
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
        # Some Tk/Tcl callback paths invoke a registered binding without a
        # positional event object. Ignore those synthetic invocations, while
        # preserving normal <Configure>/<Destroy> lifecycle handling.
        window.bind('<Configure>', lambda event=None: self.configured(window,event)
                    if event is not None else None, add='+')
        window.bind('<Destroy>', lambda event=None: self.destroyed(window,event)
                    if event is not None else None, add='+')
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
        close_button=ttk.Button(bar, text='', width=3, command=close, takefocus=True)
        close_button._game_button_kind='Btn_Close04'
        close_button.pack(side='right', padx=(6, 0))
        minimize_button=ttk.Button(bar, text='', width=3, command=lambda: self.minimize(window))
        minimize_button._game_button_kind='Btn_Minimize'
        minimize_button.pack(side='right')
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
            item.bind('<ButtonRelease-1>', lambda event=None: origin.clear())
        if not native_titlebar(window):
            window.overrideredirect(True)
        window.bind('<Map>', lambda event=None: self.restore(window, event)
                    if event is not None else None, add='+')
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
        # Keep window-message dispatch inside _tkinter. Calling synchronous
        # user32.ShowWindow through ctypes here releases the GIL and can reenter
        # Tk's window procedure without its saved Python thread state (3.14).
        if not window.winfo_exists() or window.state() in ('iconic', 'withdrawn'):
            return
        window._glass_restore = not native_titlebar(window)
        if window._glass_restore:
            window.overrideredirect(False)
        window.iconify()

    def restore(self, window, event):
        if event.widget is not window:
            return
        window.after_idle(lambda: self.finish_restore(window))

    def finish_restore(self, window):
        # A Map event can already be queued when iconify runs. Only restore
        # chrome once the window is actually visible again; tolerate closure
        # before this idle callback executes.
        if not window.winfo_exists() or window.state() in ('iconic', 'withdrawn'):
            return
        if getattr(window, '_glass_restore', False):
            window._glass_restore = False
            if not native_titlebar(window):
                window.overrideredirect(True)
        self.windows_chrome(window)

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
            parents = []
            ancestor = w.master
            while ancestor is not window:
                parents.append((ancestor.winfo_rootx()-wx, ancestor.winfo_rooty()-wy,
                                ancestor.winfo_width(), ancestor.winfo_height()))
                ancestor = ancestor.master
            bounds = visible_bounds(x, y, a, b, (width, height), parents)
            if bounds is not None:
                boxes.append((w, x, y, a, b, bounds))
        # A border policy change must repaint even if widget geometry is static.
        outline = not getattr(window, '_no_glass_border', False)
        sections = section_layers(boxes)
        signature = (width, height, outline, sections,
                     tuple((str(w), x, y, a, b, bounds) for w, x, y, a, b, bounds in boxes))
        if signature == data['signature']:
            return
        data['signature'] = signature
        # One image transform per window size. Every transparent control takes
        # the same absolute crop; nested panels never recolor/rescale the picture.
        # A dedicated version dialog uses a stronger wallpaper tint for
        # legibility; all other LaLa windows retain their original darkness.
        dim_amount = getattr(window, '_glass_background_dim', None)
        background_key = (width, height, outline, dim_amount)
        if data.get('background_key') != background_key:
            data['background'] = window_background(
                self.wallpaper, width, height, main=window is self.root,
                outline=outline, dim_amount=dim_amount)
            data['background_key'] = background_key
            data['background_size'] = (width, height)
        surface_key = (background_key, sections)
        if data.get('surface_key')!=surface_key:
            backing=data['background'].copy()
            layer=Image.new('RGBA',backing.size)
            for x,y,a,b,bounds,fill in sections:
                draw_section(layer, x, y, a, b, bounds, fill)
            data['surface']=Image.alpha_composite(backing,layer)
            data['surface_key']=surface_key
            data['surface_generation']=data.get('surface_generation',0)+1
        backing = data['surface']
        new_styles = False
        for w, x, y, a, b, bounds in boxes:
            if a < 2 or b < 2:
                continue
            cls = w.winfo_class()
            if cls in ('TFrame', 'TLabel', 'TLabelframe', 'TButton', 'TCheckbutton', 'TRadiobutton'):
                if cls == 'TLabelframe' and not hasattr(w, '_glass_label') and w.cget('text'):
                    w._glass_label = ttk.Label(w, text=w.cget('text'), style='Section.TLabel')
                    w.configure(labelwidget=w._glass_label)
                # Include ancestor clipping even when widget geometry stays fixed.
                crop_key=(data['surface_generation'],width,height,x,y,a,b,bounds)
                record=data['widgets'].get(str(w))
                if record is None or record.get('crop_key')!=crop_key:
                    new_styles = self.skin(w, data, widget_crop(backing, x, y, a, b, bounds), cls) or new_styles
                    record=data['widgets'].get(str(w))
                    if record is not None:record['crop_key']=crop_key
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
            if cls == 'TLabelframe' or type(widget).__name__ in ('HomeMap', 'GlassGroup') or getattr(widget, '_section_outline', False):
                overlay = Image.new('RGBA', crop.size)
                ImageDraw.Draw(overlay).rounded_rectangle(
                    (1, 5 if cls == 'TLabelframe' else 1, crop.width-2, crop.height-2),
                    radius=14, outline=(98, 201, 224, 150))
                surface = Image.alpha_composite(surface, overlay)
            if cls == 'TButton':
                if record['original']=='Icon.Tab.TButton':
                    overlay=Image.new('RGBA',crop.size)
                    draw=ImageDraw.Draw(overlay)
                    if state in ('active','pressed'):
                        draw.rounded_rectangle((1,1,crop.width-2,crop.height-2),radius=10,
                            fill=(38,88,114,130 if state=='active' else 210),outline=(98,201,224,200))
                    surface=Image.alpha_composite(surface,overlay)
                elif hasattr(widget, 'halo_owner') or record['original']=='Pill.Tab.TButton':
                    overlay = Image.new('RGBA', crop.size)
                    d = ImageDraw.Draw(overlay)
                    fill = {'normal': (12, 40, 63, 205), 'active': (38, 88, 114, 235),
                            'pressed': (9, 27, 47, 240), 'disabled': (13, 30, 44, 195)}[state]
                    d.rounded_rectangle((1, 1, crop.width-2, crop.height-2), radius=crop.height//2 if record['original']=='Pill.Tab.TButton' else 9,
                                        fill=fill, outline=(98, 201, 224, 120 if state=='disabled' else 220))
                    surface = Image.alpha_composite(surface, overlay)
                else:
                    kind=button_kind(widget)
                    if state=='disabled' and kind not in ('Btn_Close04','Btn_Minimize'):kind='Btn_016'
                    surface=Image.alpha_composite(surface,button_image(kind,crop.width,crop.height,state))
            images.append(surface)
        first = not record['images']
        if first:
            photos = [ImageTk.PhotoImage(value, master=self.root) for value in images]
            spec = [photos[0]]
            if cls == 'TButton':
                spec += [('disabled', photos[3]), ('pressed', photos[2]), ('selected', photos[1]), ('active', photos[1])]
            self.style.element_create(record['element'], 'image', *spec, sticky='nswe', width=0, height=0)
            self.style.layout(record['style'], record['layout'])
            if cls=='TButton' and not hasattr(widget,'halo_owner') and record['original'] not in ('Pill.Tab.TButton','Icon.Tab.TButton'):
                self.style.configure(record['style'],foreground='#10283d')
                self.style.map(record['style'],foreground=[('disabled','#46515e')])
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
