"""Canvas rendering and geometry for the minimap.

This UI feature draws from existing verified map/route snapshots. Rendering
does not authorize movement, portal travel, or NPC network commands.
"""
import math
from PIL import Image, ImageTk
from wlre.services.world.display_position import current_position
from wlre.services.world.portals import portal_map_pixel


class MinimapCanvasMixin:
    def resize(self,event):
        if self._resize_job:self.after_cancel(self._resize_job)
        self._resize_job=self.after(60,self.draw)

    def view(self):
        w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
        size=max(1,min(w,h)-16)
        return (w-size)/2,(h-size)/2,size/1024

    def screen_pixel(self,u,v):
        left,top,scale=self.view()
        return left+u*scale,top+v*scale

    def draw(self):
        self._resize_job=None
        self.canvas.delete('all')
        if not self.projection:
            self.canvas.create_text(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,
                                    text=('等待角色地圖同步…' if self.selected_id is None else '此場景沒有原始小地圖\n請從左側清單選擇返回出口\n地圖圖示與座標操作已停用'),fill='#c8d3dc',font=('Microsoft JhengHei UI',-14),justify='center')
            return
        left,top,scale=self.view()
        size=max(1,round(1024*scale))
        if self.image:
            image_key=(self.selected_id,size)
            if getattr(self,'_photo_key',None)!=image_key or getattr(self,'_photo_source',None) is not self.image:
                self.photo=ImageTk.PhotoImage(self.image.resize((size,size),Image.Resampling.LANCZOS),master=self.canvas)
                self._photo_key=image_key
                self._photo_source=self.image
            self.canvas.create_image(left,top,image=self.photo,anchor='nw')
        if self.route:
            xy=[c for p in self.route['points'] for c in self.screen_pixel(*self.projection.navigation_to_pixel(p[0],p[2]))]
            if len(xy)>=4:self.canvas.create_line(*xy,fill='#ffce58',width=3)
        for p in self.portal_rows:
            point = portal_map_pixel(p, self.projection)
            if point is None:
                continue
            px,py=self.screen_pixel(*point)
            color='#b591ff' if p['kind']=='event' else '#57e9ef'
            if not p.get('direct_eligible'):color='#9b9b9b'
            selected=p is self.selected_portal
            r=8 if selected else 5
            self.canvas.create_oval(px-r-2,py-r-2,px+r+2,py+r+2,fill='#183e4d',outline='#fff6a0' if selected else '#dafcff',width=2)
            spiral=[]
            for step in range(37):
                angle=step/36*math.pi*3.5;radius=step/36*r
                spiral.extend((px+math.cos(angle)*radius,py+math.sin(angle)*radius))
            self.canvas.create_line(*spiral,fill=color,width=2,smooth=True)
            if selected:self.canvas.create_text(px,py-14,text=p['name'],fill='white',anchor='s')
        for npc in self.npc_rows:
            x,y=npc['x'],npc['y']
            if x is None or y is None or not 0<=x<=65535 or not 0<=y<=65535:
                continue
            u,v=self.projection.packet_to_pixel(x,y)
            if not 0<=u<=1024 or not 0<=v<=1024:
                continue
            px,py=self.screen_pixel(u,v)
            selected=npc is self.selected_npc
            radius=5 if selected else 3
            self.canvas.create_oval(px-radius,py-radius,px+radius,py+radius,
                                    fill='#be8bec',outline='#fff3c1' if selected else '')
            if selected:
                self.canvas.create_text(px,py-12,text=npc['name'],fill='white',anchor='s')
        location=self.state.get('location',{})
        fix=location.get('confirmed')
        displayed=current_position(self.state)
        if displayed and displayed['scene']==self.selected_id:
            if displayed['kind']=='local_report' and fix:
                x,y=self.screen_pixel(*self.projection.packet_to_pixel(fix['x'],fix['y']))
                self.canvas.create_oval(x-5,y-5,x+5,y+5,fill='',outline='#b7bec7',width=2)
                self.canvas.create_text(x+9,y-12,text=f"上次位置 ({fix['x']}, {fix['y']})",fill='#c5cbd3',anchor='w')
            x,y=self.screen_pixel(*self.projection.packet_to_pixel(displayed['x'],displayed['y']))
            self.canvas.create_oval(x-6,y-6,x+6,y+6,fill='#ed4747' if displayed['filled'] else '',outline='#ff5959',width=2)
            self.canvas.create_text(x+9,y+13,text=f"({displayed['x']}, {displayed['y']})",fill='white',anchor='w')
        targets=[t for t in (location.get('requested_destination'),location.get('server_destination')) if t and t.get('scene')==self.selected_id]
        local=self.state.get('local_movement')
        if local and local.get('scene')==self.selected_id:
            targets=[local['target']]
        if targets:
            target=max(targets,key=lambda t:t.get('packet_number',0))
            x,y=self.screen_pixel(*self.projection.packet_to_pixel(target['x'],target['y']))
            self.canvas.create_oval(x-7,y-7,x+7,y+7,outline='#ffc654',width=2)
        if not self.state.get('player'):
            self.canvas.create_text(left+12,top+12,text='離線地圖預覽',fill='white',anchor='nw')

