"""Compact action button with an animated rainbow border while enabled."""
import colorsys
import tkinter as tk
from tkinter import ttk
from wlre.ui.theme import BG


class HaloButton(tk.Canvas):
    def __init__(self,parent,command):
        super().__init__(parent,width=60,height=26,highlightthickness=0,bg=BG,bd=0)
        self.active=False;self.phase=0;self.job=None
        self.button=ttk.Button(self,text='啟動',width=4,padding=(2,0),command=command)
        self.create_window(30,13,window=self.button,width=52,height=20)
        self.bind('<Map>',self.animate,add='+')
        self.bind('<Unmap>',self.pause,add='+')
        self.bind('<Destroy>',self.pause,add='+')

    def invoke(self):return self.button.invoke()

    def set_active(self,active):
        self.active=bool(active)
        self.button.configure(text='關閉' if self.active else '啟動')
        if self.active:self.animate()
        else:self.pause();self.delete('halo')

    def pause(self,event=None):
        if self.job is not None:self.after_cancel(self.job);self.job=None

    def animate(self,event=None):
        if not self.active or not self.winfo_ismapped() or self.job is not None:return
        self.delete('halo')
        # Evenly spaced points around all four edges; one moving hue cycle.
        points=[]
        for start,end in (((2,2),(58,2)),((58,2),(58,24)),((58,24),(2,24)),((2,24),(2,2))):
            for i in range(12):
                points.append((start[0]+(end[0]-start[0])*i/12,start[1]+(end[1]-start[1])*i/12))
        for i,(x,y) in enumerate(points):
            color='#%02x%02x%02x'%tuple(round(v*255) for v in colorsys.hsv_to_rgb((i/len(points)+self.phase)%1,0.85,1))
            self.create_line(x,y,*points[(i+1)%len(points)],fill=color,width=3,tags='halo')
        self.phase=(self.phase+0.035)%1
        self.job=self.after(100,self.advance)

    def advance(self):
        self.job=None;self.animate()
