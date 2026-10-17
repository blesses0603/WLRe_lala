"""Original EmojiData row-index mapping; static game sprites, safe literal fallback."""
from wlre.paths import RESOURCE_ROOT
import re,json,zipfile,io
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
        self.master=master;self.cache={};base=RESOURCE_ROOT
        try:
            self.catalog=json.loads((base/'emoji_catalog.json').read_text(encoding='utf-8'))['entries'];self.archive=zipfile.ZipFile(base/'emoji_images.zip')
        except (OSError,ValueError,KeyError,zipfile.BadZipFile):self.catalog={};self.archive=None
    def get(self,token,size=24):
        m=TOKEN.fullmatch(token)
        if not m:return None
        index=str(int(m.group(1)));key=index,size
        if key in self.cache:return self.cache[key]
        row=self.catalog.get(index)
        if not row or not row.get('available',True) or not self.archive:return None
        try:
            with Image.open(io.BytesIO(self.archive.read(row['sprite']+'.png'))) as src:
                im=src.convert('RGBA');im.thumbnail((size,size),Image.Resampling.LANCZOS)
            result=ImageTk.PhotoImage(im,master=self.master);self.cache[key]=result;return result
        except (OSError,KeyError,ValueError,zipfile.BadZipFile):return None
    def close(self):
        if self.archive:self.archive.close();self.archive=None
