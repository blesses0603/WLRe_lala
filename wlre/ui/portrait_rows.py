"""Two window-owned portraits; providers read verified local data only.

Provider contract: request(state, kind, size) returns a mapping containing
image (Pillow image or None), revision (stable source/content key), and status.
No downloads, packet sends, or synthetic character artwork belong here.
"""
import tkinter as tk
from tkinter import ttk, font as tkfont
from collections.abc import Mapping
from PIL import Image, ImageDraw, ImageTk

SIZE = 40


def placeholder(size=SIZE):
    image = Image.new('RGBA', (size, size))
    ImageDraw.Draw(image).ellipse((2, 2, size-3, size-3), outline=(133, 169, 180, 160), width=1)
    return image


def row_identity(state, kind):
    player = state.get('player', {})
    if not player.get('role_id'):
        return None
    if kind == 'player':
        return (player.get('role_id'), player.get('sex'), player.get('head'),
                player.get('palette1'), player.get('palette5'))
    knowledge = state.get('knowledge', {})
    active = knowledge.get('active_npc_id')
    profile = next((p for p in knowledge.get('companions', {}).values()
                    if active is not None and p.get('npc_id') == active), None)
    if profile is None:
        return None
    return (player.get('role_id'), active, profile.get('modeling'),
            profile.get('stats', {}).get('modeling'))


class PortraitRows(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        self.photos = {}; self.keys = {}; self.texts = {}; self.images = {}
        self.closed = False
        for row, kind in enumerate(('player', 'companion')):
            icon = ttk.Label(self, anchor='center', padding=0)
            icon.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=1)
            label = ttk.Label(self, anchor='w', justify='left')
            label.grid(row=row, column=1, sticky='ew', pady=1)
            label.bind('<Configure>', lambda e, w=label: self._fit(w))
            self.images[kind] = icon; self.texts[kind] = label
        self.bind('<Destroy>', self._destroyed, add='+')

    def render_state(self, state, role_text, live, provider=None):
        if self.closed:
            return
        lines = role_text.splitlines()
        captions = {'player': '\n'.join(lines[:2]), 'companion': '\n'.join(lines[2:]).replace('｜HP ', '\nHP ', 1)}
        if not state.get('player', {}).get('role_id'):
            captions = {'player': '角色資料待同步', 'companion': '夥伴資料待同步'}
        for kind in ('player', 'companion'):
            identity = row_identity(state, kind)
            response = {}; failure = False
            if provider is not None and identity is not None:
                try:
                    response = provider.request(state, kind, SIZE) or {}
                except Exception:
                    # Optional image failure must not hide health or disconnect UI.
                    failure = True
            if not isinstance(response, Mapping):
                response = {}; failure = True
            image = response.get('image')
            valid = isinstance(image, Image.Image) and 0 < image.width <= 512 and 0 < image.height <= 512
            status = response.get('status') or ('頭像待同步' if not valid else '')
            if failure:
                status = '頭像待同步'
            absent = (kind == 'companion' and state.get('player', {}).get('role_id')
                      and not state.get('knowledge', {}).get('active_npc_id'))
            if absent:
                status = ''; valid = False
            key = (identity, response.get('revision'), valid, id(provider))
            if key != self.keys.get(kind):
                pixels = image.convert('RGBA').copy() if valid else placeholder()
                if valid:
                    pixels.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
                    tile = Image.new('RGBA', (SIZE, SIZE))
                    tile.alpha_composite(pixels, ((SIZE-pixels.width)//2, (SIZE-pixels.height)//2))
                    pixels = tile
                photo = ImageTk.PhotoImage(pixels, master=self)
                self.images[kind].configure(image=photo)
                self.photos[kind] = photo
                self.keys[kind] = key
            caption = '夥伴：未出戰' if absent else (captions[kind] or '夥伴資料待同步')
            self.images[kind].configure(text='待同步' if not valid and not absent else '',
                                        compound='center')
            self.images[kind].portrait_status = str(status)
            if not live and state.get('player', {}).get('role_id'):
                parts = caption.splitlines()
                parts[0] += '（最後同步）'
                caption = '\n'.join(parts)
            self.texts[kind].full_text = caption
            self._fit(self.texts[kind])

    def _fit(self, label):
        if self.closed:
            return
        font = tkfont.nametofont('TkDefaultFont', root=self)
        width = max(1, label.winfo_width()-2)
        fitted = []
        for line in getattr(label, 'full_text', '').splitlines()[:2]:
            if font.measure(line) > width:
                while line and font.measure(line+'…') > width:
                    line = line[:-1]
                line += '…'
            fitted.append(line)
        label.configure(text='\n'.join(fitted))

    def _destroyed(self, event):
        if event.widget is self:
            self.closed = True
            self.photos.clear(); self.keys.clear()
