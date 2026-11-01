"""Cached crafting item icons; shared by inventory and recovery views.

API remains exposed from wlre.ui.crafting_browser for existing callers.
"""
from wlre.paths import RESOURCE_ROOT
from wlre.ui.crafting.icon_cache import DECODED_SPRITES
import io
from wlre.storage.bundled_database import load_bundled_json, load_bundled_bytes
import json
import zipfile
from collections import OrderedDict
import tkinter as tk
from PIL import ImageTk

BASE = RESOURCE_ROOT
ICON_MAP = load_bundled_json('item_icon_map.json', root=BASE)['items']


class ItemIcons:
    def __init__(self,master):self.master=master;self.archive=zipfile.ZipFile(io.BytesIO(load_bundled_bytes('item_icons.zip', root=BASE)));self.cache=OrderedDict()
    def get(self,item_id,size=64):
        name=ICON_MAP.get(str(item_id),{}).get('icon','s1000')+'.png'
        if name not in self.archive.NameToInfo:name='s1000.png'
        # Different item IDs may share an original sprite or the native fallback.
        key=name,size
        if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        try:
            # Cache Pillow pixels across windows; keep Tk images window-local.
            canvas=DECODED_SPRITES.get(self.archive,name,size)
            image=ImageTk.PhotoImage(canvas,master=self.master)
        except (KeyError,OSError):image=tk.PhotoImage(master=self.master,width=size,height=size)
        self.cache[key]=image
        while len(self.cache)>128:self.cache.popitem(last=False)
        return image

    def close(self):self.archive.close();self.cache.clear()
