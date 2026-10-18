"""Original game button sprites, resized using their Unity slice borders."""
from functools import lru_cache
from PIL import Image, ImageEnhance, ImageOps
from wlre.paths import RESOURCE_ROOT


@lru_cache(maxsize=4)
def source(name):
    with Image.open(RESOURCE_ROOT / 'assets' / 'buttons' / (name + '.png')) as image:
        return image.convert('RGBA')


@lru_cache(maxsize=256)
def button_image(name, width, height, state='normal'):
    image = source(name)
    if name == 'Btn_Close04':
        result = Image.new('RGBA', (width, height))
        icon = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
        result.alpha_composite(icon, ((width-icon.width)//2, (height-icon.height)//2))
    else:
        # Unity borders: left=34, right=37; top/bottom=0. Scale ends with
        # height, stretch only the center so narrow desktop buttons stay crisp.
        scale = min(height / image.height, width / 71)
        left, right = max(1, round(34*scale)), max(1, round(37*scale))
        if left+right > width:
            left = width//2; right = width-left
        result = Image.new('RGBA', (width, height))
        slices = ((0,34,0,left), (34,image.width-37,left,width-right),
                  (image.width-37,image.width,width-right,width))
        for x1,x2,d1,d2 in slices:
            if d2>d1:
                part=image.crop((x1,0,x2,image.height)).resize((d2-d1,height),Image.Resampling.LANCZOS)
                result.alpha_composite(part,(d1,0))
    if state in ('active','pressed'):
        alpha=result.getchannel('A')
        result=ImageEnhance.Brightness(result).enhance(1.15 if state=='active' else .78)
        result.putalpha(alpha)
    elif state=='disabled':
        alpha=result.getchannel('A').point(lambda value:round(value*.75))
        result=ImageOps.grayscale(result).convert('RGBA');result.putalpha(alpha)
    return result


def button_kind(widget):
    explicit=getattr(widget,'_game_button_kind',None)
    if explicit:return explicit
    text=str(widget.cget('text')).strip()
    if text.startswith(('停止','中斷','取消')):return 'Btn_016'
    if text.startswith(('啟動','開始','確認','登入','送出')):return 'Btn_014'
    return 'Btn_004'
