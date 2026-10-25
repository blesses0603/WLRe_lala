"""NPC display, guarded interaction, read-only shop and dialogue widgets.

NPCIndex/TalkData/ItemData remain verified resource services; no packet,
purchase, or server authority is implemented in this UI mixin.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from wlre.services.world.npc_catalog import npc_detail
from wlre.services.world.npc_talk import dialogue_text
from wlre.services.world.npc_shop import shop_catalog
from wlre.services.world.npc_item_data import item_catalog, sellable


class NPCInteractionMixin:
    def choose_npc(self,event=None):
        selected=self.npc_list.curselection()
        if not selected or selected[0]>=len(self.npc_rows):return
        npc=self.npc_rows[selected[0]]
        self.select_npc(npc)
        if npc['x'] is not None and 0<=npc['x']<=65535 and 0<=npc['y']<=65535:
            self.on_pick(self.selected_id,npc['x'],npc['y'])

    def select_npc(self,npc):
        self.selected_npc=npc
        self.selected_portal=None
        self.portal_list.selection_clear(0,'end')
        self.update_portal_button()
        self.npc_list.selection_clear(0,'end')
        pos=next((i for i,row in enumerate(self.npc_rows) if row is npc),None)
        if pos is not None:
            self.npc_list.selection_set(pos)
            self.npc_list.see(pos)
        self.npc_message.set(npc_detail(npc))
        self.update_npc_buttons()
        self.draw()

    def update_npc_buttons(self):
        npc=self.selected_npc
        current=self.state or {}
        player=current.get('player',{})
        loc=current.get('location',{})
        confirmed=loc.get('confirmed') or {}
        battle=current.get('battle',{})
        dialogue=current.get('npc_dialogue',{})
        post=(battle.get('post_event') or {}).get('status')
        moving=(current.get('local_movement') or {}).get('status') in ('running','finished')
        can_start=(self.on_npc is not None and npc is not None and npc.get('verified')
                   and npc.get('event_count',0)>0 and current.get('phase')=='world_ready'
                   and npc.get('scene')==player.get('scene')==confirmed.get('scene')
                   and loc.get('confirmed_is_current') and not moving
                   and not current.get('roaming',{}).get('enabled')
                   and not battle.get('active') and post in (None,'completed')
                   and not current.get('event_flow',{}).get('blocked'))
        self.npc_talk_button.configure(state='normal' if can_start else 'disabled')
        can_next=(self.on_npc_next is not None and not battle.get('active')
                  and dialogue.get('active')
                  and dialogue.get('scene')==player.get('scene')
                  and dialogue.get('phase') in ('talk','continue'))
        self.npc_next_button.configure(state='normal' if can_next else 'disabled')
        can_close=(self.on_npc_next is not None and dialogue.get('active')
                   and dialogue.get('phase')=='choice_unavailable'
                   and dialogue.get('effect_type')==6
                   and dialogue.get('scene')==player.get('scene')
                   and not battle.get('active'))
        known_shop=(self.npc_interacts.get(dialogue.get('scene'),dialogue.get('option_index'))
                    if can_close else None)
        is_shop=bool(known_shop and known_shop['form_kind'] in (2,3))
        self.npc_close_button.configure(state='normal' if can_close and not is_shop else 'disabled')
        current_shop=(shop_catalog(dialogue.get('scene'),dialogue.get('option_index'),
                      index=self.npc_interacts) if is_shop else None)
        self.npc_shop_button.configure(
            state='normal' if is_shop and current_shop and self.on_npc_next is not None
            else 'disabled')
        can_view=(dialogue.get('active') and dialogue.get('phase')=='talk'
                  and dialogue_text(self.npc_talks,dialogue.get('text_id')) is not None)
        self.npc_text_button.configure(state='normal' if can_view else 'disabled')
        history=dialogue.get('history') or []
        self.npc_history_button.configure(state='normal' if history else 'disabled')
        choices=(self.npc_interacts.choices(dialogue.get('scene'),
                 dialogue.get('option_index'), self.npc_talks)
                 if dialogue.get('active') and dialogue.get('phase')=='choice_unavailable'
                 and dialogue.get('scene')==player.get('scene') and not battle.get('active')
                 else None)
        self.npc_options_button.configure(
            state='normal' if choices is not None and self.on_npc_next is not None else 'disabled')

    def interact_npc(self):
        npc=self.selected_npc
        if npc is None or str(self.npc_talk_button.cget('state'))!='normal':
            return
        if not messagebox.askyesno('確認 NPC 互動',
                '只送出一次官方 C20-1。NPC 事件可能啟動戰鬥、任務或未支援的選項。'
                '\n不會自動靠近、購物或重送封包。確定要互動嗎？',parent=self):
            return
        self.on_npc({'type':'npc_start','confirmed':True,'scene':npc['scene'],
                     'npc_index':npc['npc_index'],'npc_id':npc['npc_id'],
                     'x':npc['x'],'y':npc['y']})

    def next_npc(self):
        if str(self.npc_next_button.cget('state'))=='normal':
            self.on_npc_next({'type':'npc_next'})

    def show_npc_shop(self):
        """Read-only shop listing backed by official Eve; never send purchases."""
        if str(self.npc_shop_button.cget('state'))!='normal':
            return
        info=self.state.get('npc_dialogue',{})
        if (not info.get('active') or info.get('phase')!='choice_unavailable'
                or self.state.get('player',{}).get('scene')!=info.get('scene')):
            return
        catalog=shop_catalog(info.get('scene'),info.get('option_index'),
                             index=self.npc_interacts)
        if catalog is None:
            return
        if self.npc_shop_window is not None:
            try:
                if self.npc_shop_window.winfo_exists():
                    self.npc_shop_window.destroy()
            except tk.TclError:
                pass
        win=tk.Toplevel(self)
        self.npc_shop_window=win
        win.title('NPC '+catalog['title']+'（官方價格預覽／交易未啟用）')
        win.geometry('680x475')
        win.transient(self.winfo_toplevel())
        body=ttk.Frame(win,padding=12)
        body.pack(fill='both',expand=True)
        ttk.Label(body,text=catalog['title']+'｜商品 ID：Eve；金額：ItemData_C 基礎價',
                  wraplength=640).pack(fill='x',pady=(0,4))
        ttk.Label(body,text=catalog.get('resource_index_note', '官方分類來源待確認'),
                  style='Muted.TLabel',wraplength=640).pack(fill='x',pady=(0,6))
        tabs=ttk.Notebook(body)
        tabs.pack(fill='both',expand=True)
        offers=ttk.Frame(tabs)
        owned=ttk.Frame(tabs)
        tabs.add(offers,text='購買商品（唯讀）')
        tabs.add(owned,text='背包／販售預覽（唯讀）')
        def add_grid(parent,columns,widths):
            frame=ttk.Frame(parent)
            frame.pack(fill='both',expand=True,pady=5)
            tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
            for key,title,width in widths:
                tree.heading(key,text=title)
                tree.column(key,width=width,anchor='w')
            scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right',fill='y')
            tree.pack(side='left',fill='both',expand=True)
            return tree
        items=add_grid(offers,('index','id','name','price'),(
            ('index','商品索引',85),('id','官方物品 ID',105),
            ('name','官方物品名稱',260),('price','金幣基礎價',125)))
        for row in catalog['products']:
            items.insert('','end',values=(row['offer_index'],row['item_id'],
                         row['name'],row['price_gold'] if row['price_gold'] is not None else '資料未核實'))
        bag=add_grid(owned,('slot','id','name','count','sale'),(
            ('slot','格位',70),('id','物品 ID',95),('name','物品名稱',230),
            ('count','數量',75),('sale','NPC 收購價／限制',150)))
        try:
            verified_items=item_catalog()
        except (OSError,ValueError,EOFError,UnicodeError):
            verified_items={}
        inv=self.state.get('inventory',{})
        if inv.get('ready') and inv.get('reliable'):
            for slot,record in sorted(inv.get('items',{}).items(),
                                      key=lambda x:int(x[0])):
                item_id=record.get('item_id')
                if type(item_id) is int:
                    official=verified_items.get(item_id)
                    sale=(('不可賣給 NPC' if not sellable(official)
                           else str(official['sell_price'])) if official else '來源未核實')
                    bag.insert('','end',values=(slot,item_id,
                               official['name'] if official else f'物品 {item_id}',
                               record.get('count',0),sale))
        else:
            ttk.Label(owned,text='背包尚未由伺服器可靠同步，不顯示推定可售商品。').pack()
        gold=self.state.get('gold',{})
        if gold.get('ready') and gold.get('reliable') and type(gold.get('amount')) is int:
            balance=f"目前金幣：{gold['amount']:,}（伺服器 S26 同步；不代表已可交易）"
        else:
            balance='目前金幣：尚未收到可信 S26 初始化／增減回覆'
        ttk.Label(body,text=balance,wraplength=640).pack(fill='x',pady=(8,0))
        evidence=self.state.get('shop_evidence',{})
        history=evidence.get('events') or []
        packet_labels={'bag_snapshot':'S23-5','bag_add':'S23-6',
                       'bag_delete':'S23-9','bag_sell':'S27-6',
                       'gold_snapshot':'S26-4','gold_delta':'S26-1/2',
                       'gold_limit':'S26-3','shop_purchase_result':'S27-1',
                       'sale_notice':'S27-8'}
        latest='、'.join(packet_labels.get(entry.get('type'),'其他')
                        for entry in history[-5:]) if history else '尚無'
        ttk.Label(body,text='最近交易相關伺服器封包：'+latest+
                  '。此為觀測紀錄，不代表交易已結算。',
                  wraplength=640).pack(fill='x',pady=(5,0))
        ttk.Label(body,text=catalog['reason'],wraplength=640,
                  foreground='#ad5b32').pack(fill='x',pady=6)
        ttk.Label(body,text='顯示 ItemData_C 官方基礎價；實際折扣後價格和當前持有金幣尚待同步。禁止購買或販售。',
                  wraplength=640).pack(fill='x')
        ttk.Button(body,text='關閉商店（需伺服器確認）',
                   command=lambda:self.close_npc_shop_dialog(catalog)).pack(fill='x',pady=(8,0))
        win.protocol('WM_DELETE_WINDOW',lambda:self.close_npc_shop_dialog(catalog))

    def close_npc_shop_dialog(self,catalog):
        info=self.state.get('npc_dialogue',{})
        if (not info.get('active') or info.get('phase')!='choice_unavailable'
                or info.get('effect_type')!=6
                or info.get('scene')!=catalog['scene']
                or info.get('option_index')!=catalog['interact_index']
                or self.state.get('battle',{}).get('active')
                or self.on_npc_next is None):
            return
        current=shop_catalog(info['scene'],info['option_index'],
                             index=self.npc_interacts)
        if current!=catalog:
            return
        if not messagebox.askyesno('確認關閉商店',
                '官方 C20-9 空內容關閉商店，不會購買／出售任何物品。'
                '\n只送出一次，需等待伺服器 S20-8；確認關閉嗎？',
                parent=self.npc_shop_window or self):
            return
        if self.npc_shop_window is not None and self.npc_shop_window.winfo_exists():
            self.npc_shop_window.destroy()
            self.npc_shop_window=None
        self.on_npc_next({'type':'npc_close_shop','confirmed':True})

    def show_npc_choices(self):
        dialogue=self.state.get('npc_dialogue',{})
        if str(self.npc_options_button.cget('state'))!='normal':
            return
        options=self.npc_interacts.choices(dialogue.get('scene'),
                        dialogue.get('option_index'), self.npc_talks)
        if options is None:
            return
        # Never allow old dialogs to remain actionable after a state change.
        if self.npc_choice_window is not None:
            try:
                if self.npc_choice_window.winfo_exists():
                    self.npc_choice_window.destroy()
            except tk.TclError:
                pass
        win=tk.Toplevel(self)
        self.npc_choice_window=win
        win.title('NPC 互動選項（一般對話）')
        win.geometry('520x360')
        win.transient(self.winfo_toplevel())
        panel=ttk.Frame(win,padding=12)
        panel.pack(fill='both',expand=True)
        ttk.Label(panel,text=options['title'],wraplength=470).pack(fill='x',pady=(0,8))
        frame=ttk.Frame(panel)
        frame.pack(fill='both',expand=True)
        canvas=tk.Canvas(frame,highlightthickness=0,background='#203f53')
        scroll=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
        contents=ttk.Frame(canvas)
        contents.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0),window=contents,anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        for choice in options['options']:
            label=choice['text']
            btn=ttk.Button(contents,text=label,command=lambda item=choice:
                           self.choose_npc_reply(options,item),width=48)
            btn.pack(fill='x',pady=3)
        ttk.Label(panel,text='僅手動確認後送出一次；任務效果由伺服器決定。',
                  wraplength=470).pack(fill='x',pady=(8,0))

    def choose_npc_reply(self, options, item):
        dialogue=self.state.get('npc_dialogue',{})
        if (not dialogue.get('active') or dialogue.get('phase')!='choice_unavailable'
                or dialogue.get('scene')!=options['scene']
                or dialogue.get('option_index')!=options['index']
                or self.state.get('battle',{}).get('active')):
            return
        fresh=self.npc_interacts.choices(options['scene'],options['index'],self.npc_talks)
        if fresh!=options or item not in options['options']:
            return
        if not messagebox.askyesno('確認 NPC 選項',
                f"你選擇：「{item['text']}」\n此操作可能觸發任務、物品或戰鬥效果。"
                "\n只會發送一次，不會自動重試。確定送出嗎？",
                parent=self.npc_choice_window or self):
            return
        if self.npc_choice_window is not None and self.npc_choice_window.winfo_exists():
            self.npc_choice_window.destroy()
            self.npc_choice_window=None
        self.on_npc_next({'type':'npc_choose','confirmed':True,
                          'scene':options['scene'],'interact_index':options['index'],
                          'choice':item['choice'],'text_id':item['text_id']})

    def close_npc_option(self):
        if str(self.npc_close_button.cget('state'))!='normal':
            return
        if not messagebox.askyesno('確認關閉 NPC 選項',
                '使用官方 C20-9 40 關閉這個選項清單，不選擇任何選項。'
                '\n需等待伺服器 S20-8；逾時不會重送。確定嗎？',parent=self):
            return
        self.on_npc_next({'type':'npc_close_choice','confirmed':True})

    def view_npc_text(self):
        dialogue=self.state.get('npc_dialogue',{})
        if dialogue.get('active') and dialogue.get('phase')=='talk':
            text=dialogue_text(self.npc_talks,dialogue.get('text_id'))
            if text is not None:
                messagebox.showinfo('NPC 對話（官方文字 ID '+str(dialogue['text_id'])+'）',
                                    text or '（空白對話）',parent=self)

    def view_npc_history(self):
        """Read-only, bounded record of this manually started dialogue."""
        history=(self.state.get('npc_dialogue',{}).get('history') or [])[-50:]
        if not history:
            return
        if self.npc_history_window is not None:
            try:
                if self.npc_history_window.winfo_exists():
                    self.npc_history_window.destroy()
            except tk.TclError:
                pass
        win=tk.Toplevel(self)
        self.npc_history_window=win
        win.title('NPC 本輪對話紀錄')
        win.geometry('560x360')
        panel=ttk.Frame(win,padding=10)
        panel.pack(fill='both',expand=True)
        scroll=ttk.Scrollbar(panel,orient='vertical')
        scroll.pack(side='right',fill='y')
        content=tk.Text(panel,wrap='word',yscrollcommand=scroll.set,
                        background='#203f53',foreground='#f4e4b5',
                        borderwidth=0,highlightthickness=0,
                        font=('Microsoft JhengHei UI',11))
        content.pack(side='left',fill='both',expand=True)
        scroll.configure(command=content.yview)
        for number,text_id in enumerate(history,1):
            text=dialogue_text(self.npc_talks,text_id)
            content.insert('end',f'{number:02d}. 對話 ID {text_id}\n'
                + (text if text is not None else '（未取得對應原文）')
                + '\n\n')
        content.configure(state='disabled')
        win.transient(self.winfo_toplevel())

    def show_dialogue_status(self):
        dialogue=self.state.get('npc_dialogue',{})
        if dialogue.get('active'):
            phase=dialogue.get('phase')
            if phase=='talk':
                text_id=dialogue.get('text_id')
                content=dialogue_text(self.npc_talks,text_id)
                if content is not None:
                    excerpt=content.replace('\r','').replace('\n',' ')[:85]
                    self.npc_message.set(f'對話 ID {text_id}：{excerpt}'
                        + ('…（可查看全文）' if len(content)>85 else ''))
                else:
                    self.npc_message.set(
                        f"對話文字 ID {text_id}；尚無已驗證的文字表，請手動接續。")
            elif phase=='continue':
                self.npc_message.set('伺服器允許繼續，請按下一段對話。')
            elif phase=='choice_unavailable' and (
                    (shop_catalog(dialogue.get('scene'),dialogue.get('option_index'),
                     index=self.npc_interacts) is not None)):
                self.npc_message.set('NPC 商店已開啟：可查看官方商品基礎價與不可販售標記；'
                                     '折扣與金幣同步未確認，不會購買或販售。')
            elif phase=='closing_shop':
                self.npc_message.set('已要求關閉 NPC 商店，等待伺服器確認；不會重送。')
            elif phase=='choice_unavailable':
                self.npc_message.set(
                    f"選項索引 {dialogue.get('option_index')} 尚無可信資料；"
                    "不會自行選擇；可手動按「關閉選項」，或重新登入同步。")
            elif phase=='awaiting_choice':
                self.npc_message.set('已送出一般 NPC 選項；等待伺服器回覆，不會重送。')
            elif phase=='closing':
                self.npc_message.set('已要求關閉選項，等待伺服器 S20-8；不自動重送。')
            elif phase=='effect_unavailable':
                self.npc_message.set('收到未支援的事件效果；停止自動接續，必要時重新登入。')
            else:
                self.npc_message.set('等待 NPC 伺服器回覆中；不自動重送。')
        elif dialogue.get('phase')=='ended':
            self.npc_message.set('NPC 事件已由伺服器 S20-8 確認結束。')
        elif dialogue.get('phase')=='rejected':
            self.npc_message.set('NPC 事件被伺服器拒絕：'+dialogue.get('reason',''))

