"""Crafting queue window and server-confirmed queue rendering.

Methods are mixed into CraftingBrowser without changing its public API.
"""
import time
import tkinter as tk
from tkinter import ttk

from wlre.ui.window_layout import configure_dialog
from wlre.services.items.crafting import effective_time, elapsed
from wlre.services.items.combat_resources import item_name
from wlre.core.efficiency import duration


class CraftingQueueMixin:
    def show_queue(self):
        if self.queue_window and self.queue_window.winfo_exists():self.queue_window.lift();return
        w=self.queue_window=tk.Toplevel(self.window);w.title('製作排程');configure_dialog(w,820,420);w.resizable(False,False)
        body=ttk.Frame(w,padding=12);body.pack(fill='both',expand=True)
        self.queue=ttk.Treeview(body,columns=['order','name','count','time'],show='headings',height=5)
        for key,title,width in [('order','順序',55),('name','製作物',300),('count','批數',65),('time','剩餘時間',220)]:self.queue.heading(key,text=title);self.queue.column(key,width=width,anchor='center')
        self.queue.pack(fill='both',expand=True)
        self.queue_activity=tk.StringVar();ttk.Label(body,textvariable=self.queue_activity,wraplength=760).pack(fill='x',before=self.queue)
        self.queue_progress=ttk.Progressbar(body,maximum=100);self.queue_progress.pack(fill='x',before=self.queue,pady=(3,6))
        buttons=ttk.Frame(body);buttons.pack(fill='x',pady=5)
        for label,action in [('開始／接續','start'),('暫停','pause'),('停止接續','stop_auto'),('上移','up'),('下移','down'),('移除','delete')]:ttk.Button(buttons,text=label,command=lambda a=action:self.queue_command(a)).pack(side='left',padx=3)
        self.queue_status=tk.StringVar();ttk.Label(body,textvariable=self.queue_status,style='Muted.TLabel',wraplength=720).pack(fill='x')
        self.queue_key=None;self.update_queue()

    def queue_command(self,action):
        if action in ('up','down','delete'):
            selected=self.queue.selection()
            if not selected:self.queue_status.set('請先選擇製作排程');return
            return self.panel.command(action,index=selected[0])
        self.panel.command(action)

    def update_queue(self):
        c=self.state.get('crafting',{});now=time.monotonic()
        active=next((r for r in c.get('queue',{}).values() if r['index']==c.get('active')),None)
        if active:
            seconds=effective_time(self.state,active)
            total=seconds if seconds is not None else active['base_time']
            spent=elapsed(c,active,now);remaining=max(0,total-spent)
            phase='製作中' if c.get('running') else '已暫停'
            self.queue_activity.set(f"{phase}：{item_name(active['item_id'])}｜剩餘 {duration(remaining)}｜已完成 {c.get('completed',0)} 項")
            self.queue_progress['value']=min(100,100*spent/total) if total>0 else 0
        else:
            self.queue_activity.set(f"等待製作｜排程 {len(c.get('queue',{}))} 項｜已完成 {c.get('completed',0)} 項")
            self.queue_progress['value']=0
        rows=[]
        for iid,row in sorted(c.get('queue',{}).items(),key=lambda value:int(value[0])):
            seconds=effective_time(self.state,row)
            remaining=max(0,(seconds if seconds is not None else row['base_time'])-elapsed(c,row,now))
            text='等待完成回覆' if c.get('completion_requested') and row['index']==c.get('active') else duration(remaining)
            rows.append((str(iid),(row['index'],item_name(row['item_id']),row['count'],text)))
        key=(c.get('revision'),c.get('status'),tuple(rows))
        if key==getattr(self,'queue_key',None):return
        self.queue_key=key;selected=self.queue.selection();self.queue.delete(*self.queue.get_children())
        for iid,values in rows:self.queue.insert('','end',iid=iid,values=values)
        if selected and self.queue.exists(selected[0]):self.queue.selection_set(selected[0])
        self.queue_status.set(c.get('status','等待同步'))
