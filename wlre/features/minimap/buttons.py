"""Explicit minimap click/double-click interaction.

Keep the existing single-click selection and guarded double-click callback.
Only the app's existing movement/portal services can send commands.
"""
import math
from wlre.services.world.portals import nearest_marker


class MinimapPickMixin:
    def pick(self,event):
        if not self.projection:return False
        marker=nearest_marker(self.portal_rows,self.projection,self.screen_pixel,event.x,event.y)
        if marker is not None:
            self.select_portal(marker)
            return False
        # NPC markers are position references, not walk or event commands.
        npc_candidates=[]
        for npc in self.npc_rows:
            if npc['x'] is None or npc['y'] is None or not 0<=npc['x']<=65535 or not 0<=npc['y']<=65535:
                continue
            u,v=self.projection.packet_to_pixel(npc['x'],npc['y'])
            if not 0<=u<=1024 or not 0<=v<=1024:
                continue
            px,py=self.screen_pixel(u,v)
            if math.hypot(px-event.x,py-event.y)<=8:
                npc_candidates.append((math.hypot(px-event.x,py-event.y),npc))
        if npc_candidates:
            self.select_npc(min(npc_candidates,key=lambda x:x[0])[1])
            return False
        self.selected_portal=None
        self.selected_npc=None
        self.update_portal_button()
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

