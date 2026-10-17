"""Complete form editor for every supported AutoPlay rule; JSON is an exchange format."""
import copy
import json
from functools import lru_cache
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.layout import heading
import os
from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.ui.theme import group as LabelFrame
from tkinter import ttk,messagebox,filedialog
from wlre.services.battle.auto_battle import validate, ACTION_IDS
from wlre.services.battle.battle_commands import ACTIONS, owned_units
from wlre.services.items.combat_resources import CAT, skill_rows, field_context
from wlre.ui.recovery_ui import RecoveryPage

NAMES={0:'略過此格',**{sid:ACTIONS[mode] for sid,mode in ACTION_IDS.items()}}
TARGETS={1:'最低HP',2:'屬性優先',3:'最高HP'}
NOTICES={1:'同方任一單位',2:'本機角色',3:'出戰夥伴'}
COMPARES={1:'大於',2:'小於'}
GROUPS=(('bDeadAction','deadAction','同方陣亡',1),('bEnemyHPAction','enemyHpAction','敵HP條件',1),
        ('bLowHpAction','lowHpAction','低HP條件',1),('bLowSpAction','lowSpAction','低SP條件',1),
        ('bRoundAction','roundAction','指定回合',3),('bRepeatAction','repeatAction','循環行動',5),
        ('bOrderAction','orderAction','順序行動',2))

def action_label(row):
    sid=row['id']
    if sid in NAMES:return NAMES[sid]
    source=CAT['items'] if row['kind']==2 else CAT['skills']
    return f"{source.get(str(sid),{}).get('name','未知')} ({sid})"


def confirmed_skill_entries(state,who):
    """Only this profile's confirmed skills; never search the full catalogue."""
    if state.get('battle',{}).get('active'):
        actors=owned_units(state,False)
    else:
        context,_=field_context(state)
        actors=list(context['battle_units'].values())
    pid=state.get('player',{}).get('role_id');known={}
    if not pid:return []
    for actor in actors:
        if (actor['pid']==pid)!=(who=='player'):continue
        for skill in skill_rows(state,actor):
            source='裝備附帶' if skill['source']=='目前裝備附帶' else '已學'
            known.setdefault(skill['id'],[]).append(f"{actor.get('name','夥伴')} {source} Lv{skill['level']}")
    return [(sid,f"{CAT['skills'].get(str(sid),{}).get('name',f'技能{sid}')} ({sid})｜"+'／'.join(labels))
            for sid,labels in sorted(known.items())]

def confirmed_action_label(row,state,who):
    if row['kind']==1 and row['id'] not in NAMES:
        if row['id'] not in dict(confirmed_skill_entries(state,who)):
            return '特技未學會或尚未同步，請重新選擇'
    return action_label(row)

@lru_cache(maxsize=1)
def supply_catalogue():
    return tuple((int(sid),value['name']) for sid,value in CAT['items'].items() if value['kind'] in (23,32))

def action_entries(state,who,item):
    special=(0,-2,-3) if item else (0,-1,10001,60021,60041,10008)
    entries=[(sid,NAMES[sid]) for sid in special]
    if item:
        counts={}
        for value in state.get('inventory',{}).get('items',{}).values():
            counts[value['item_id']]=counts.get(value['item_id'],0)+value['count']
        data=[(sid,f"{name} ({sid})｜持有 {counts.get(sid,0)}") for sid,name in supply_catalogue()]
        data.sort(key=lambda row:(row[0] not in counts,row[0]))
    else:data=[entry for entry in confirmed_skill_entries(state,who) if entry[0] not in special]
    return entries+data

class RuleDraft:
    """A detached draft: cancel/import/export never silently applies settings."""
    def __init__(self,value):self.value=validate(value)
    def rows(self,who):
        p=self.value['profiles'][who]
        for flag,key,label,count in GROUPS:
            for i in range(count):
                yield key,i,label,p[flag],p[key][i] if count>1 else p[key]
    def set_action(self,who,key,index,row):
        value=copy.deepcopy(self.value);profile=value['profiles'][who]
        if isinstance(profile[key],list):profile[key][index]=copy.deepcopy(row)
        else:profile[key]=copy.deepcopy(row)
        self.value=validate(value)
    def swap(self,who,key,index,direction):
        values=self.value['profiles'][who][key];other=index+direction
        if not isinstance(values,list) or not 0<=other<len(values):return False
        values[index],values[other]=values[other],values[index];return True

class ActionEditor:
    def __init__(self,parent,row,snapshot,who,commit):
        self.original=copy.deepcopy(row);self.commit=commit;self.snapshot_source=snapshot if callable(snapshot) else lambda:snapshot;self.snapshot=self.snapshot_source();self.who=who
        self.window=tk.Toplevel(parent);self.window.title('編輯行動與條件');configure_dialog(self.window,960,640);self.window.resizable(False,False)
        self.window.transient(parent);self.window.grab_set()
        box=ttk.Frame(self.window,padding=12);box.pack(fill='both',expand=True)
        heading(box,'編輯行動','先選擇行動，再核對目標與條件；儲存後返回規則草稿。')
        self.kind=tk.StringVar(value='包包道具' if row['kind']==2 else '技能／基本行動')
        ttk.Label(box,text='行動類型').pack(anchor='w')
        kind=ttk.Combobox(box,textvariable=self.kind,values=('技能／基本行動','包包道具'),state='readonly');kind.pack(fill='x')
        self.query=tk.StringVar();ttk.Label(box,text='搜尋名稱或ID（僅列出此單位已確認特技）').pack(anchor='w',pady=(8,0))
        ttk.Entry(box,textvariable=self.query).pack(fill='x')
        footer=ttk.Frame(box)
        footer.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Button(footer,text='儲存此行動',command=self.save).pack(side='right',padx=(6,0))
        ttk.Button(footer,text='取消',command=self.window.destroy).pack(side='right')
        body=ttk.Frame(box);body.pack(fill='both',expand=True,pady=6)
        body.columnconfigure(0,weight=1);body.columnconfigure(1,weight=0,minsize=270);body.rowconfigure(0,weight=1)
        area=ttk.Frame(body);area.grid(row=0,column=0,sticky='nsew',padx=(0,12))
        options=ttk.Frame(body,width=270);options.grid(row=0,column=1,sticky='nsew')
        self.list=tk.Listbox(area,exportselection=False,height=10,font=('Microsoft JhengHei UI' if os.name=='nt' else 'WenQuanYi Micro Hei',-14),selectborderwidth=2);self.list.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.list.yview);scroll.pack(side='right',fill='y');self.list.configure(yscrollcommand=scroll.set)
        self.chosen=row['id'];self.selection=tk.StringVar(value=confirmed_action_label(row,self.snapshot,who))
        ttk.Label(options,textvariable=self.selection,wraplength=260).pack(anchor='w')
        fields=ttk.Frame(options);fields.pack(fill='x',pady=6)
        self.target=tk.StringVar(value=TARGETS[row['target']]);self.next=tk.BooleanVar(value=row.get('bUseNextSkill',False));self.extra={}
        self.combo(fields,0,'目標排序',self.target,TARGETS.values())
        ttk.Checkbutton(fields,text='允許次階特技（僅技能）',variable=self.next).grid(row=1,column=0,columnspan=2,sticky='w',pady=4)
        r=2
        for key,label,mapping in (('notice','觀察對象',NOTICES),('compareKind','敵HP比較',COMPARES)):
            if key in row:
                var=tk.StringVar(value=mapping[row[key]]);self.extra[key]=(var,mapping);self.combo(fields,r,label,var,mapping.values());r+=1
        if 'value' in row:
            var=tk.StringVar(value=str(row['value']));self.extra['value']=(var,None)
            ttk.Label(fields,text='HP／SP門檻').grid(row=r,column=0,sticky='w');ttk.Entry(fields,textvariable=var,width=16).grid(row=r,column=1,sticky='w');r+=1
        ttk.Label(options,text='只列已學及裝備附帶特技。\nSP不足仍保留；0為略過。',wraplength=260).pack(anchor='w',pady=6)
        self._query_job=None;self._poll_job=None
        kind.bind('<<ComboboxSelected>>',self.change_kind);self.query.trace_add('write',self.search_changed)
        self.window.bind('<Destroy>',self.cleanup,add='+')
        self.list.bind('<<ListboxSelect>>',self.pick);self.populate();self.poll()
    @staticmethod
    def combo(parent,row,label,var,values):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
        ttk.Combobox(parent,textvariable=var,values=tuple(values),state='readonly',width=15).grid(row=row,column=1,sticky='w')
    def change_kind(self,*a):
        self.chosen=0;self.next.set(False);self.selection.set('略過此格');self.populate()
    def search_changed(self,*args):
        if self._query_job:self.window.after_cancel(self._query_job)
        self._query_job=self.window.after(120,self.populate)
    def populate(self):
        if getattr(self,'_query_job',None):self.window.after_cancel(self._query_job)
        self._query_job=None
        self.snapshot=self.snapshot_source()
        item=self.kind.get()=='包包道具';query=self.query.get().casefold()
        self._catalogue=action_entries(self.snapshot,self.who,item)
        self.entries=[entry for entry in self._catalogue if not query or query in entry[1].casefold() or query in str(entry[0])]
        self.list.delete(0,'end')
        if self.entries:self.list.insert('end',*(label for sid,label in self.entries))
        for i,(sid,label) in enumerate(self.entries):
            if sid==self.chosen:self.list.selection_set(i);self.list.see(i);break
    def poll(self):
        if self._poll_job:self.window.after_cancel(self._poll_job)
        self._poll_job=None
        if not self.window.winfo_exists():return
        latest=self.snapshot_source()
        item=self.kind.get()=='包包道具'
        if action_entries(latest,self.who,item)!=self._catalogue:
            self.populate()
            if not item:self.selection.set(confirmed_action_label({'kind':1,'id':self.chosen},self.snapshot,self.who))
        self._poll_job=self.window.after(500,self.poll)
    def cleanup(self,event):
        if event.widget is not self.window:return
        for job in (self._query_job,self._poll_job):
            if job:self.window.after_cancel(job)
        self._query_job=self._poll_job=None
    def pick(self,*a):
        selected=self.list.curselection()
        if selected:self.chosen,label=self.entries[selected[0]];self.selection.set(label)
    def save(self):
        try:
            if self.kind.get()!='包包道具' and self.chosen not in NAMES and self.chosen not in dict(confirmed_skill_entries(self.snapshot_source(),self.who)):
                raise ValueError('此單位尚未確認學會此特技，請從清單重新選擇。')
            row=copy.deepcopy(self.original);row.update(id=self.chosen,kind=2 if self.kind.get()=='包包道具' else 1,target=next(k for k,v in TARGETS.items() if v==self.target.get()))
            row['bUseNextSkill']=self.next.get()
            for key,(var,mapping) in self.extra.items():row[key]=next(k for k,v in mapping.items() if v==var.get()) if mapping else float(var.get())
            self.commit(row);self.window.destroy()
        except (ValueError,TypeError,KeyError) as exc:messagebox.showerror('行動設定',str(exc),parent=self.window)

MISC_RULE_KEYS=('lowHpAction','lowSpAction','enemyHpAction','deadAction')

class RuleCard:
    """One visible rule section; all values remain in the unsaved form."""
    def __init__(self,editor,parent,who,group,compact=False):
        self.editor=editor;self.who=who;self.flag,self.key,label,self.count=group
        title={'orderAction':'使用特定指令（預設普攻）','repeatAction':'循環使用指令','roundAction':'特定回合指令','lowHpAction':'HP低於設定數值時','lowSpAction':'SP低於設定數值時','enemyHpAction':'敵方HP條件','deadAction':'我方陣亡時'}[self.key]
        box=self.box=LabelFrame(parent,padding=(8,0,8,6));box.pack(fill='x',padx=2,pady=2)
        top=ttk.Frame(box);top.pack(fill='x')
        enabled=tk.BooleanVar();editor.flags[who,self.flag]=enabled
        ttk.Checkbutton(top,text=title,variable=enabled).pack(side='left')
        self.conditions={};self.controls=[]
        initial=editor.draft.value['profiles'][who][self.key]
        if self.count==1:
            if 'notice' in initial:
                var=tk.StringVar();self.conditions['notice']=(var,NOTICES)
                ttk.Combobox(top,textvariable=var,values=tuple(NOTICES.values()),state='readonly',width=14).pack(side='left',padx=8)
            if 'compareKind' in initial:
                var=tk.StringVar();self.conditions['compareKind']=(var,COMPARES)
                ttk.Combobox(top,textvariable=var,values=tuple(COMPARES.values()),state='readonly',width=6).pack(side='left',padx=8)
            if 'value' in initial:
                var=tk.StringVar();self.conditions['value']=(var,None)
                ttk.Button(top,text='−',width=3,command=lambda:self.step(-1)).pack(side='left',padx=(8,2))
                ttk.Entry(top,textvariable=var,width=9,justify='center').pack(side='left')
                ttk.Button(top,text='＋',width=3,command=lambda:self.step(1)).pack(side='left',padx=2)
        for i in range(self.count):
            line=ttk.Frame(box);line.pack(fill='x',pady=(4,0))
            label=f'第{i+1}順位' if self.key=='orderAction' else f'順序{i+1}' if self.key=='repeatAction' else f'第{i+1}回合' if self.key=='roundAction' else '使用指令'
            if not compact:ttk.Label(line,text=label,width=9).pack(side='left')
            mark=tk.StringVar();name=tk.StringVar();target=tk.StringVar();nextskill=tk.BooleanVar()
            ttk.Button(line,textvariable=mark,width=3 if compact else 4,command=lambda i=i:editor.edit(who,self.key,i)).pack(side='left',padx=6)
            ttk.Button(line,textvariable=name,width=20 if compact else 25,command=lambda i=i:editor.edit(who,self.key,i)).pack(side='left',padx=4)
            ttk.Button(line,text='清除',width=5,command=lambda i=i:editor.clear(who,self.key,i)).pack(side='right',padx=4)
            if self.count>1:
                ttk.Button(line,text='↓',width=3,command=lambda i=i:editor.move(who,self.key,i,1)).pack(side='right')
                ttk.Button(line,text='↑',width=3,command=lambda i=i:editor.move(who,self.key,i,-1)).pack(side='right')
            detail=line if compact else ttk.Frame(box)
            if not compact:detail.pack(fill='x',padx=(72,0),pady=(0,4))
            ttk.Label(detail,text='優先目標').pack(side='left',padx=(0,8))
            ttk.Combobox(detail,textvariable=target,values=tuple(TARGETS.values()),state='readonly',width=11).pack(side='left')
            nextbutton=ttk.Checkbutton(detail,text='次階特技' if compact else '允許下一階特技',variable=nextskill);nextbutton.pack(side='left',padx=12)
            self.controls.append({'mark':mark,'name':name,'target':target,'next':nextskill,'nextbutton':nextbutton})
        if self.key=='orderAction':ttk.Label(box,text='第一順位不可用才試第二順位；不是同回合連續施放兩次。').pack(anchor='w')
        if self.key=='repeatAction':ttk.Label(box,text='每回合輪用一格，只計入非空指令。').pack(anchor='w')
    def step(self,delta):
        var=self.conditions['value'][0]
        try:var.set(str(max(0,float(var.get())+delta)))
        except ValueError:messagebox.showerror('條件數值','請先輸入非負數值。',parent=self.editor.window)
    def render(self):
        value=self.editor.draft.value['profiles'][self.who][self.key]
        rows=value if self.count>1 else [value]
        for row,controls in zip(rows,self.controls):
            controls['mark'].set('＋' if row['id']==0 else '✓')
            controls['name'].set('點選空格以設定指令' if row['id']==0 else confirmed_action_label(row,self.editor.app.snapshot,self.who))
            controls['target'].set(TARGETS[row['target']]);controls['next'].set(row.get('bUseNextSkill',False))
            controls['nextbutton'].configure(state='disabled' if row['kind']==2 else 'normal')
        if self.count==1:
            for key,(var,mapping) in self.conditions.items():var.set(mapping[value[key]] if mapping else str(value[key]))
    def collect(self):
        original=self.editor.draft.value['profiles'][self.who][self.key]
        rows=copy.deepcopy(original if self.count>1 else [original])
        for row,c in zip(rows,self.controls):
            row['target']=next(k for k,v in TARGETS.items() if v==c['target'].get())
            if 'bUseNextSkill' in row or c['next'].get():row['bUseNextSkill']=bool(c['next'].get()) if row['kind']==1 else False
        if self.count==1:
            for key,(var,mapping) in self.conditions.items():rows[0][key]=next(k for k,v in mapping.items() if v==var.get()) if mapping else float(var.get())
        return rows if self.count>1 else rows[0]

class SettingsEditor:
    def __init__(self,app):
        self.settings_key=app.settings_identity()
        self.app=app;self.draft=RuleDraft(app.ai_settings);self.flags={};self.cards={};self.rootvars={};self.rule_views={}
        w=self.window=tk.Toplevel(app.root);w.title('自動戰鬥設定');configure_dialog(w,1080,720);w.resizable(False,False)
        box=ttk.Frame(w,padding=12);box.pack(fill='both',expand=True)
        ttk.Label(box,text='左側選擇規則，點行動名稱編輯。優先序：陣亡 → 敵HP → 低HP → 低SP → 回合 → 循環 → 順序 → 普攻。',wraplength=900).pack(anchor='w',pady=(0,8))
        heading(box,'自動戰鬥設定','角色與夥伴規則、補給及停止條件；修改會先保留在草稿。')
        tabs=self.tabs=RoundedNotebook(box);tabs.pack(fill='both',expand=True)
        display=('orderAction','repeatAction','roundAction','misc')
        for who,title in (('player','角色規則'),('partner','夥伴規則')):
            panel=ttk.Frame(tabs);tabs.add(panel,text=title)
            menu=tk.Listbox(panel,exportselection=False,width=10,height=8,activestyle='none',font=('Microsoft JhengHei UI' if os.name=='nt' else 'WenQuanYi Micro Hei',-14),selectborderwidth=2)
            menu.pack(side='left',fill='y',padx=(0,10))
            for label in ('順序行動','循環行動','指定回合','雜項設定'):menu.insert('end',label)
            menu.selection_set(0)
            area=ttk.Frame(panel);area.pack(side='left',fill='both',expand=True)
            inside=ttk.Frame(area);inside.pack(fill='both',expand=True)
            self.rule_views[who]={'menu':menu,'inside':inside,'display':display,'selected':None}
            menu.bind('<<ListboxSelect>>',lambda e,who=who:self.choose_rule(who))
            self.show_rule(who,display[0])
        self.rootvars={'field_heal':tk.BooleanVar()}
        self.recovery_pages={}
        self.recovery_tab=ttk.Frame(tabs,padding=6);tabs.add(self.recovery_tab,text='補給設定')
        self.recovery_tab.columnconfigure(0,weight=1,uniform='recovery')
        self.recovery_tab.columnconfigure(1,weight=1,uniform='recovery')
        self.recovery_tab.rowconfigure(1,weight=1)
        ttk.Checkbutton(self.recovery_tab,text='啟用戰後補給（HP／SP 共用開關）',variable=self.rootvars['field_heal']).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,6))
        for column,resource in enumerate(('hp','sp')):
            page=RecoveryPage(self.recovery_tab,self,resource,self.rootvars['field_heal'],compact=True)
            page.grid(row=1,column=column,sticky='nsew',padx=(0,4) if column==0 else (4,0))
            self.recovery_pages[resource]=page
        general=ttk.Frame(tabs,padding=16);tabs.add(general,text='停止條件')
        for key,label in [('bPlayerDieCloseAI','角色陣亡時停止AI與徘徊'),('bNPCDieCloseAI','夥伴陣亡時停止AI與徘徊')]:
            v=tk.BooleanVar();self.rootvars[key]=v;ttk.Checkbutton(general,text=label,variable=v).pack(anchor='w',pady=8)
        self.note=tk.StringVar(value='變更先留在草稿；「套用全部設定」會儲存到目前帳號，不會自動啟動 AI。')
        note_label=ttk.Label(box,textvariable=self.note,wraplength=900)
        note_label.pack(side='bottom',anchor='w',pady=8)
        buttons=ttk.Frame(box);buttons.pack(side='bottom',fill='x')
        for label,fn in [('載入JSON',self.load),('匯出目前設定',self.export)]:ttk.Button(buttons,text=label,command=fn).pack(side='left',padx=(0,6))
        ttk.Button(buttons,text='套用全部設定',command=self.apply).pack(side='right',padx=(6,0))
        ttk.Button(buttons,text='取消',command=w.destroy).pack(side='right');self.render()
        note_label.pack_forget();note_label.pack(side='bottom',anchor='w',pady=8)
        tabs.pack_forget();tabs.pack(fill='both',expand=True)
    def show_rule(self,who,key):
        view=self.rule_views[who];previous=view['selected']
        if previous==key:return
        for card_key in tuple(self.cards):
            if card_key[0]==who:
                card=self.cards.pop(card_key);self.flags.pop((who,card.flag),None);card.box.destroy()
        keys=MISC_RULE_KEYS if key=='misc' else (key,)
        for rule_key in keys:
            group=next(group for group in GROUPS if group[1]==rule_key)
            card=RuleCard(self,view['inside'],who,group,compact=key=='misc');self.cards[who,rule_key]=card
            self.flags[who,card.flag].set(self.draft.value['profiles'][who][card.flag]);card.render()
        view['selected']=key
    def choose_rule(self,who):
        view=self.rule_views[who];selection=view['menu'].curselection()
        if not selection:return
        key=view['display'][selection[0]]
        if key==view['selected']:return
        try:self.draft=RuleDraft(self.collect())
        except (ValueError,TypeError,KeyError,tk.TclError) as exc:
            view['menu'].selection_clear(0,'end');view['menu'].selection_set(view['display'].index(view['selected']))
            messagebox.showerror('AI設定',str(exc),parent=self.window);return
        self.show_rule(who,key)
    def render(self):
        for (who,flag),v in self.flags.items():v.set(self.draft.value['profiles'][who][flag])
        for key,v in self.rootvars.items():v.set(self.draft.value[key])
        for card in self.cards.values():card.render()
        for resource,page in self.recovery_pages.items():page.render(self.draft.value['recovery'][resource])
    def edit(self,who,key,index):
        try:self.draft=RuleDraft(self.collect())
        except (OSError,ValueError,TypeError,KeyError,tk.TclError) as exc:messagebox.showerror('AI設定',str(exc),parent=self.window);return
        data=self.draft.value['profiles'][who][key];row=data[index] if isinstance(data,list) else data
        def commit(value):self.draft.set_action(who,key,index,value);self.cards[who,key].render()
        ActionEditor(self.window,row,lambda:self.app.snapshot,who,commit)
    def clear(self,who,key,index):
        try:
            self.draft=RuleDraft(self.collect());data=self.draft.value['profiles'][who][key]
            row=copy.deepcopy(data[index] if isinstance(data,list) else data);row.update(id=0,kind=1,bUseNextSkill=False)
            self.draft.set_action(who,key,index,row);self.cards[who,key].render()
        except (OSError,ValueError,TypeError,KeyError,tk.TclError) as exc:messagebox.showerror('AI設定',str(exc),parent=self.window)
    def move(self,who,key,index,direction):
        try:
            self.draft=RuleDraft(self.collect())
            if self.draft.swap(who,key,index,direction):self.cards[who,key].render()
        except (OSError,ValueError,TypeError,KeyError,tk.TclError) as exc:messagebox.showerror('AI設定',str(exc),parent=self.window)
    def collect(self):
        value=copy.deepcopy(self.draft.value)
        for (who,flag),v in self.flags.items():value['profiles'][who][flag]=v.get()
        for (who,key),card in self.cards.items():value['profiles'][who][key]=card.collect()
        for key,v in self.rootvars.items():value[key]=int(v.get()) if key.endswith('_percent') else v.get()
        if hasattr(self,'recovery_pages'):
            value['recovery']={resource:page.collect() for resource,page in self.recovery_pages.items()}
            for resource in ('hp','sp'):value['field_'+resource+'_percent']=value['recovery'][resource]['player_percent']
        return validate(value)
    def apply(self):
        try:
            if self.settings_key!=self.app.settings_identity():raise ValueError('帳號已變更，請重新開啟設定')
            value=self.collect();self.app.persist_ai_settings(value);self.app.ai_settings=value
            self.app.party_guard_panel.set_config(value['party_guard'])
            self.app.party_guard_panel.update_state(self.app.snapshot)
            if self.app.snapshot.get('auto_battle',{}).get('enabled'):self.app.send({'type':'start_auto_battle','settings':value})
            self.window.destroy()
        except (OSError,ValueError,TypeError,KeyError,tk.TclError) as exc:messagebox.showerror('AI設定',str(exc),parent=self.window)
    def load(self):
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('AI設定','*.json')])
        if not path:return
        try:
            with open(path,encoding='utf-8-sig') as f:value=validate(json.load(f))
            self.draft=RuleDraft(value);self.render();self.note.set('已載入草稿，可繼續修改；按套用全部設定才生效。')
        except (OSError,ValueError,TypeError,KeyError) as exc:messagebox.showerror('AI設定',str(exc),parent=self.window)
    def export(self):
        try:value=self.collect()
        except (OSError,ValueError,TypeError,KeyError,tk.TclError) as exc:messagebox.showerror('AI設定',str(exc),parent=self.window);return
        path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.json',filetypes=[('AI設定','*.json')])
        if not path:return
        try:
            with open(path,'w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
            self.note.set('已匯出畫面中的目前設定；尚未套用的草稿仍未啟用。')
        except OSError as exc:messagebox.showerror('AI設定',str(exc),parent=self.window)

def open_settings(app):return SettingsEditor(app)
