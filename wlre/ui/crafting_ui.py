"""Embedded icon crafting page and commands shared with queue/plan windows."""
from tkinter import ttk,messagebox
from wlre.services.items.crafting import recipe_plan
from wlre.services.items.combat_resources import item_name
from wlre.network.wire import ProtocolError
from wlre.ui.crafting_browser import CraftingBrowser


class CraftingPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.state={};self.browser=None;self.plan_window=None
        self.open_browser()
        self.bind('<Destroy>',self.cleanup,add='+')

    @property
    def recipe_id(self):return self.open_browser().selected
    @property
    def count(self):return self.open_browser().count
    @property
    def icons(self):return self.open_browser().icons
    @property
    def status(self):return self.open_browser().message

    def cleanup(self,event):
        if event.widget is self and self.browser:self.browser.close()

    def open_browser(self):
        if not self.browser or self.browser.closed:self.browser=CraftingBrowser(self,embedded=True)
        return self.browser

    def open_plan(self):
        if self.plan_window and self.plan_window.window.winfo_exists():
            self.plan_window.window.deiconify();self.plan_window.window.lift();return self.plan_window
        from wlre.ui.crafting_plan_ui import PlanWindow
        self.plan_window=PlanWindow(self)
        self.plan_window.window.protocol('WM_DELETE_WINDOW',self.plan_window.window.withdraw)
        return self.plan_window

    def command(self,action,index=None):
        cmd={'type':'craft','action':action}
        if action in ('up','down','delete'):
            if index is None:self.status.set('請先選取製作排程');return
            cmd.update(index=int(index),revision=self.state.get('crafting',{}).get('revision'))
            if action=='delete' and not messagebox.askyesno('移除製作排程','確定放棄此製作項目？材料是否退還依伺服器規則。',parent=self.app.root):return
        self.app.send(cmd)

    def add(self,item_id,count):
        try:
            count=int(count)
            from types import SimpleNamespace
            data=self.state
            state=SimpleNamespace(player=data.get('player',{}),furniture=data.get('furniture',{}),crafting=data.get('crafting',{}),inventory=data.get('inventory',{}))
            if not item_id:raise ProtocolError('請選擇配方')
            if not data.get('player'):raise ProtocolError('請先登入角色')
            recipe,allocations,_=recipe_plan(state,item_id,count)
        except (ValueError,KeyError,ProtocolError,AttributeError) as exc:self.status.set(str(exc));return
        text=f"製作：{item_name(item_id)} ×{recipe['output']*count}\n設備：{item_name(recipe['tool_id'])}\n背包消耗："+'、'.join(f"{item_name(a['item_id'])} ×{a['count']}" for a in allocations)
        if not messagebox.askyesno('加入製作排程',text+'\n\n確認送出？',parent=self.app.root):return
        self.app.send({'type':'craft','action':'add','item_id':item_id,'count':count})

    def render(self,state):
        self.state=state
        if self.plan_window and self.plan_window.window.winfo_exists():self.plan_window.render(state)
        if self.browser and not self.browser.closed:self.browser.update_state(state)
