from kivy.metrics import dp
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy.uix.widget import Widget
from android_app.pages.general import Page
from android_app.widgets import label, button, row, field, pick
from android_app.assets import texture
from wlre.ui.minimap import SmallMaps
from wlre.services.world.portals import Portals
from wlre.services.world.portal_policy import allowed_rows
from wlre.services.world.map_names import map_label, parse_map_id
from wlre.services.world.display_position import current_position


class MapCanvas(Widget):
    def __init__(self, on_pick, **kwargs):
        super().__init__(size_hint_y=None,height=dp(320),**kwargs)
        self.texture=None;self.projection=None;self.player=None;self.selected=None;self.portals=[];self.on_pick=on_pick
        self.bind(pos=lambda *_:self.draw(),size=lambda *_:self.draw())
    def box(self):
        side=min(self.width,self.height)
        return self.x+(self.width-side)/2,self.y+(self.height-side)/2,side
    def screen(self,u,v):
        x,y,size=self.box();return x+u/1024*size,y+(1024-v)/1024*size
    def draw(self):
        self.canvas.clear()
        x,y,size=self.box()
        with self.canvas:
            Color(.08,.15,.2,1);Rectangle(pos=self.pos,size=self.size)
            if not self.texture:return
            Color(1,1,1,1);Rectangle(texture=self.texture,pos=(x,y),size=(size,size))
            if self.projection:
                for portal in self.portals:
                    if portal.get('coordinate_valid'):
                        u,v=self.screen(*self.projection.packet_to_pixel(portal['x'],portal['y']))
                        Color(.2,1,1,1);Line(circle=(u,v,dp(4)),width=1.2)
                for point,color in ((self.player,(1,.2,.2,1)),(self.selected,(1,.85,.2,1))):
                    if point:
                        u,v=self.screen(*self.projection.packet_to_pixel(point['x'],point['y']))
                        Color(*color);Ellipse(pos=(u-dp(4),v-dp(4)),size=(dp(8),dp(8)))
    def on_touch_down(self,touch):
        x,y,size=self.box()
        if self.texture and self.projection and x<=touch.x<=x+size and y<=touch.y<=y+size:
            u=(touch.x-x)/size*1024;v=1024-(touch.y-y)/size*1024
            px,py=self.projection.pixel_to_packet(u,v)
            self.on_pick(round(px),round(py));return True
        return super().on_touch_down(touch)


class MapPage(Page):
    def __init__(self,d):
        super().__init__(d);self.maps=SmallMaps();self.portals=Portals();self.scene=None
        self.title=label('自動跟隨目前地圖');self.add_widget(self.title)
        self.image=MapCanvas(self.picked);self.add_widget(self.image)
        self.note=label('紅點：角色｜黃點：選取目的地｜青圈：出口');self.add_widget(self.note)
        self.add_widget(row(button('NPC／出口',lambda:self.entities(False)),button('怪物',lambda:self.entities(True))))
        self.x_input=field(self,'目的地 X',numeric=True);self.y_input=field(self,'目的地 Y',numeric=True)
        self.add_widget(row(button('移動到選取座標',self.walk),button('停止移動',lambda:d.send({'type':'stop_walk'}))))
        self.portal=None
        self.add_widget(button('直接嘗試所選出口換圖',self.direct))
        self.add_widget(button('逐圖核對',self.audit))
    def picked(self,x,y):
        self.x_input.text=str(x);self.y_input.text=str(y);self.image.selected={'x':x,'y':y};self.image.draw()
    def walk(self):
        try:self.d.send(dict(type='walk',scene=self.scene,x=int(self.x_input.text),y=int(self.y_input.text)))
        except ValueError:self.d.message.text='請選取地圖座標或輸入有效 X、Y'
    def direct(self):
        if not self.portal:self.d.message.text='請先選擇出口';return
        self.d.send(dict(type='portal_direct',portal_id=self.portal['id']), '確認嘗試換圖至 '+self.portal.get('name','所選出口')+'？')
    def entities(self,monsters):
        scene=self.scene;rows=[]
        if not monsters:
            rows += [(('portal',p),p['name']+(' · 可直接換圖' if p.get('direct_eligible') else ' · 僅檢視')) for p in self.image.portals]
        rows += [(('entity',p),('Lv.'+str(p.get('level','?'))+' ' if monsters else '')+p['name'])
                 for p in self.portals.data.get('entities',{}).get(str(scene),[]) if bool(p['kind'])==monsters]
        def choose(value):
            kind,p=value
            if scene!=self.scene:self.d.message.text='目前地圖已變更，請重新選擇';return
            self.portal=p if kind=='portal' else None
            self.note.text=p['name']+' · '+p.get('direct_note',p.get('navigation_note','已選取，尚未送出操作'))
            if p.get('coordinate_valid') or kind=='entity' and 'x' in p and 'y' in p:
                self.picked(round(p['x']),round(p['y']))
        pick('怪物' if monsters else 'NPC／出口',rows,choose)
    def audit(self):
        rows=[]
        for scene,data in sorted(self.maps.coordinates.stages.items(),key=lambda p:int(p[0])):
            has=self.maps.has_image(int(scene));portals=self.portals.for_scene(int(scene))
            rows.append((int(scene),map_label(int(scene))+(' · 有原圖' if has else ' · 無原圖')+f' · 出口 {len(portals)}'))
        pick('逐圖核對（只讀；目前地圖持續自動跟隨）',rows,lambda scene:setattr(self.note,'text',map_label(scene)+' · 原圖 '+('有' if self.maps.has_image(scene) else '無')))
    def refresh(self):
        scene=self.state.get('player',{}).get('scene')
        self.title.text='小地圖｜'+(map_label(scene) if scene is not None else '等待角色位置')
        if scene!=self.scene:
            self.scene=scene;self.portal=None;self.image.selected=None;self.x_input.text=self.y_input.text=''
            self.image.texture=None;self.image.projection=None
            if scene is not None:
                try:
                    projection,model=self.maps.projection(scene)
                    entry=self.maps.entries.get(parse_map_id(model))
                    if entry:self.image.texture=texture('smallmaps.zip',entry);self.image.projection=projection
                except (ValueError,KeyError,OSError):pass
            self.image.portals=allowed_rows(self.portals,scene,self.maps,recovery=self.image.texture is None)
            if not self.image.texture:self.note.text='此圖沒有可顯示的原始小地圖；可從 NPC／出口選擇已確認的返回出口。'
        point=current_position(self.state)
        self.image.player=point if point and point.get('scene')==scene else None
        self.image.draw()
