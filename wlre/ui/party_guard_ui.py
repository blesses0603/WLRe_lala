"""Compact required-party editor directly under the Lua AI controls."""
import tkinter as tk
from tkinter import ttk,messagebox
from wlre.ui.theme import GlassGroup as LabelFrame
from wlre.services.battle import party_guard


class PartyGuardPanel(LabelFrame):
    def __init__(self,parent,app):
        super().__init__(parent,text='必要隊員名單',padding=8)
        self.app=app;self.choices={};self.people={};self.combos=[];self.labels=[]
        self.enabled=tk.BooleanVar()
        self.note=tk.StringVar(value='留白不指定；選擇名稱或輸入 ID，儲存後啟動 AI。')
        for col in (0,1):self.columnconfigure(col,weight=1,uniform='members')
        ttk.Checkbutton(self,text='名單未到齊時，遇戰自動逃跑',variable=self.enabled).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,3))
        for index in range(4):
            cell=ttk.Frame(self)
            cell.grid(row=index//2+1,column=index%2,sticky='ew',padx=(0,6) if index%2==0 else (6,0),pady=2)
            cell.columnconfigure(1,weight=1)
            ttk.Label(cell,text=str(index+1)).grid(row=0,column=0,padx=(0,4))
            combo=ttk.Combobox(cell,width=15)
            combo.grid(row=0,column=1,sticky='ew')
            label=ttk.Label(cell,text='未指定',width=6,anchor='center')
            label.grid(row=0,column=2,padx=(4,0))
            combo.bind('<<ComboboxSelected>>',lambda e:self.show_draft())
            combo.bind('<KeyRelease>',lambda e:self.show_draft())
            self.combos.append(combo);self.labels.append(label)
        buttons=ttk.Frame(self);buttons.grid(row=3,column=0,columnspan=2,sticky='ew',pady=(4,2))
        ttk.Button(buttons,text='帶入目前隊伍',command=self.use_team).pack(side='left')
        ttk.Button(buttons,text='清空',command=self.clear).pack(side='left',padx=4)
        ttk.Button(buttons,text='儲存並套用',command=self.apply).pack(side='right')
        note=ttk.Label(self,textvariable=self.note,wraplength=560)
        note.grid(row=4,column=0,columnspan=2,sticky='ew')
        note.bind('<Configure>',lambda e:note.configure(wraplength=max(1,e.width)))
        self.applied_status=ttk.Label(self,text='',style='Muted.TLabel',wraplength=560)
        self.applied_status.grid(row=5,column=0,columnspan=2,sticky='ew',pady=(2,0))
        self.applied_status.bind('<Configure>',lambda e:self.applied_status.configure(wraplength=max(1,e.width)))
        self.set_config(app.ai_settings['party_guard'])

    def set_config(self,config):
        self.enabled.set(config['enabled'])
        for i,combo in enumerate(self.combos):
            member=config['members'][i] if i<len(config['members']) else None
            label=f"{member['name']} ({member['role_id']})" if member else ''
            if member:self.choices[label]=dict(member)
            combo.set(label)
        self.show_draft()

    def resolve(self,text):
        raw=text.strip()
        if not raw:return None
        if raw in self.choices:return dict(self.choices[raw])
        if raw.isascii() and raw.isdigit():
            rid=int(raw)
            return {'role_id':rid,'name':self.people.get(rid,str(rid))}
        matches=[{'role_id':rid,'name':name} for rid,name in self.people.items() if name==raw]
        if len(matches)!=1:
            raise ValueError('名稱尚未取得或有同名角色，請選取下拉選項或輸入角色 ID：'+raw)
        return matches[0]

    def collect(self):
        members=[m for combo in self.combos if (m:=self.resolve(combo.get())) is not None]
        return party_guard.validate({'enabled':self.enabled.get(),'members':members})

    def show_draft(self):
        state=self.app.snapshot;present=party_guard.present_ids(state)
        connected=bool(state.get('player',{}).get('role_id'))
        for combo,label in zip(self.combos,self.labels):
            try:member=self.resolve(combo.get())
            except ValueError:label.configure(text='待確認');continue
            label.configure(text='未指定' if member is None else '待同步' if not connected else '在隊' if member['role_id'] in present else '缺席')

    def update_state(self,state):
        people={}
        for person in [state.get('player',{}),*state.get('party',{}).get('nearby',{}).values(),*state.get('guild',{}).get('members',{}).values()]:
            rid=person.get('role_id');name=person.get('name')
            if type(rid) is int and name:people[rid]=name
        book=getattr(getattr(self.app,'chat_panel',None),'names',None)
        if book:
            for (server,rid),name in book.names.items():
                if server is None:people.setdefault(rid,name)
        self.people=people
        config=self.app.ai_settings['party_guard']
        candidates={f'{name} ({rid})':{'role_id':rid,'name':name} for rid,name in sorted(people.items(),key=lambda p:(p[1],p[0]))}
        for member in config['members']:
            label=f"{member['name']} ({member['role_id']})";candidates.setdefault(label,dict(member))
        # Retain only currently displayed draft selections in addition to known names.
        for combo in self.combos:
            label=combo.get()
            if label in self.choices:candidates.setdefault(label,self.choices[label])
        if candidates!=self.choices:
            self.choices=candidates
            values=['',*candidates]
            for combo in self.combos:combo.configure(values=values)
        self.show_draft()
        if not config['enabled']:text='已套用：缺員逃跑關閉'
        elif not state.get('player',{}).get('role_id'):text='已套用：等待登入後同步隊伍'
        else:
            absent=party_guard.missing(state,config)
            text=f'已套用：尚缺 {len(absent)} 位必要隊員' if absent else '已套用：必要隊員已到齊'
        if config['enabled'] and not state.get('auto_battle',{}).get('enabled'):text+='（AI 未啟動）'
        self.applied_status.configure(text=text)

    def use_team(self):
        state=self.app.snapshot
        if not state.get('player',{}).get('role_id'):
            messagebox.showinfo('必要隊員名單','請先登入並同步隊伍。',parent=self.app.root);return
        ids=sorted(party_guard.present_ids(state))
        self.set_config({'enabled':self.enabled.get(),'members':[{'role_id':rid,'name':self.people.get(rid,str(rid))} for rid in ids]})
        self.note.set('已帶入目前隊伍；按「儲存並套用」生效。')

    def clear(self):
        for combo in self.combos:combo.set('')
        self.enabled.set(False);self.show_draft()
        self.note.set('已清空草稿；按「儲存並套用」生效。')

    def apply(self):
        try:
            config=self.collect()
            self.app.persist_ai_settings({**self.app.ai_settings,'party_guard':config})
        except (OSError,ValueError,TypeError) as exc:
            messagebox.showerror('必要隊員名單',str(exc),parent=self.app.root);return
        self.app.ai_settings['party_guard']=config
        self.set_config(config)
        if self.app.snapshot.get('auto_battle',{}).get('enabled'):
            self.app.send({'type':'set_party_guard','settings':config})
        self.note.set('已儲存並套用；空白欄位不列入判斷。')
        self.update_state(self.app.snapshot)
