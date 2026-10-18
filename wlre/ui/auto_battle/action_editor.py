"""Single-action editor; settings persist only through an explicit parent commit."""
import copy
import os
import tkinter as tk
from tkinter import ttk, messagebox
from wlre.ui.window_layout import configure_dialog
from wlre.ui.layout import heading
from wlre.ui.auto_battle.model import (NAMES, TARGETS, NOTICES, COMPARES,
                                      confirmed_skill_entries, confirmed_action_label,
                                      action_entries)

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
