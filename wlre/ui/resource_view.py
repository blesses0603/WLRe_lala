"""Live bag contents and every confirmed learned/equipment skill, with reasons."""
import tkinter as tk
from wlre.ui.rounded_notebook import RoundedNotebook
from tkinter import ttk,messagebox
from wlre.services.items.combat_resources import CAT, skill_rows, available, heal_effects, item_name, food_command, learned_command, field_context
from wlre.services.battle.battle_commands import owned_units
from wlre.ui.crafting_browser import ItemIcons

class ResourceView:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root);self.window.title('包包與角色／夥伴特技');self.window.geometry('1000x660')
        self.signature=None;self.skill_map={};self.bag_map={};self.bag_images={};self.icons=ItemIcons(self.window)
        self.window.bind('<Destroy>',self.destroyed,add='+')
        bar=ttk.Frame(self.window,padding=10);bar.pack(fill='x')
        ttk.Label(bar,text='搜尋名稱／ID').pack(side='left')
        self.query=tk.StringVar();ttk.Entry(bar,textvariable=self.query,width=25).pack(side='left',padx=6)
        ttk.Button(bar,text='更新顯示',command=self.refresh).pack(side='left')
        self.status=tk.StringVar();ttk.Label(self.window,textvariable=self.status,wraplength=970).pack(fill='x',padx=10)
        tabs=RoundedNotebook(self.window);tabs.pack(fill='both',expand=True,padx=10,pady=10)
        bag=ttk.Frame(tabs);skills=ttk.Frame(tabs);tabs.add(bag,text='實際包包');tabs.add(skills,text='全部已確認特技')
        self.bag=self.table(bag,('index','id','name','count','reserved','available','effect'),('索引','ID','名稱','持有','待扣','可用','回復效果'))
        self.bag.configure(show='tree headings');self.bag.heading('#0',text='圖示');self.bag.column('#0',width=48,minwidth=48,stretch=False)
        self.skills=self.table(skills,('actor','id','name','level','kind','sp','status','source'),('角色／夥伴','ID','特技','等級','分類','消耗SP','基礎條件／不可用原因','資料來源'))
        actions=ttk.Frame(bag);actions.pack(fill='x',pady=5)
        ttk.Button(actions,text='使用選取道具補HP',command=lambda:self.use_item('hp')).pack(side='left',padx=4)
        ttk.Button(actions,text='使用選取道具補SP',command=lambda:self.use_item('sp')).pack(side='left',padx=4)
        ttk.Label(actions,text='只使用所選包包索引；戰鬥內消耗本回合行動。').pack(side='left',padx=8)
        ttk.Button(skills,text='施放選取特技（戰鬥內）',command=self.use_skill).pack(anchor='w',pady=5)
        ttk.Label(skills,text='搜尋列出已學、裝備附帶、生活與被動；可施放與否會再核對目前回合、武器、資源及目標。',wraplength=960).pack(anchor='w')
        self.query.trace_add('write',lambda *a:self.refresh())
        self.set_state(app.snapshot)

    def destroyed(self,event):
        if event.widget is self.window:self.icons.close();self.bag_images.clear()

    @staticmethod
    def table(parent,columns,labels):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
        for c,label in zip(columns,labels):
            tree.heading(c,text=label);tree.column(c,width=170 if c in ('name','status','actor') else 75,minwidth=45)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);scroll.pack(side='right',fill='y')
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);horizontal.pack(side='bottom',fill='x')
        tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set);tree.pack(fill='both',expand=True)
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
        signature=(str(state.get('inventory')),str(state.get('knowledge')),str(state.get('battle_units')),state.get('battle',{}).get('active'),self.query.get())
        if signature==self.signature:return
        self.signature=signature;query=self.query.get().casefold();inv=state.get('inventory',{});k=state.get('knowledge',{})
        self.status.set(f"包包：{'已同步' if inv.get('ready') else '等待S23-5'}｜{'數量有效' if inv.get('reliable') else '尚不可自動取用'}｜{len(inv.get('items',{}))}格；角色技能：{'已同步' if k.get('player',{}).get('ready') else '等待S5-3'}；夥伴資料：{len(k.get('companions',{}))}隻。更新顯示不會發送未驗證的查包封包。")
        selected_bag=self.bag.selection();selected_skill=self.skills.selection()
        self.bag.delete(*self.bag.get_children());self.skills.delete(*self.skills.get_children());self.bag_map={};self.skill_map={};self.bag_images={}
        for index,value in sorted(inv.get('items',{}).items(),key=lambda x:int(x[0])):
            name=item_name(value['item_id'])
            if query and query not in (name+str(value['item_id'])).casefold():continue
            effect=' / '.join(f'{a.upper()} +{b}' for a,b in heal_effects(value['item_id']).items())
            iid='bag'+index;self.bag_map[iid]=value
            image=self.icons.get(value['item_id'],24);self.bag_images[iid]=image
            self.bag.insert('','end',iid=iid,image=image,values=(index,value['item_id'],name,value['count'],inv.get('reserved',{}).get(index,0),available(inv,index),effect))
        for actor in self.actors(state):
            label=('角色 ' if actor['pid']==state.get('player',{}).get('role_id') else f"夥伴#{actor.get('npc_index')} ")+actor.get('name','')
            for row in skill_rows(state,actor):
                if query and query not in (label+row['name']+str(row['id'])).casefold():continue
                iid=f"skill{actor['pid']}_{actor.get('npc_index',0)}_{row['id']}"
                self.skill_map[iid]=(actor,row['id'])
                self.skills.insert('','end',iid=iid,values=(label,row['id'],row['name'],row['level'],row['category'],row['sp'],'；'.join(row['reasons']) or '基礎條件可用',row['source']))
        if selected_bag and selected_bag[0] in self.bag_map:self.bag.selection_set(selected_bag[0])
        if selected_skill and selected_skill[0] in self.skill_map:self.skills.selection_set(selected_skill[0])

    def use_item(self,resource):
        selected=self.bag.selection()
        if not selected:return
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
