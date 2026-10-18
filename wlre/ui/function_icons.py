"""Original game pictograms with compact circular navigation backplates."""
from functools import lru_cache
from PIL import Image, ImageDraw, ImageOps, ImageTk
from wlre.paths import RESOURCE_ROOT

ICONS={'主頁':'MainIcon_041', '組隊':'MainIcon_005', '夥伴出戰':'MainIcon_010',
       '遠征':'MainIcon_038', '煉金':'MainIcon_007', '製作':'MainIcon_011',
       '經驗效率':'MainIcon_020', '自動戰鬥':'Btn_AI', '包包':'MainIcon_001'}


@lru_cache(maxsize=16)
def icon_image(name, size=34):
    scale=3
    image=Image.new('RGBA',(size*scale,size*scale))
    draw=ImageDraw.Draw(image)
    draw.ellipse((2,2,size*scale-3,size*scale-3),fill=(45,81,101,230),
                 outline=(180,225,235,235),width=scale)
    with Image.open(RESOURCE_ROOT/'assets'/'function-icons'/(name+'.png')) as source:
        glyph=ImageOps.contain(source.convert('RGBA'),(size*scale-20,size*scale-20),Image.Resampling.LANCZOS)
    image.alpha_composite(glyph,((image.width-glyph.width)//2,(image.height-glyph.height)//2))
    return image.resize((size,size),Image.Resampling.LANCZOS)


def icon_photo(widget, title, size=34):
    name=ICONS.get(title)
    return ImageTk.PhotoImage(icon_image(name,size),master=widget) if name else None
