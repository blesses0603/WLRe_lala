"""Explicit minimap click/double-click interaction.

Keep the existing single-click selection and guarded double-click callback.
Only the app's existing movement/portal services can send commands.
"""
from wlre.services.world.portals import nearest_marker


class MinimapPickMixin:
    def pick(self,event):
        if not self.projection:return False
        marker=nearest_marker(self.portal_rows,self.projection,self.screen_pixel,event.x,event.y)
        if marker is not None:
            self.select_portal(marker)
            return False
        # NPCs have no visible markers. Do not leave invisible NPC hitboxes;
        # NPC selection and interaction stay in the sidebar list only.
        self.selected_portal=None
        self.selected_npc=None
        self.update_portal_button()
        if not getattr(getattr(self, 'maps', None), 'supports_navigation', True):
            self.note.set('1275 圖像與場景座標已校準，舊版點擊尋路未通過驗證。')
            return False
        left,top,scale=self.view()
        u,v=(event.x-left)/scale,(event.y-top)/scale
        if not (0<=u<=1024 and 0<=v<=1024):return False
        x,y=self.projection.pixel_to_packet(u,v)
        x,y=round(x),round(y)
        if not (0<=x<=65535 and 0<=y<=65535):
            self.note.set('此處超出遊戲座標範圍。');return False
        return self.on_pick(self.selected_id,x,y) is not False

    def double_pick(self,event):
        marker=nearest_marker(self.portal_rows,self.projection,self.screen_pixel,event.x,event.y) if self.projection else None
        if marker is not None:
            self.select_portal(marker);self.go_portal()
        elif self.pick(event) and self.on_move is not None:self.on_move()
        return 'break'

