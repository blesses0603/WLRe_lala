"""PortalMapActions user actions; server authorization remains shared."""
from wlre.services.world.portal_policy import allowed_rows, destination_problem


class PortalMapActions:
    def update_portal_button(self):
        p=self.selected_portal
        enabled=bool(p and destination_problem(p,self.maps) is None and p.get('direct_eligible') and self.state.get('player',{}).get('scene')==self.selected_id and not self.state.get('battle',{}).get('active') and not self.state.get('event_flow',{}).get('blocked'))
        self.portal_go.configure(state='normal' if enabled else 'disabled',
                                 text='返回有圖地圖' if self.image is None else '直接嘗試換圖')


    def choose_portal(self,event=None):
        selected=self.portal_list.curselection()
        if not selected or selected[0]>=len(self.list_rows):return
        p=self.list_rows[selected[0]]
        self.select_portal(p)


    def select_portal(self,p):
        self.selected_npc=None
        self.npc_list.selection_clear(0,'end')
        self.selected_portal=p
        self.portal_list.selection_clear(0,'end')
        self.portal_list.selection_set(self.list_rows.index(p))
        self.portal_list.see(self.list_rows.index(p))
        self.portal_status.set(p['name']+'｜'+p.get('direct_note','尚未核對觸碰事件'))
        self.update_portal_button()
        self.draw()


    def go_portal(self):
        if not self.selected_portal:return False
        try:
            problem=destination_problem(self.selected_portal,self.maps)
            if problem:raise ValueError(problem)
            self.portals.direct_target(self.selected_portal,self.state.get('player',{}).get('scene'))
            if self.on_portal is None:
                raise ValueError('尚未接上本機角色的出口觸發功能。')
            self.on_portal(self.selected_portal['id'])
            return True
        except ValueError as exc:
            self.portal_status.set(str(exc));return False
