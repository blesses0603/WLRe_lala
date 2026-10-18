"""Settings entry point, kept compatible with the original AutoPlay UI API.

The action editor, rule card and verified action catalogue live in focused
submodules. The existing imports from this module remain available.
"""
import copy
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from wlre.ui.window_layout import configure_dialog
from wlre.ui.layout import heading
from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.ui.recovery_ui import RecoveryPage
from wlre.ui.maintenance_ui import MaintenancePage
from wlre.ui.auto_battle.model import (
    NAMES, TARGETS, NOTICES, COMPARES, GROUPS, MISC_RULE_KEYS, RuleDraft, validate,
    action_label, confirmed_skill_entries, confirmed_action_label, supply_catalogue,
    action_entries, ACTION_IDS, ACTIONS, CAT, owned_units, skill_rows, field_context)
from wlre.ui.auto_battle.action_editor import ActionEditor
from wlre.ui.auto_battle.rule_card import RuleCard

class SettingsEditor:
    def __init__(self,app):
        self.settings_key=app.settings_identity()
        self.app=app;self.draft=RuleDraft(app.ai_settings);self.flags={};self.cards={};self.rootvars={};self.rule_views={}
        w=self.window=tk.Toplevel(app.root);w.title('自動戰鬥設定');configure_dialog(w,1080,720);w.resizable(False,False)
        box=ttk.Frame(w,padding=12);box.pack(fill='both',expand=True)
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
            ttk.Label(area,text='點選行動名稱編輯。優先序：陣亡 → 敵HP → 低HP → 低SP → 回合 → 循環 → 順序 → 普攻。',style='Muted.TLabel',wraplength=850).pack(fill='x',pady=(0,8))
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
        self.maintenance_page=MaintenancePage(tabs,self)
        tabs.add(self.maintenance_page,text='修理／整理')
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
        self.maintenance_page.render(self.draft.value['maintenance'])
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
        if hasattr(self,'maintenance_page'):value['maintenance']=self.maintenance_page.collect()
        return validate(value)
    def apply(self):
        try:
            if self.settings_key!=self.app.settings_identity():raise ValueError('帳號已變更，請重新開啟設定')
            if self.app.snapshot.get('maintenance',{}).get('pending') or self.app.snapshot.get('maintenance',{}).get('uncertain'):
                raise ValueError('請先等待戰後修理／整理確認；結果未確認時需重新登入同步')
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
