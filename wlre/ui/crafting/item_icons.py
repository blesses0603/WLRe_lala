"""Window-local Tk images backed by verified official SQLite snapshots."""
from collections import OrderedDict
from collections.abc import Mapping
from PIL import Image, ImageTk
from wlre.services.world.item_image_database import current_catalog, source_token
from wlre.ui.crafting.icon_cache import DECODED_SPRITES


class LiveIconMap(Mapping):
    def __getitem__(self,key):
        catalog=current_catalog()
        if catalog is None or int(key) not in catalog.mapping:raise KeyError(key)
        return dict((catalog.metadata or {}).get(int(key),{}),icon='s%04d'%catalog.mapping[int(key)])
    def __iter__(self):
        catalog=current_catalog()
        return iter(tuple(str(k) for k in catalog.mapping) if catalog else ())
    def __len__(self):
        catalog=current_catalog()
        return len(catalog.mapping) if catalog else 0


ICON_MAP=LiveIconMap()


class DatabaseArchive:
    def __init__(self,catalog):
        self.catalog=catalog
        self.filename=(str(catalog.images.database),catalog.catalog_key,id(catalog))
    def read(self,name):
        raw=self.catalog.images.png(int(name[1:-4]))
        if raw is None:raise KeyError(name)
        return raw


class ItemIcons:
    def __init__(self,master):
        self.master=master;self.cache=OrderedDict();self.source=source_token();self.timer=None
        self.closed=False
        if hasattr(master,'after'):
            self.timer=master.after(1000,self.refresh_source)
            master.bind('<Destroy>',lambda event:self.close() if event.widget is master else None,add='+')

    def _pixels(self,item_id,size):
        catalog=current_catalog()
        if catalog is not None:
            try:
                return DECODED_SPRITES.get(DatabaseArchive(catalog),'s%04d.png'%catalog.icon(item_id),size)
            except (KeyError,OSError,ValueError):pass
        return Image.new('RGBA',(size,size))

    def refresh_source(self):
        if self.closed:return
        token=source_token()
        if token!=self.source:
            self.source=token
            for (item_id,size),photo in self.cache.items():photo.paste(self._pixels(item_id,size))
        if hasattr(self.master,'after'):self.timer=self.master.after(1000,self.refresh_source)

    def get(self,item_id,size=64):
        token=source_token()
        if token!=self.source:
            self.source=token
            for (ident,pixels),photo in self.cache.items():photo.paste(self._pixels(ident,pixels))
        key=item_id,size
        if key not in self.cache:self.cache[key]=ImageTk.PhotoImage(self._pixels(item_id,size),master=self.master)
        self.cache.move_to_end(key)
        while len(self.cache)>128:self.cache.popitem(last=False)
        return self.cache[key]

    def close(self):
        self.closed=True
        if self.timer is not None:
            try:self.master.after_cancel(self.timer)
            except Exception:pass
        self.cache.clear()
