"""Live bag contents and every confirmed learned/equipment skill, with reasons."""
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.rounded_notebook import RoundedNotebook
from tkinter import ttk,messagebox
from wlre.services.items.combat_resources import CAT, skill_rows, available, heal_effects, item_name, food_command, learned_command, field_context
from wlre.services.battle.battle_commands import owned_units
from wlre.ui.crafting_browser import ItemIcons
from wlre.ui.bag_grid import BagGrid
from wlre.ui.room_storage_status import unlock_message, storage_sync_message, confirmed_view
from wlre.ui.layout import heading,scroll_table

class ResourceView:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root);self.window.title('包包與角色／夥伴特技');self.window._no_glass_border=True;configure_dialog(self.window,1040,700)
        self.signature=None;self.skill_map={};self.bag_map={};self.bag_images={};self.icons=ItemIcons(self.window)
        self.window.bind('<Destroy>',self.destroyed,add='+')
        header=ttk.Frame(self.window,padding=(12,10,12,0));header.pack(fill='x')
        heading(header,'包包與特技','搜尋已同步物品與特技，選取後使用下方操作。')
        bar=ttk.Frame(self.window,padding=(12,0,12,8));bar.pack(fill='x')
        ttk.Label(bar,text='搜尋名稱／ID').pack(side='left')
        self.query=tk.StringVar();ttk.Entry(bar,textvariable=self.query,width=25).pack(side='left',padx=6)
        ttk.Button(bar,text='更新顯示',command=self.refresh).pack(side='left')
        self.status=tk.StringVar();ttk.Label(self.window,textvariable=self.status,wraplength=970).pack(fill='x',padx=10)
        # Keep a single thematic surface, no extra coloured outer margin.
        tabs=RoundedNotebook(self.window);tabs.pack(fill='both',expand=True,padx=4,pady=(0,4))
        bag=ttk.Frame(tabs);remote=ttk.Frame(tabs);skills=ttk.Frame(tabs)
        tabs.add(bag,text='實際包包')
        tabs.add(remote,text='超空間袋')
        tabs.add(skills,text='全部已確認特技')
        # Keep the current v0.5.0 window and skill table; only replace bag content.
        self.bag=BagGrid(bag,self.icons,self.use_item)
        self.bag.pack(fill='both',expand=True)
        self.skills=self.table(skills,('actor','id','name','level','kind','sp','status','source'),('角色／夥伴','ID','特技','等級','分類','消耗SP','基礎條件／不可用原因','資料來源'))
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
        ttk.Label(remote_head,text='S62 唯讀同步',style='Muted.TLabel').pack(side='right')
        ttk.Label(remote_body,textvariable=self.remote_status,style='Muted.TLabel',wraplength=910).pack(anchor='w',pady=(0,2))
        ttk.Label(remote_body,textvariable=self.remote_unlock_status,style='Muted.TLabel',wraplength=910).pack(anchor='w',pady=(0,2))
        storage_tabs=RoundedNotebook(remote_body)
        storage_tabs.pack(fill='both',expand=True,pady=(2,0))
        garage_page=ttk.Frame(storage_tabs);materials_page=ttk.Frame(storage_tabs)
        storage_tabs.add(garage_page,text='儲藏室')
        storage_tabs.add(materials_page,text='雜物櫃')
        self.remote_garage=BagGrid(garage_page,self.icons,lambda resource:None,
                                   read_only=True,title='儲藏室物品',compact=True)
        self.remote_materials=BagGrid(materials_page,self.icons,lambda resource:None,
                                      read_only=True,title='雜物櫃物品',compact=True)
        self.remote_garage.pack(fill='both',expand=True)
        self.remote_materials.pack(fill='both',expand=True)
        ttk.Button(skills,text='施放選取特技（戰鬥內）',command=self.use_skill).pack(anchor='w',pady=5)
        ttk.Label(skills,text='搜尋列出已學、裝備附帶、生活與被動；可施放與否會再核對目前回合、武器、資源及目標。',wraplength=960).pack(anchor='w')
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

    def actors(self,state):
        if state.get('battle',{}).get('active'):return owned_units(state,False)
        k=state.get('knowledge',{});context,role=field_context(state);role.update(col=0,row=0)
        actors=[role] if state.get('player',{}).get('role_id') else []
        for profile in k.get('companions',{}).values():
            actors.append({'col':0,'row':0,'pid':profile['npc_id'],'master_id':state['player']['role_id'],
                'npc_index':profile['index'],'name':CAT['npcs'].get(str(profile['npc_id']),{}).get('name','夥伴'),
                'equips':profile.get('equips',[]),**profile.get('stats',{})})
        return actors

    def set_state(self,state):
        signature=(str(state.get('inventory')),str(state.get('knowledge')),str(state.get('battle_units')),state.get('battle',{}).get('active'),self.query.get(),state.get('room_storage',{}).get('revision'))
        if signature==self.signature:return
        self.signature=signature;query=self.query.get().casefold();inv=state.get('inventory',{});k=state.get('knowledge',{})
        self.status.set(f"包包：{'已同步' if inv.get('ready') else '等待S23-5'}｜{'數量有效' if inv.get('reliable') else '尚不可自動取用'}｜{len(inv.get('items',{}))}格；角色技能：{'已同步' if k.get('player',{}).get('ready') else '等待S5-3'}；夥伴資料：{len(k.get('companions',{}))}隻。更新顯示不會發送未驗證的查包封包。")
        selected_bag=self.bag.selection();selected_skill=self.skills.selection()
        self.skills.delete(*self.skills.get_children());self.skill_map={}
        self.bag_map=self.bag.render(inv,query)
        self.update_remote_status(state)
        for actor in self.actors(state):
            label=('角色 ' if actor['pid']==state.get('player',{}).get('role_id') else f"夥伴#{actor.get('npc_index')} ")+actor.get('name','')
            for row in skill_rows(state,actor):
                if query and query not in (label+row['name']+str(row['id'])).casefold():continue
                iid=f"skill{actor['pid']}_{actor.get('npc_index',0)}_{row['id']}"
                self.skill_map[iid]=(actor,row['id'])
                self.skills.insert('','end',iid=iid,values=(label,row['id'],row['name'],row['level'],row['category'],row['sp'],'；'.join(row['reasons']) or '基礎條件可用',row['source']))
        if selected_bag and selected_bag[0] in self.bag_map and not self.bag.selection():self.bag.selection_set(selected_bag[0])
        if selected_skill and selected_skill[0] in self.skill_map:self.skills.selection_set(selected_skill[0])

    def update_remote_status(self,state):
        inventory = state.get('inventory', {})
        storage = state.get('room_storage', {})
        self.remote_unlock_status.set(unlock_message(inventory))
        self.remote_status.set(storage_sync_message(storage))
        self.remote_garage.render(confirmed_view(storage.get('garage', {})), self.query.get())
        self.remote_materials.render(confirmed_view(storage.get('materials', {})), self.query.get())

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

    def use_skill(self):
        selected=self.skills.selection()
        if not selected:return
        actor,sid=self.skill_map[selected[0]];state=self.app.snapshot
        try:
            if not state.get('battle',{}).get('active'):raise ValueError('請在可下令的戰鬥回合施放特技')
            target=self.app.priority_target
            data=CAT['skills'].get(str(sid),{})
            if data.get('TargetKind') in (1,3,5):target=None
            cmd=learned_command(state,actor,sid,target)
            cmd.update(battle_count=state['battle_count'],round=state['battle']['round'])
            self.app.send(cmd)
        except (ValueError,KeyError) as exc:messagebox.showinfo('特技',str(exc),parent=self.window)
