"""Original EmojiData row-index mapping; static game sprites, safe literal fallback."""
import re,io
from PIL import Image,ImageTk
TOKEN=re.compile(r'\[Emoji([0-9]+)\]')

def segments(text):
    offset=0
    for m in TOKEN.finditer(text):
        if m.start()>offset:yield ('text',text[offset:m.start()])
        yield ('emoji',m.group(0));offset=m.end()
    if offset<len(text):yield ('text',text[offset:])

class EmojiImages:
    def __init__(self,master):
        self.master=master;self.cache={};self.token=None
    def refresh_source(self):
        from wlre.services.world.emoji_database import source_token
        token=source_token()
        if token==self.token:return False
        self.token=token;self.cache.clear();return True
    @property
    def catalog(self):
        from wlre.services.world.emoji_database import current_entries
        self.refresh_source();return current_entries()
    def get(self,token,size=24):
        from wlre.services.world.emoji_database import current_png
        self.refresh_source()
        m=TOKEN.fullmatch(token)
        if not m:return None
        index=str(int(m.group(1)));key=index,size
        try:
            raw=current_png(index)
            if raw is None:return None
            if key in self.cache:return self.cache[key]
            with Image.open(io.BytesIO(raw)) as src:
                im=src.convert('RGBA');im.thumbnail((size,size),Image.Resampling.LANCZOS)
            result=ImageTk.PhotoImage(im,master=self.master);self.cache[key]=result;return result
        except (OSError,KeyError,ValueError,TypeError):return None
    def close(self):
        self.cache.clear();self.token=None
