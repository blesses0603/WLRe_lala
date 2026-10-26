"""Compact action button with an animated rainbow border while enabled."""
import colorsys
import math
import time
from functools import lru_cache
from tkinter import ttk
from PIL import Image, ImageDraw
from wlre.ui.automation_control_icons import control_icon_photo


@lru_cache(maxsize=8)
def edge_points(width,height):
    """Sample straight edges and corners at comparable distances."""
    radius=min(9,(width-3)/2,(height-3)/2)
    corners=((width-2-radius,1+radius,270),(width-2-radius,height-2-radius,0),
             (1+radius,height-2-radius,90),(1+radius,1+radius,180))
    points=[]
    for index,(cx,cy,start) in enumerate(corners):
        steps=max(1,math.ceil(math.pi*radius/2/.75))
        for step in range(steps+1):
            angle=math.radians(start+90*step/steps)
            points.append((cx+radius*math.cos(angle),cy+radius*math.sin(angle)))
        nx,ny,angle=corners[(index+1)%4]
        target=(nx+radius*math.cos(math.radians(angle)),ny+radius*math.sin(math.radians(angle)))
        origin=points[-1];distance=math.dist(origin,target)
        for step in range(1,max(1,math.ceil(distance/.75))):
            fraction=step/max(1,math.ceil(distance/.75))
            points.append(tuple(a+(b-a)*fraction for a,b in zip(origin,target)))
    distinct=[]
    for point in points:
        if not distinct or math.dist(distinct[-1],point)>1e-8:distinct.append(point)
    if math.dist(distinct[-1],distinct[0])<1e-8:distinct.pop()
    points=distinct
    distances=[math.dist(point,points[(i+1)%len(points)]) for i,point in enumerate(points)]
    total=sum(distances);position=0;result=[]
    for point,distance in zip(points,distances):
        result.append((point,position/total));position+=distance
    return tuple(result)


@lru_cache(maxsize=8)
def edge_texture(width,height):
    """Fixed, continuous alpha mask; animation changes colors only."""
    scale=3;size=(width*scale,height*scale)
    mask=Image.new('L',size)
    radius=min(9,(width-3)/2,(height-3)/2)
    ImageDraw.Draw(mask).rounded_rectangle((scale,scale,(width-2)*scale,(height-2)*scale),
        radius=radius*scale,outline=255,width=4)
    texture=Image.new('P',size)
    points=edge_points(width,height)
    pixels=texture.load();alpha=mask.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if alpha[x,y]:
                _,position=min(points,key=lambda item:(item[0][0]-x/scale)**2+(item[0][1]-y/scale)**2)
                pixels[x,y]=round(position*255)
    return texture,mask


def edge_overlay(width,height,phase):
    texture,mask=edge_texture(width,height)
    colored=texture.copy()
    palette=[]
    for index in range(256):
        palette.extend(round(v*255) for v in colorsys.hsv_to_rgb((index/256+phase)%1,.85,1))
    colored.putpalette(palette)
    overlay=colored.convert('RGBA');overlay.putalpha(mask)
    # Area averaging keeps alpha outside the exact curve at zero: no ringing.
    return overlay.resize((width,height),Image.Resampling.BOX)


class HaloButton(ttk.Button):
    def __init__(self,parent,command):
        super().__init__(parent,text='啟動',width=4,padding=(3,2),command=command)
        self.active=False;self.phase=0;self.job=None;self.started=None
        self._control_icons = {
            kind: control_icon_photo(self, kind)
            for kind in ('play', 'pause')
        }
        if self._control_icons['play'] is not None:
            self.configure(image=self._control_icons['play'],
                           compound='none', width=0, padding=(2, 1))
        self.halo_owner=self
        self.surfaces=[];self.photos=[];self.halo_visible=False
        self.bind('<Map>',self.animate,add='+')
        self.bind('<Unmap>',self.pause,add='+')
        self.bind('<Destroy>',self.pause,add='+')

    def set_active(self,active):
        active=bool(active)
        if active==self.active:return
        self.active=active
        if active:self.started=time.monotonic()
        self.configure(text='關閉' if self.active else '啟動')
        icon = self._control_icons['pause' if self.active else 'play']
        if icon is not None:
            self.configure(image=icon, compound='none')
        else:
            self.configure(image='', compound='none', width=4,
                           padding=(3, 2))
        if self.active:self.animate()
        else:
            self.pause();self.paint_edge()

    def pause(self,event=None):
        if self.job is not None:self.after_cancel(self.job);self.job=None

    def animate(self,event=None):
        if not self.active or not self.winfo_ismapped() or self.job is not None:return
        self.phase=((time.monotonic()-self.started)/3)%1
        started=time.perf_counter()
        self.paint_edge()
        self.job=self.after(max(1,16-round((time.perf_counter()-started)*1000)),self.advance)

    def set_button_surfaces(self,surfaces,photos):
        self.surfaces=surfaces;self.photos=photos
        self.paint_edge()

    def paint_edge(self):
        self.halo_visible=bool(self.active and self.surfaces)
        overlay=None
        if self.halo_visible:
            width,height=self.surfaces[0].size
            overlay=edge_overlay(width,height,self.phase)
        for surface,photo in zip(self.surfaces,self.photos):
            photo.paste(Image.alpha_composite(surface,overlay) if overlay is not None else surface)
        if self.winfo_ismapped():self.event_generate('<Expose>',when='tail')

    def advance(self):
        self.job=None;self.animate()
