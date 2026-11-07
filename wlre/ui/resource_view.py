"""Live inventory and server-confirmed storage, separate from skill browsing."""
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.rounded_notebook import RoundedNotebook
from tkinter import ttk,messagebox
from wlre.ui.storage_transfer_form import StorageTransferForm
from wlre.services.items.combat_resources import food_command, field_context
from wlre.services.battle.battle_commands import owned_units
from wlre.ui.crafting_browser import ItemIcons
from wlre.ui.bag_grid import BagGrid
from wlre.ui.room_storage_status import unlock_message, storage_sync_message, confirmed_view
from wlre.ui.layout import heading,scroll_table

class ResourceView:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root);self.window.title('包包與超空間袋');self.window._no_glass_border=True;configure_dialog(self.window,1040,700)
        self.signature=None;self.bag_map={};self.bag_images={};self.icons=ItemIcons(self.window)
        self.window.bind('<Destroy>',self.destroyed,add='+')
        header=ttk.Frame(self.window,padding=(12,10,12,0));header.pack(fill='x')
        heading(header,'包包與超空間袋','搜尋已同步物品，選取後使用下方操作。')
        bar=ttk.Frame(self.window,padding=(12,0,12,8));bar.pack(fill='x')
        ttk.Label(bar,text='搜尋名稱／ID').pack(side='left')
        self.query=tk.StringVar();ttk.Entry(bar,textvariable=self.query,width=25).pack(side='left',padx=6)
        ttk.Button(bar,text='更新顯示',command=self.refresh).pack(side='left')
        self.status=tk.StringVar();ttk.Label(self.window,textvariable=self.status,wraplength=970).pack(fill='x',padx=10)
        # Keep a single thematic surface, no extra coloured outer margin.
        tabs=RoundedNotebook(self.window);tabs.pack(fill='both',expand=True,padx=4,pady=(0,4))
        self.tabs=tabs
        self.storage_queued_revision=None
        self.storage_form=StorageTransferForm(self.window,app,self.storage_sent,self.cancel_storage)
        bag=ttk.Frame(tabs);remote=ttk.Frame(tabs)
        tabs.add(bag,text='實際包包')
        tabs.add(remote,text='超空間袋')
        self.bag=BagGrid(bag,self.icons,self.use_item)
        self.bag.pack(fill='both',expand=True)
        # The large duplicate HP/SP row is no longer needed.
        # Context-specific recovery buttons remain in the compact item strip.
        self.remote_status=tk.StringVar(value='等待 S62 同步')
        self.remote_unlock_status=tk.StringVar(value='等待背包同步')
        # A compact header preserves vertical space for actual item slots;
        # the earlier duplicated headline and large icon compressed tiles into strips.
        remote_body=ttk.Frame(remote,padding=(6,2))
        remote_body.pack(fill='both',expand=True)
        remote_head=ttk.Frame(remote_body)
        remote_head.pack(fill='x',pady=(0,2))
        self.remote_icon=self.icons.get(34977,34)
        ttk.Label(remote_head,image=self.remote_icon).pack(side='left',padx=(0,8))
        ttk.Label(remote_head,text='超空間袋｜小屋儲藏室',style='Heading.TLabel').pack(side='left')
        ttk.Label(remote_head,text='伺服器同步存取',style='Muted.TLabel').pack(side='right')
        ttk.Label(remote_body,textvariable=self.remote_status,style='Muted.TLabel',wraplength=910).pack(anchor='w',pady=(0,2))
        ttk.Label(remote_body,textvariable=self.remote_unlock_status,style='Muted.TLabel',wraplength=910).pack(anchor='w',pady=(0,2))
        storage_tabs=RoundedNotebook(remote_body)
        storage_tabs.pack(fill='both',expand=True,pady=(2,0))
        garage_page=ttk.Frame(storage_tabs);materials_page=ttk.Frame(storage_tabs)
        storage_tabs.add(garage_page,text='儲藏室')
        storage_tabs.add(materials_page,text='雜物櫃')
        self.remote_garage=BagGrid(garage_page,self.icons,lambda resource:None,
                                   read_only=True,title='儲藏室物品',compact=True,storage_actions=True)
        self.remote_materials=BagGrid(materials_page,self.icons,lambda resource:None,
                                      read_only=True,title='雜物櫃物品',compact=True,storage_actions=True)
        self.remote_garage.pack(fill='both',expand=True)
        self.remote_materials.pack(fill='both',expand=True)
        self.storage_buttons=[]
        self.add_storage_actions(self.bag,[('存入儲藏室','garage','deposit'),('存入雜物櫃','materials','deposit')])
        self.add_storage_actions(self.remote_garage,[('取出到背包','garage','withdraw')])
        self.add_storage_actions(self.remote_materials,[('取出到背包','materials','withdraw')])
        self.query.trace_add('write',lambda *a:self.refresh())
        self.set_state(app.snapshot)

    def destroyed(self,event):
        if event.widget is self.window:self.icons.close();self.bag_images.clear()

    @staticmethod
    def table(parent,columns,labels):
        frame,tree=scroll_table(parent,columns,labels,[170 if c in ('name','status','actor') else 75 for c in columns],height=10)
        frame.pack(fill='both',expand=True)
        return tree

    def refresh(self):self.signature=None;self.set_state(self.app.snapshot)

    def set_state(self,state):
        from wlre.services.items.live_combat_catalog import source_token
        signature=(source_token(),self.app.live_active,str(state.get('inventory')),str(state.get('knowledge')),str(state.get('battle_units')),state.get('battle',{}).get('active'),self.query.get(),state.get('room_storage',{}).get('revision'))
        if signature==self.signature:return
        self.signature=signature;query=self.query.get().casefold();inv=state.get('inventory',{});k=state.get('knowledge',{})
        self.status.set(f"包包：{'已同步' if inv.get('ready') else '等待S23-5'}｜{'數量有效' if inv.get('reliable') else '尚不可自動取用'}｜{len(inv.get('items',{}))}格。更新顯示不會發送未驗證的查包封包。")
        self.status.set(self.status.get()+(' 官方戰鬥資料已同步。' if source_token() is not None else ' 官方戰鬥資料尚未同步，技能與物品規則暫不可用。'))
        selected_bag=self.bag.selection()
        self.bag_map=self.bag.render(inv,query)
        self.update_remote_status(state)
        if selected_bag and selected_bag[0] in self.bag_map and not self.bag.selection():self.bag.selection_set(selected_bag[0])

    def update_remote_status(self,state):
        inventory = state.get('inventory', {})
        storage = state.get('room_storage', {})
        if self.storage_queued_revision is not None and storage.get('revision')!=self.storage_queued_revision:
            self.storage_queued_revision=None
        self.remote_unlock_status.set(unlock_message(inventory))
        self.remote_status.set(storage_sync_message(storage))
        self.remote_garage.render(confirmed_view(storage.get('garage', {})), self.query.get())
        self.remote_materials.render(confirmed_view(storage.get('materials', {})), self.query.get())
        for button,target in getattr(self,'storage_buttons',[]):
            bucket=storage.get(target,{})
            enabled=(self.app.live_active and inventory.get('ready') and inventory.get('reliable')
                     and bucket.get('ready') and bucket.get('reliable')
                     and not storage.get('pending') and not storage.get('uncertain')
                     and self.storage_queued_revision is None)
            button.configure(state='normal' if enabled else 'disabled')
        self.storage_form.render(state)

    def storage_sent(self,command):
        self.storage_queued_revision=command['storage_revision']
        for button,_ in self.storage_buttons:button.configure(state='disabled')

    def cancel_storage(self):
        self.storage_form.pack_forget()
        for grid in (self.bag,self.remote_garage,self.remote_materials):grid.card.grid()

    def storage_rejected(self,message):
        self.storage_queued_revision=None
        self.storage_form.rejected(message)
        self.update_remote_status(self.app.snapshot)

    def add_storage_actions(self,grid,actions):
        bar=ttk.Frame(grid.card)
        bar.grid(row=3,column=0,columnspan=3,sticky='e',pady=(4,0))
        for label,target,action in actions:
            button=ttk.Button(bar,text=label,
                command=lambda t=target,a=action,g=grid:self.transfer_item(g,t,a))
            button.pack(side='left',padx=3)
            self.storage_buttons.append((button,target))

    def transfer_item(self,grid,target,action):
        if self.storage_queued_revision is not None:return
        if not self.app.live_active:
            messagebox.showinfo('儲藏存取','請先登入角色',parent=self.window);return
        selected=grid.selection()
        if not selected:
            messagebox.showinfo('儲藏存取','請先點選來源物品',parent=self.window);return
        item=grid.bag_map.get(selected[0])
        if not item:return
        # The confirmation replaces the details strip so all four item rows
        # retain usable height instead of competing with another full card.
        for source in (self.bag,self.remote_garage,self.remote_materials):source.card.grid_remove()
        self.storage_form.pack(side='bottom',fill='x',before=self.tabs)
        self.storage_form.present(target,action,int(selected[0][3:]),item)

    def use_item(self,resource):
        selected=self.bag.selection()
        if not selected or selected[0] not in self.bag_map:return
        value=self.bag_map[selected[0]];state=self.app.snapshot
        try:
            if state.get('battle',{}).get('active'):
                owned=[u for u in owned_units(state) if f"{u['col']}:{u['row']}" not in state['battle'].get('commands',{})]
                if not owned:raise ValueError('本回合沒有尚未下令的可操作單位')
                cmd=food_command(state,owned[0],resource,value['item_id'],index=value['index'])
                cmd.update(battle_count=state['battle_count'],round=state['battle']['round'])
            else:
                context,actor=field_context(state);cmd=food_command(context,actor,resource,value['item_id'],field=True,index=value['index'])
                target=context['battle_units'][f"{cmd['target_col']}:{cmd['target_row']}"];cmd['npc_index']=target.get('npc_index',0)
            self.app.send(cmd)
        except (ValueError,KeyError) as exc:messagebox.showinfo('道具補給',str(exc),parent=self.window)
