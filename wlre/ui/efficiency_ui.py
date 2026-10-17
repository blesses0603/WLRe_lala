"""Compact overview statistics; only changed values repaint, timer is 1 Hz."""
import time
import tkinter as tk
from tkinter import ttk
from wlre.core.efficiency import rates, progress, forecast, STAGES

class EfficiencyPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=8);self.app=app;self.state={};self.signature=None;self.labels={};self.selected=tk.StringVar();self.unit=tk.StringVar(value='分')
        top=ttk.Frame(self);top.pack(fill='x')
        ttk.Label(top,text='經驗效率',style='Heading.TLabel').pack(side='left')
        ttk.Button(top,text='重設統計',command=self.reset).pack(side='right',padx=4)
        select=ttk.Frame(self);select.pack(fill='x',pady=(5,3))
        ttk.Label(select,text='統計對象').pack(side='left')
        self.choice=ttk.Combobox(select,textvariable=self.selected,state='readonly',width=24);self.choice.pack(side='left',padx=5);self.choice.bind('<<ComboboxSelected>>',lambda e:self.render(force=True))
        ttk.Label(select,text='效率單位').pack(side='left',padx=(10,3))
        unit=ttk.Combobox(select,textvariable=self.unit,state='readonly',values=['天','時','分'],width=4);unit.pack(side='left');unit.bind('<<ComboboxSelected>>',lambda e:self.render(force=True))
        self.info=tk.StringVar(value='等待登入角色與經驗資料');ttk.Label(self,textvariable=self.info,wraplength=620).pack(fill='x',pady=3)
        self.total=tk.StringVar(value='首場作基準，從第二個有效樣本計算效率');ttk.Label(self,textvariable=self.total,style='Muted.TLabel',wraplength=620).pack(fill='x')
        self.progress=ttk.Progressbar(self,maximum=100);self.progress.pack(fill='x',pady=5)
        self.table=ttk.Treeview(self,columns=['mode','speed','next','target'],show='headings',height=3,selectmode='none')
        for key,title,width in [('mode','統計範圍',116),('speed','經驗／分',144),('next','升級倒數',158),('target','一轉190倒數',178)]:
            self.table.heading(key,text=title);self.table.column(key,width=width,minwidth=60,anchor='center')
        self.table.pack(fill='x')
        for key in ('all','ten','thirty'):self.table.insert('','end',iid=key,values=('—',)*4)
        self.note=tk.StringVar(value='只統計本機角色與已確認的所屬夥伴／坐騎，首場作基準。')
        ttk.Label(self,textvariable=self.note,style='Muted.TLabel',wraplength=620).pack(fill='x',pady=(5,0))
        self.after(1000,self.tick)

    def reset(self):
        self.app.commands.put({'type':'reset_efficiency'}) if self.app.live_active else None
        if not self.app.live_active:self.note.set('請在登入後重設統計')

    def update_state(self,state):self.state=state;self.render()

    def tick(self):
        if self.winfo_exists():
            if self.winfo_ismapped():self.render()
            self.after(1000,self.tick)

    def render(self,force=False):
        eff=self.state.get('efficiency',{});rows=eff.get('rows',{})
        labels={(('玩家｜' if key=='self' else '夥伴／坐騎｜')+row['name']+(f" #{key.split(':')[1]}" if key!='self' else '')):key for key,row in rows.items()}
        if labels!=self.labels:
            old=self.labels.get(self.selected.get());self.labels=labels;self.choice.configure(values=list(labels))
            self.selected.set(next((k for k,v in labels.items() if v==old),next(iter(labels),'')))
        row=rows.get(labels.get(self.selected.get()))
        if row is None:
            self.signature=None;self.info.set('等待登入角色與經驗資料');self.total.set('首場作基準，從第二個有效樣本計算效率');self.progress['value']=0
            for iid in ('all','ten','thirty'):self.table.item(iid,values=('—',)*4)
            return
        degree=row['degree'];level=row['level'];total=row['exp'];remaining,pct,target=progress(total,level,degree) if total is not None else (None,None,None)
        rate_values=rates(row);elapsed=0
        if not eff.get('offline') and row['last_time'] is not None and self.app.live_active:elapsed=max(0,time.monotonic()-row['last_time'])
        unit=self.unit.get();multiplier={'分':1,'時':60,'天':1440}[unit]
        values=[]
        for label,(rate,count) in zip(('總平均','近10場','近30場'),rate_values):
            values.append((f'{label}（{count}場）',f'{rate*multiplier:,.0f}' if rate is not None else '等待樣本',forecast(remaining,rate,elapsed),forecast(target,rate,elapsed) if degree==1 else '—'))
        info=f"{row['name']}｜{STAGES.get(degree,'階段待同步')}｜{str(level)+' 級' if level is not None else '等級待同步'}｜進度 {pct:.1f}%" if pct is not None else f"{row['name']}｜{STAGES.get(degree,'階段待同步')}｜等級 {level if level is not None else '待同步'}｜升級進度待同步"
        summary=f"累積經驗：{total:,}" if total is not None else '累積經驗：等待伺服器同步'
        summary+=f"｜本次統計 +{row['earned']:,}｜本場 {('+'+format(row['last_gain'],',')) if row['last_gain'] is not None else '基準／待樣本'}"
        if remaining is not None:summary+=f'｜升級還差 {remaining:,}'
        note='首場作基準；有效場數不足時顯示實際樣本數。'
        if degree==0:note+='未轉生升級需求沿用 EXP_Monitor 參考公式。'
        if row.get('level_inferred') or row.get('degree_inferred'):note+='此夥伴／坐騎的等級或階段依經驗曲線推估。'
        if eff.get('offline'):note+='離線分析採封包時間。'
        signature=(info,summary,pct,unit,tuple(values),note)
        if force or signature!=self.signature:
            self.signature=signature;self.info.set(info);self.total.set(summary);self.progress['value']=pct or 0;self.note.set(note)
            self.table.heading('speed',text='經驗／'+unit)
            for iid,value in zip(('all','ten','thirty'),values):self.table.item(iid,values=value)
