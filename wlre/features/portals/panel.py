"""Portal controls, navigation guards and review panel.

Original user confirmation/destination validation remain in the existing
feature callbacks, while underlying world services remain authoritative.
"""
import tkinter as tk
from tkinter import ttk
from wlre.paths import PROJECT_ROOT
from wlre.ui.window_layout import configure_dialog
from wlre.services.world.portal_policy import destination_problem


class PortalInteractionMixin:
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

    def show_audit(self):
        if self.audit_window and self.audit_window.winfo_exists():
            self.audit_window.lift();return
        win=tk.Toplevel(self);self.audit_window=win
        win.title('地圖傳送點逐圖核對 · 1262');configure_dialog(win,1000,600);win.resizable(False,False)
        ttk.Label(win,text='已核對數量只代表門編號與觸碰事件有效，正式服是否允許遠距觸發仍待實測。').pack(fill='x',padx=10,pady=8)
        def open_report():
            import webbrowser
            webbrowser.open((PROJECT_ROOT/'docs/Portal_Review_1262.html').as_uri())
        ttk.Button(win,text='開啟完整逐筆核對報告',command=open_report).pack(anchor='e',padx=10,pady=(0,6))
        body=ttk.Frame(win);body.pack(fill='both',expand=True,padx=10)
        cols=('scene','name','count','normal','event','nav','status')
        tree=ttk.Treeview(body,columns=cols,show='headings')
        for c,label,w in zip(cols,('地圖ID','名稱','傳點數','一般出口','事件入口','可直接嘗試','核對結果'),(65,165,65,70,70,100,290)):
            tree.heading(c,text=label);tree.column(c,width=w,minwidth=45)
        bar=ttk.Scrollbar(body,orient='vertical',command=tree.yview);bar.pack(side='right',fill='y')
        tree.configure(yscrollcommand=bar.set);tree.pack(fill='both',expand=True)
        for row in self.portals.audit.values():
            tree.insert('', 'end',iid=str(row['scene']),values=(row['scene'],row['name'],row['count'],row['normal'],row['event'],row.get('direct_ready',0),row['status']))

