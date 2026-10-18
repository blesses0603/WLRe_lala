"""Original game button sprites, resized using their Unity slice borders."""
from functools import lru_cache
from tkinter import ttk
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageTk
from wlre.paths import RESOURCE_ROOT


@lru_cache(maxsize=8)
def source(name):
    if name in ('Btn_Minimize','Btn_Close04'):
        # Both window controls use the exact same frame and glow geometry.
        image=Image.new('RGBA',(198,198))
        glow=Image.new('RGBA',image.size)
        draw=ImageDraw.Draw(glow)
        draw.ellipse((27,27,170,170),outline=(55,244,239,230),width=15)
        image=Image.alpha_composite(image,glow.filter(ImageFilter.GaussianBlur(12)))
        draw=ImageDraw.Draw(image)
        draw.ellipse((28,28,169,169),fill=(25,92,101,230),outline=(169,255,250,255),width=8)
        if name=='Btn_Minimize':
            draw.rounded_rectangle((61,91,137,106),radius=5,fill=(230,255,255,255))
        else:
            draw.line((72,72,126,126),fill=(230,255,255,255),width=13)
            draw.line((72,126,126,72),fill=(230,255,255,255),width=13)
        return image.resize((66,66),Image.Resampling.LANCZOS)
    with Image.open(RESOURCE_ROOT / 'assets' / 'buttons' / (name + '.png')) as image:
        return image.convert('RGBA')


@lru_cache(maxsize=256)
def button_image(name, width, height, state='normal'):
    image = source(name)
    if name in ('Btn_Close04','Btn_Minimize'):
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


def settings_button(parent, command, text='設定'):
    photo=ImageTk.PhotoImage(source('Btn_Setting').resize((20,20),Image.Resampling.LANCZOS),master=parent)
    button=ttk.Button(parent,text=text,image=photo,compound='none',width=0,
                      style='Icon.Tab.TButton',padding=(2,1),command=command)
    button._settings_icon=photo
    return button


def bag_button(parent, command):
    image=ImageOps.contain(source('Btn_Bag'),(24,24),Image.Resampling.LANCZOS)
    photo=ImageTk.PhotoImage(image,master=parent)
    button=ttk.Button(parent,text='包包',image=photo,compound='none',width=0,
                      style='Icon.Tab.TButton',padding=(2,1),command=command)
    button._bag_icon=photo
    return button


def recovery_button(parent, command):
    image=ImageOps.contain(source('Btn_CategoryAISetting003'),(24,24),Image.Resampling.LANCZOS)
    photo=ImageTk.PhotoImage(image,master=parent)
    button=ttk.Button(parent,text='回復',image=photo,compound='none',width=0,
                      style='Icon.Tab.TButton',padding=(2,1),command=command)
    button._recovery_icon=photo
    return button
