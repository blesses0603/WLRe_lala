"""Compact action button with an animated rainbow border while enabled."""
import colorsys
import math
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
from wlre.ui.theme import BG


class HaloButton(tk.Canvas):
    def __init__(self,parent,command):
        super().__init__(parent,width=60,height=26,highlightthickness=0,bg=BG,bd=0)
        self.background_photo=None;self.background_item=None
        self.active=False;self.phase=0;self.job=None
        self.button=ttk.Button(self,text='啟動',width=4,padding=(2,0),command=command)
        self.button.halo_owner=self
        self.surfaces=[];self.photos=[];self.halo_visible=False
        self.create_window(30,13,window=self.button,width=52,height=20)
        self.bind('<Map>',self.animate,add='+')
        self.bind('<Unmap>',self.pause,add='+')
        self.bind('<Destroy>',self.pause,add='+')

    def set_glass_background(self,image):
        """Match the window artwork beneath the halo instead of a solid box."""
        self.background_photo=ImageTk.PhotoImage(image,master=self)
        if self.background_item is None:
            self.background_item=self.create_image(0,0,anchor='nw',image=self.background_photo,tags='glass-background')
        else:self.itemconfigure(self.background_item,image=self.background_photo)
        self.tag_lower(self.background_item)

    def invoke(self):return self.button.invoke()

    def set_active(self,active):
        self.active=bool(active)
        self.button.configure(text='關閉' if self.active else '啟動')
        if self.active:self.animate()
        else:
            self.pause();self.paint_edge()

    def pause(self,event=None):
        if self.job is not None:self.after_cancel(self.job);self.job=None

    def animate(self,event=None):
        if not self.active or not self.winfo_ismapped() or self.job is not None:return
        self.paint_edge()
        self.phase=(self.phase+0.035)%1
        self.job=self.after(100,self.advance)

    def set_button_surfaces(self,surfaces,photos):
        self.surfaces=surfaces;self.photos=photos
        self.paint_edge()

    def paint_edge(self):
        self.halo_visible=bool(self.active and self.surfaces)
        overlay=None
        if self.halo_visible:
            width,height=self.surfaces[0].size
            scale=3
            overlay=Image.new('RGBA',(width*scale,height*scale))
            draw=ImageDraw.Draw(overlay)
            radius=min(9,(width-3)/2,(height-3)/2)
            points=[]
            # Follow the same inset and corner radius as the glass button skin.
            for cx,cy,start in ((width-2-radius,1+radius,270),(width-2-radius,height-2-radius,0),
                                (1+radius,height-2-radius,90),(1+radius,1+radius,180)):
                for step in range(17):
                    angle=math.radians(start+90*step/16)
                    points.append(((cx+radius*math.cos(angle))*scale,(cy+radius*math.sin(angle))*scale))
            for index,point in enumerate(points):
                color=tuple(round(v*255) for v in colorsys.hsv_to_rgb((index/len(points)+self.phase)%1,.85,1))+(255,)
                draw.line((point,points[(index+1)%len(points)]),fill=color,width=4)
            overlay=overlay.resize((width,height),Image.Resampling.LANCZOS)
        for surface,photo in zip(self.surfaces,self.photos):
            photo.paste(Image.alpha_composite(surface,overlay) if overlay is not None else surface)

    def advance(self):
        self.job=None;self.animate()
