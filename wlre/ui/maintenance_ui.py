"""Repair/cleanup draft and live backpack-only item selection."""
import tkinter as tk
from tkinter import ttk, messagebox
from wlre.ui.layout import scroll_table
from wlre.ui.window_layout import configure_dialog
from wlre.ui.crafting_browser import ItemIcons
from wlre.services.items.combat_resources import item_name
from wlre.services.items.maintenance import backpack_stock, cleanup_action


class BackpackPicker:
    def __init__(self,page,kind,index):
        self.page=page;self.kind=kind;self.index=index;self.job=None;self.signature=None
        self.window=w=tk.Toplevel(page);w.title('從背包選擇物品');configure_dialog(w,680,520)
        self.search=tk.StringVar();self.note=tk.StringVar();self.images=[]
        box=ttk.Frame(w,padding=12);box.pack(fill='both',expand=True)
        ttk.Label(box,text='只列出已同步背包的可用物品；不讀取倉庫或全物品目錄。').pack(anchor='w')
        ttk.Entry(box,textvariable=self.search).pack(fill='x',pady=8)
        frame,self.table=scroll_table(box,('name','count'),('物品名稱','可用數量'),(400,100),
                                     height=9,show='tree headings',horizontal_scrollbar=False)
        self.table.column('#0',width=36,minwidth=36,stretch=False)
        frame.pack(fill='both',expand=True);self.table.bind('<Double-1>',lambda e:self.choose())
        ttk.Label(box,textvariable=self.note,wraplength=600).pack(fill='x',pady=8)
        buttons=ttk.Frame(box);buttons.pack(fill='x')
        ttk.Button(buttons,text='清除此格',command=lambda:self.commit(0)).pack(side='left')
        ttk.Button(buttons,text='選取',command=self.choose).pack(side='right')
        ttk.Button(buttons,text='取消',command=w.destroy).pack(side='right',padx=6)
        self.search.trace_add('write',lambda *a:self.refresh(force=True))
        w.bind('<Destroy>',self.destroyed,add='+');self.poll()

    def stock(self):
        stock=backpack_stock(self.page.editor.app.snapshot.get('inventory',{}),self.kind=='repair')
        return stock if self.kind=='repair' else {sid:count for sid,count in stock.items() if cleanup_action(sid)}

    def refresh(self,force=False):
        stock=self.stock();query=self.search.get().strip().casefold();signature=(stock,query)
        if not force and signature==self.signature:return
        self.signature=signature;selection=self.table.selection()
        self.table.delete(*self.table.get_children());self.images=[]
        for sid,count in sorted(stock.items(),key=lambda row:item_name(row[0])):
            if query and query not in item_name(sid).casefold() and query not in str(sid):continue
            image=self.page.icons.get(sid,24);self.images.append(image)
            self.table.insert('', 'end',iid=str(sid),image=image,values=(item_name(sid),count))
        if selection and self.table.exists(selection[0]):self.table.selection_set(selection[0])
        inv=self.page.editor.app.snapshot.get('inventory',{})
        self.note.set('背包尚未可靠同步，暫無可選物品。' if not inv.get('ready') or not inv.get('reliable') else
                      f'目前可選 {len(self.table.get_children())} 種；已排除鎖定、限時及保留物品。')

    def poll(self):
        self.refresh();self.job=self.window.after(1000,self.poll)

    def commit(self,sid):
        if sid and sid not in self.stock():
            self.refresh(force=True)
            messagebox.showinfo('背包已變更','該物品已不在可用背包內，請重新選擇。',parent=self.window);return
        values=self.page.items[self.kind]
        if sid and sid in values and values[self.index]!=sid:
            messagebox.showinfo('已選取','同種物品不需要重複設定。',parent=self.window);return
        values[self.index]=sid;self.page.refresh_slots(force=True);self.window.destroy()

    def choose(self):
        selected=self.table.selection()
        if selected:self.commit(int(selected[0]))

    def destroyed(self,event):
        if event.widget is self.window and self.job is not None:
            self.window.after_cancel(self.job);self.job=None


class MaintenancePage(ttk.Frame):
    def __init__(self,parent,editor):
        super().__init__(parent,padding=12);self.editor=editor;self.icons=ItemIcons(self)
        self.items={'repair':[0,0],'cleanup':[0]*15};self.buttons={};self.images=[]
        self.repair_enabled=tk.BooleanVar();self.cleanup_enabled=tk.BooleanVar();self.threshold=tk.IntVar(value=50)
        self.runtime_note=tk.StringVar()
        self.stock_note=tk.StringVar();self.signature=None;self.job=None
        ttk.Label(self,text='啟用 AI 後，在戰鬥與戰後事件結束時執行；每次操作均等待伺服器確認。',
                  wraplength=960).pack(fill='x',pady=(2,4))
        row=ttk.Frame(self);row.pack(fill='x')
        ttk.Checkbutton(row,text='戰鬥結束後，修復角色／出戰夥伴剩餘耐久低於或等於門檻的普通裝備',
                        variable=self.repair_enabled).pack(side='left')
        ttk.Spinbox(row,from_=0,to=249,width=5,textvariable=self.threshold).pack(side='right')
        ttk.Label(self,text='剩餘耐久使用 250 點制，預設 50；特殊、限時及已損壞裝備不自動修理。',style='Muted.TLabel').pack(anchor='w',pady=4)
        ttk.Label(self,text='修理道具順序（由左至右；只從背包選擇）').pack(anchor='w',pady=(8,4))
        slots=ttk.Frame(self);slots.pack(anchor='w')
        self.make_slots(slots,'repair',2)
        ttk.Separator(self).pack(fill='x',pady=8)
        ttk.Checkbutton(self,text='戰鬥結束後，自動販售／丟棄指定物品',variable=self.cleanup_enabled).pack(anchor='w')
        ttk.Label(self,text='依官方限制可販售者先賣；不可販售但可丟棄者才丟棄，兩者皆不可者略過。',
                  style='Muted.TLabel').pack(anchor='w',pady=(2,4))
        slots=ttk.Frame(self);slots.pack(anchor='w',fill='x')
        self.make_slots(slots,'cleanup',5)
        ttk.Label(self,textvariable=self.runtime_note,wraplength=950).pack(fill='x',pady=(4,0))
        ttk.Label(self,textvariable=self.stock_note,wraplength=950).pack(fill='x',pady=4)
        self.bind('<Destroy>',self.destroyed,add='+');self.poll()

    def make_slots(self,parent,kind,columns):
        for column in range(columns):parent.columnconfigure(column,weight=1)
        for index in range(len(self.items[kind])):
            button=ttk.Button(parent,width=14,compound='left',padding=(3,2),command=lambda k=kind,i=index:BackpackPicker(self,k,i))
            button.grid(row=index//columns,column=index%columns,sticky='ew',padx=(0,8),pady=4)
            button.bind('<Button-3>',lambda event,k=kind,i=index:self.clear(k,i))
            self.buttons[kind,index]=button

    def clear(self,kind,index):
        self.items[kind][index]=0;self.refresh_slots(force=True)

    def render(self,value):
        self.items={'repair':list(value['repair_items']),'cleanup':list(value['cleanup_items'])}
        self.threshold.set(value['repair_below']);self.repair_enabled.set(value['repair_enabled']);self.cleanup_enabled.set(value['cleanup_enabled'])
        self.refresh_slots(force=True)

    def collect(self):
        return {'repair_enabled':self.repair_enabled.get(),'cleanup_enabled':self.cleanup_enabled.get(),'repair_below':self.threshold.get(),
                'repair_items':list(self.items['repair']),'cleanup_items':list(self.items['cleanup'])}

    def refresh_slots(self,force=False):
        inv=self.editor.app.snapshot.get('inventory',{});stock=backpack_stock(inv)
        signature=(stock,repr(self.items),inv.get('ready'),inv.get('reliable'))
        if not force and signature==self.signature:return
        self.signature=signature;self.images=[]
        for (kind,index),button in self.buttons.items():
            sid=self.items[kind][index]
            if sid:
                image=self.icons.get(sid,24);self.images.append(image)
                count=stock.get(sid,0)
                button.configure(text=item_name(sid)[:6]+' '+(f'×{count}' if count else '缺貨'),image=image)
            else:button.configure(text=f'{index+1}　＋',image='')
        self.stock_note.set('背包已同步，庫存自動更新；點格選物品，右鍵清除。' if inv.get('ready') and inv.get('reliable') else
                            '等待背包可靠同步；目前不能新增物品。')

    def poll(self):
        self.runtime_note.set(self.editor.app.snapshot.get('maintenance',{}).get('status','等待戰後檢查'))
        self.refresh_slots();self.job=self.after(1000,self.poll)

    def destroyed(self,event):
        if event.widget is self:
            if self.job is not None:self.after_cancel(self.job);self.job=None
            self.icons.close()
