"""One rule card of the unsaved AutoPlay settings draft."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from wlre.ui.theme import group as LabelFrame
from wlre.ui.auto_battle.model import TARGETS, NOTICES, COMPARES, confirmed_action_label

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
