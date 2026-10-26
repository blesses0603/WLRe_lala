"""Local map geometry preview. No reference to the client's command queue."""
import json
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.layout import heading
from tkinter import ttk, filedialog, messagebox
from wlre.ui.theme import install as install_theme
from wlre.services.world.navigation import Repository, NavigationError
from wlre.services.world.coordinates import Coordinates
from wlre.services.world.map_names import map_label, model_label, map_choices, parse_map_id
from wlre.features.minimap.ui.minimap import SmallMaps
from wlre.services.world.display_position import current_position
from PIL import Image,ImageTk


class NavigationWindow:
    def __init__(self, parent, suggested_scene=None, on_route=None):
        install_theme(parent.winfo_toplevel())
        self.window = tk.Toplevel(parent)
        self.window.title('全場景導航 · 離線幾何預覽')
        configure_dialog(self.window,1120,760)
        self.repository = Repository()
        self.smallmaps = SmallMaps()
        self.on_route = on_route
        self.background_image = None
        self.background_projection = None
        self.background_photo = None
        self.converter = Coordinates()
        self.linked_state = None
        self.linked_revision = None
        self.mesh = None
        self.result = None
        self.click_start = True
        frame = ttk.Frame(self.window,padding=10)
        frame.pack(fill='both',expand=True)
        heading(frame,'全場景導航','離線預覽路徑；不會自動送出移動指令。')
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill='x')
        ttk.Label(toolbar,text='場景模型').pack(side='left')
        self.scene = ttk.Combobox(toolbar,width=28,values=[r['display_name'] for r in self.repository.catalog])
        self.scene.pack(side='left',padx=5)
        self.scene.set(model_label(suggested_scene if suggested_scene is not None else 0))
        if suggested_scene is not None:
            try:self.scene.set(model_label(self.converter.mapping(suggested_scene)[1]))
            except NavigationError:self.background_image=None
        ttk.Button(toolbar,text='載入場景',command=self.load).pack(side='left',padx=5)
        ttk.Button(toolbar,text='縮放至全圖',command=self.fit).pack(side='left',padx=5)
        ttk.Button(toolbar,text='匯出預覽路徑',command=self.save).pack(side='left',padx=5)
        self.show_mesh=tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar,text='導航邊界',variable=self.show_mesh,command=self.draw).pack(side='left',padx=5)
        mapping = ttk.Frame(frame)
        mapping.pack(fill='x',pady=5)
        self.packet_mode = tk.BooleanVar(value=False)
        self.logical_map = tk.StringVar(value=map_label(suggested_scene if suggested_scene is not None else 10000))
        ttk.Checkbutton(mapping,text='使用遊戲封包 X/Y',variable=self.packet_mode,
                        command=lambda:self.load_mapped() if self.packet_mode.get() else self.load()).pack(side='left')
        ttk.Label(mapping,text='地圖').pack(side='left',padx=5)
        ttk.Combobox(mapping,textvariable=self.logical_map,width=28,values=map_choices()).pack(side='left')
        ttk.Button(mapping,text='依地圖表載入模型',command=self.load_mapped).pack(side='left',padx=5)
        ttk.Label(frame,text='724 份一般場景導航圖／39 個 StageScenes 尚無同類圖。ID 為資源 ID，與遊戲地圖 ID 的對應仍需核對。',wraplength=1030).pack(fill='x',pady=(8,2))
        ttk.Label(frame,text='勾選封包模式後，第二軸是遊戲 Y；其餘模式是導航 Int3 Z。高度欄仍用導航 Int3。路徑不會送出移動。',wraplength=1030).pack(fill='x')
        form = ttk.Frame(frame)
        form.pack(fill='x',pady=8)
        self.coordinates = [tk.StringVar() for _ in range(6)]
        for i,label in enumerate(('起點 X','起點 Y／Z','導航高度（選填）','終點 X','終點 Y／Z','導航高度（選填）')):
            ttk.Label(form,text=label).grid(row=0,column=i,sticky='w',padx=3)
            ttk.Entry(form,textvariable=self.coordinates[i],width=15).grid(row=1,column=i,padx=3,sticky='ew')
            form.columnconfigure(i,weight=1)
        ttk.Button(form,text='預覽路徑',command=self.plan).grid(row=1,column=6,padx=6)
        self.status = tk.StringVar(value='點一下選起點，再點一下選終點；之後按「預覽路徑」。滾輪縮放。')
        ttk.Label(frame,textvariable=self.status,wraplength=1030).pack(fill='x',pady=(0,6))
        self.canvas = tk.Canvas(frame,background='#101a24',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.fit())
        self.canvas.bind('<Button-1>',self.pick)
        self.canvas.bind('<MouseWheel>',lambda e:self.zoom(e,1.2 if e.delta>0 else 1/1.2))
        self.canvas.bind('<Button-4>',lambda e:self.zoom(e,1.2))
        self.canvas.bind('<Button-5>',lambda e:self.zoom(e,1/1.2))
        self.window.after_idle(self.load)

    def load(self):
        self.mesh = None
        self.background_image = None
        self.background_projection = None
        self.result = None
        self.click_start = True
        self.canvas.delete('all')
        for v in self.coordinates:v.set('')
        try:
            if self.packet_mode.get():
                _,scene,_ = self.converter.mapping(self.logical_map.get())
                if self.repository.normalize(self.scene.get())!=scene:
                    raise NavigationError('場景與邏輯地圖不同，請按「依地圖表載入模型」。')
            self.mesh = self.repository.load(self.scene.get())
            self.background_image = self.smallmaps.image(self.mesh.scene_id)
            try:self.background_projection=self.smallmaps.for_model(self.mesh.scene_id,self.logical_map.get())
            except NavigationError:self.background_image=None
            self.scene.set(model_label(self.mesh.scene_id))
            self.fit()
            self.status.set(f'{model_label(self.mesh.scene_id)}｜{len(self.mesh.faces)} 個三角形｜點選起點及終點；滾輪縮放。')
        except (OSError,ValueError,KeyError) as exc:
            self.status.set(str(exc))

    def load_mapped(self):
        try:
            _,scene,_ = self.converter.mapping(self.logical_map.get())
            self.scene.set(model_label(scene))
            self.load()
            self.update_live_state(self.linked_state)
        except (ValueError,KeyError) as exc:
            self.mesh = None
            self.result = None
            self.canvas.delete('all')
            self.status.set(str(exc))

    def stale_for_current_map(self):
        if not self.linked_state or not self.mesh:return False
        nav = self.linked_state.get('navigation',{})
        try:
            _,scene,_ = self.converter.mapping(self.logical_map.get())
            return (nav.get('scene')==parse_map_id(self.logical_map.get()) and scene==self.mesh.scene_id
                    and nav.get('stale',False))
        except (ValueError,KeyError):return False

    def update_live_state(self,state):
        self.linked_state = state
        revision = state.get('navigation',{}).get('revision') if state else None
        if revision != self.linked_revision:
            self.result = None
            self.linked_revision = revision
            if hasattr(self,'canvas') and self.mesh:self.draw()
        if self.stale_for_current_map():
            self.result = None
            self.draw()
            self.status.set('收到障礙相關變更，舊路徑已失效；尚未取得完整動態形狀，暫停此地圖的連線預覽。')
        if self.mesh and hasattr(self,'canvas'):self.draw()

    def display_point(self,x,z):
        if self.packet_mode.get():return self.converter.to_packet(self.logical_map.get(),x,z)
        return x,z

    def navigation_point(self,x,y):
        if self.packet_mode.get():return self.converter.to_navigation(self.logical_map.get(),x,y)
        return x,y

    def fit(self):
        if not self.mesh or not self.mesh.faces:return
        vertices = [v for tri in self.mesh.faces for v in tri]
        self.cx = (min(v[0] for v in vertices)+max(v[0] for v in vertices))/2
        self.cz = (min(v[2] for v in vertices)+max(v[2] for v in vertices))/2
        width,height = max(self.canvas.winfo_width(),80),max(self.canvas.winfo_height(),80)
        self.scale = min((width-40)/max(1,max(v[0] for v in vertices)-min(v[0] for v in vertices)),
                         (height-40)/max(1,max(v[2] for v in vertices)-min(v[2] for v in vertices)))
        self.draw()

    def screen(self,point):
        return ((point[0]-self.cx)*self.scale+self.canvas.winfo_width()/2,
                self.canvas.winfo_height()/2-(point[2]-self.cz)*self.scale)

    def world(self,x,y):
        return ((x-self.canvas.winfo_width()/2)/self.scale+self.cx,
                (self.canvas.winfo_height()/2-y)/self.scale+self.cz)

    def zoom(self,event,factor):
        if not self.mesh or not hasattr(self,'scale'):return
        x,z = self.world(event.x,event.y)
        self.scale *= factor
        self.cx = x-(event.x-self.canvas.winfo_width()/2)/self.scale
        self.cz = z+(event.y-self.canvas.winfo_height()/2)/self.scale
        self.draw()

    def draw(self):
        self.canvas.delete('all')
        if not self.mesh:return
        if self.background_image and self.background_projection:
            width,height=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
            x,z=self.world(0,0)
            u,v=self.background_projection.navigation_to_pixel(x,z)
            ratio=self.background_projection.rate/(1000*self.scale)
            image=self.background_image.transform((width,height),Image.Transform.AFFINE,
                      (ratio,0,u,0,ratio,v),resample=Image.Resampling.BILINEAR,fillcolor=(16,26,36,255))
            self.background_photo=ImageTk.PhotoImage(image,master=self.canvas)
            self.canvas.create_image(0,0,image=self.background_photo,anchor='nw')
        if self.show_mesh.get() or self.background_image is None:
            for tri in self.mesh.faces:
                xy=[c for p in tri for c in self.screen(p)]
                self.canvas.create_polygon(*xy,fill='' if self.background_image else '#284b59',outline='#65c6d5',width=1)
        if self.result:
            xy=[c for p in self.result['points'] for c in self.screen(p)]
            if len(xy)>=4:self.canvas.create_line(*xy,fill='#ffc857',width=3)
        if self.linked_state:
            location=self.linked_state.get('location',{})
            displayed=current_position(self.linked_state)
            fix=location.get('confirmed')
            markers=[]
            if displayed and displayed['kind']=='local_report' and fix:
                markers.append((fix,'上次位置','#b7bec7',False))
            if displayed:markers.append((displayed,displayed['label'],'#ff4545',displayed['filled']))
            for point,label,color,filled in markers:
                try:
                    _,scene,_=self.converter.mapping(point['scene'])
                    if scene==self.mesh.scene_id:
                        x,z=self.converter.to_navigation(point['scene'],point['x'],point['y'])
                        px,py=self.screen((x,0,z))
                        self.canvas.create_oval(px-6,py-6,px+6,py+6,fill=color if filled else '',outline=color,width=2)
                        self.canvas.create_text(px+9,py+15,text=label,fill=color,anchor='w')
                except NavigationError:pass
        for offset,color,label in ((0,'#56dfb1','起'),(3,'#ff8274','終')):
            try:
                x,z = self.navigation_point(float(self.coordinates[offset].get()),float(self.coordinates[offset+1].get()))
            except ValueError:continue
            sx,sy = self.screen((x,0,z))
            self.canvas.create_oval(sx-5,sy-5,sx+5,sy+5,fill=color,outline='')
            self.canvas.create_text(sx+12,sy-12,text=label,fill=color)

    def pick(self,event):
        if not self.mesh or not hasattr(self,'scale'):return
        x,z = self.world(event.x,event.y)
        try:x,z = self.display_point(x,z)
        except NavigationError as exc:
            self.status.set(str(exc));return
        offset = 0 if self.click_start else 3
        self.coordinates[offset].set(f'{x:.3f}')
        self.coordinates[offset+1].set(f'{z:.3f}')
        self.coordinates[offset+2].set('')
        self.click_start = not self.click_start
        self.result = None
        self.draw()
        self.status.set('已選起點，請點終點。' if not self.click_start else '已選終點，按「預覽路徑」。')

    def plan(self):
        self.result = None
        if self.on_route:self.on_route(None)
        if not self.mesh:return
        try:
            if self.stale_for_current_map():
                raise NavigationError('此地圖收到動態障礙變更；靜態快取路徑已失效。')
            values = [float(v.get()) if v.get().strip() else None for v in self.coordinates]
            if any(values[i] is None for i in (0,1,3,4)):
                raise NavigationError('請填寫起終點 X、Z，或在圖上點選。')
            if self.packet_mode.get():
                _,scene,_ = self.converter.mapping(self.logical_map.get())
                if scene!=self.mesh.scene_id:raise NavigationError('場景與邏輯地圖模型不同，請依地圖表載入。')
                self.result = self.converter.route(self.repository,self.logical_map.get(),values[:2],values[3:5],values[2],values[5])
            else:
                self.result = self.mesh.route(values[:2],values[3:5],values[2],values[5])
            self.status.set(f'離線預覽：通過 {len(self.result["faces"])} 個三角形，{len(self.result["points"])} 個路徑點。未套用執行時障礙與原始節點旗標。')
            if self.on_route:self.on_route(self.result)
        except (ValueError,TypeError) as exc:
            self.status.set(str(exc))
        self.draw()

    def save(self):
        if not self.result:
            messagebox.showinfo('路徑','請先成功預覽一條路徑。',parent=self.window)
            return
        path = filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',
                    initialfile=self.mesh.scene_id+'_offline_route.json',filetypes=[('JSON','*.json')])
        if path:
            try:
                with open(path,'w',encoding='utf8') as f:json.dump(self.result,f,ensure_ascii=False,indent=2)
            except OSError as exc:messagebox.showerror('匯出失敗',str(exc),parent=self.window)


def main():
    root = tk.Tk()
    root.withdraw()
    viewer = NavigationWindow(root)
    viewer.window.protocol('WM_DELETE_WINDOW',root.destroy)
    root.mainloop()


if __name__=='__main__':main()
