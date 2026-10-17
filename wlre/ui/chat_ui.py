"""Persistent, bounded chat panel; normal receives append without rebuilding UI."""
from collections import deque
from datetime import datetime
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from tkinter import ttk
from wlre.ui.theme import group
from wlre.services.social.chat import CHANNELS, chat_packet, plain_text
from wlre.services.social.chat_names import NameBook, name_scope
from wlre.ui.chat_emoji import EmojiImages, segments
import re
import os
from wlre.network.wire import ProtocolError


class ChatPanel(ttk.Frame):
    def __init__(self,parent,app,height=250):
        super().__init__(parent,height=height)
        self.pack_propagate(False)
        self.display_dirty=False
        self.app=app;self.messages=deque(maxlen=200);self.pending=False;self.line_targets={};self.line_events={};self.names=NameBook();self.quote=None;self.sent_quote=None;self.emoji_picker=None;self.emojis=EmojiImages(self)
        box=group(self,text='聊天',padding=6);box.pack(fill='both',expand=True)
        tools=ttk.Frame(box);tools.pack(fill='x',pady=(0,3))
        self.filter=tk.StringVar(value='全部')
        ttk.Label(tools,text='顯示').pack(side='left')
        self.filters=ttk.Combobox(tools,textvariable=self.filter,state='readonly',values=['全部',*CHANNELS,'跨服','系統'],width=7)
        self.filters.pack(side='left',padx=(3,6));self.filters.bind('<<ComboboxSelected>>',lambda e:self.redraw())
        self.status=tk.StringVar(value='右鍵引用回覆；雙擊密語；表情可由按鈕插入')
        ttk.Label(tools,textvariable=self.status,style='Muted.TLabel',wraplength=350).pack(side='left',fill='x',expand=True)
        self.unread=0
        self.latest_button=ttk.Button(tools,text='最新',command=self.latest);self.latest_button.pack(side='right')
        compose=ttk.Frame(box);compose.pack(side='bottom',fill='x',pady=(4,0))
        self.channel=tk.StringVar(value='區域');self.target=tk.StringVar();self.text=tk.StringVar()
        self.channel_combo=ttk.Combobox(compose,textvariable=self.channel,state='readonly',values=list(CHANNELS),width=5)
        self.channel_combo.pack(side='left',padx=(0,4));self.channel_combo.bind('<<ComboboxSelected>>',lambda e:self.target_state())
        self.target_label=ttk.Label(compose,text='名稱/ID')
        self.target_entry=ttk.Entry(compose,textvariable=self.target,width=11)
        self.send_button=ttk.Button(compose,text='送出',command=self.send);self.send_button.pack(side='right',padx=(4,0))
        ttk.Button(compose,text='表情',width=4,command=self.show_emoji_picker).pack(side='right')
        self.entry=ttk.Entry(compose,textvariable=self.text);self.entry.pack(side='left',fill='x',expand=True)
        self.entry.bind('<Return>',lambda e:self.send())
        self.quote_bar=ttk.Frame(box);self.quote_text=tk.StringVar()
        ttk.Label(self.quote_bar,textvariable=self.quote_text,style='Muted.TLabel',wraplength=540).pack(side='left',fill='x',expand=True)
        ttk.Button(self.quote_bar,text='取消引用',command=self.cancel_quote).pack(side='right')
        body=self.body=ttk.Frame(box);body.pack(fill='both',expand=True)
        self.view=tk.Text(body,height=5,state='disabled',wrap='word',font=('Microsoft JhengHei UI' if os.name=='nt' else 'WenQuanYi Micro Hei',-14),background='#142638',foreground='#eff7ff',relief='flat',cursor='arrow')
        bar=ttk.Scrollbar(body,orient='vertical',command=self.view.yview)
        self.view.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');self.view.pack(fill='both',expand=True)
        self.view.bind('<Double-Button-1>',self.reply)
        self.view.bind('<Button-3>',self.context_menu)
        self.view.tag_configure('mention',foreground='#ffe49a',background='#3e4154')
        self.view.tag_configure('quoted',foreground='#9ab0c4')
        self.bind('<Destroy>',self.cleanup,add='+')
        for ch,color in {'區域':'#eaf4fa','世界':'#f8d479','隊伍':'#70e1de','組織':'#99e4a8','密語':'#f3a7ec','系統':'#aac9df','跨服':'#d4bbff'}.items():self.view.tag_configure(ch,foreground=color)

    def target_state(self):
        if self.quote and self.quote['channel']!=self.channel.get():self.cancel_quote()
        if self.channel.get()=='密語':
            self.target_label.pack(side='left',before=self.entry,padx=(0,2))
            self.target_entry.pack(side='left',before=self.entry,padx=(0,4))
        else:
            self.target_label.pack_forget();self.target_entry.pack_forget()

    def send(self):
        if self.pending:return
        if not self.app.live_active or not self.app.worker or not self.app.worker.is_alive():
            self.status.set('請先登入後再送出訊息');return
        command={'type':'chat','channel':self.channel.get(),'target':self.target.get(),'text':self.text.get()}
        from types import SimpleNamespace
        data=self.app.snapshot
        try:
            if command['channel']=='密語':command['target']=self.names.resolve(command['target'],data.get('player',{}).get('role_id'))
            if self.quote:command['reply']=dict(self.quote)
            chat_packet(command,SimpleNamespace(player=data.get('player',{}),attributes=data.get('attributes',{}),party=data.get('party',{})))
        except ProtocolError as exc:self.status.set(str(exc));return
        self.sent_quote=dict(self.quote) if self.quote else None
        self.pending=True;self.send_button.configure(state='disabled');self.status.set('準備送出…')
        self.app.send(command)

    def handle_event(self,event,state):
        kind=event['type']
        if kind not in ('chat_sent','chat_result','chat_notice','connection_closed','chat_message','command_rejected'):return
        if kind=='command_rejected' and event.get('command_type')!='chat':return
        self.update_names(state,event)
        if kind=='chat_sent':
            self.finish_pending()
            if self.text.get()==event['text']:self.text.set('')
            if self.sent_quote==self.quote:self.cancel_quote()
            self.sent_quote=None
            self.status.set('已送出，等待伺服器轉送；不代表對方已讀')
        elif kind in ('chat_result','chat_notice'):
            self.status.set(event['text'])
        elif kind=='command_rejected' and event.get('command_type')=='chat':
            self.finish_pending();self.status.set(event['error'])
        elif kind=='connection_closed':
            self.finish_pending();self.status.set('連線已結束，登入後可繼續聊天')
        elif kind=='chat_message':
            e=dict(event,time=datetime.now().strftime('%H:%M:%S'))
            e['name']=plain_text(self.names.name(e['role_id'],name_scope(e)) if e['role_id'] else '系統')
            e['own_id']=state.get('player',{}).get('role_id')
            at_bottom=self.view.yview()[1]>=.999
            dropped=self.messages[0] if len(self.messages)==self.messages.maxlen else None
            self.messages.append(e)
            if self.app.entered_world and self.app.background_window():
                self.display_dirty=True;return
            if dropped and self.matches(dropped):
                self.view.configure(state='normal');self.view.delete('1.0','2.0');self.view.configure(state='disabled')
                self.line_targets={line-1:target for line,target in self.line_targets.items() if line>1}
                self.line_events={line-1:value for line,value in self.line_events.items() if line>1}
            if self.matches(e):
                self.view.configure(state='normal');self.insert(e);self.view.configure(state='disabled')
                if at_bottom:self.latest()
                else:
                    self.unread+=1;self.latest_button.configure(text=f'最新 +{self.unread}')
            if e.get('reply_id') and e['reply_id']==e['own_id'] and e['channel']!='跨服':self.status.set(f"{e['name']} 引用了你的訊息")
            if e['channel']=='密語' and e['role_id']!=e['own_id']:self.status.set(f"收到密語：{e['name']}（{e['role_id']}）；雙擊回覆")

    def finish_pending(self):
        self.pending=False;self.send_button.configure(state='normal')

    def reset(self):
        self.messages.clear();self.names=NameBook();self.cancel_quote();self.sent_quote=None;self.finish_pending();self.redraw();self.status.set('新連線，聊天紀錄已清空')

    def matches(self,e):return self.filter.get() in ('全部',e['channel'])

    def update_names(self,state,event=None):
        if not self.names.update(state,event):return
        changed=False
        for e in self.messages:
            name=plain_text(self.names.name(e['role_id'],name_scope(e)) if e['role_id'] else '系統')
            if name!=str(e['role_id']) and e['name']!=name:e['name']=name;changed=True
        if changed:
            if self.app.entered_world and self.app.background_window():self.display_dirty=True
            else:self.redraw(scroll=False)

    def insert_content(self,text,tags):
        for kind,value in segments(plain_text(text)):
            picture=self.emojis.get(value) if kind=='emoji' else None
            if picture:self.view.image_create('end',image=picture,padx=1,align='center')
            else:self.view.insert('end',value,tags)

    def insert(self,e):
        line=int(self.view.index('end-1c').split('.')[0]);target=e['role_id']
        if target==e.get('own_id'):target=e.get('target_id')
        if target and e['channel']!='跨服':self.line_targets[line]=target
        self.line_events[line]=e
        suffix=f" → {self.names.name(e['target_id'])}" if e['channel']=='密語' and e.get('target_id') else ''
        self.view.insert('end',f"[{e['time']}] [{e['channel']}] {e['name']}{suffix}：",e['channel'])
        text=plain_text(e['text']);mention=re.match(r'@[^ ]+ ',text) if e.get('reply_id') else None
        if mention:
            self.view.insert('end',mention.group(0),(e['channel'],'mention'));text=text[mention.end():]
        self.insert_content(text,(e['channel'],))
        if e.get('items'):self.view.insert('end',' [道具連結]',e['channel'])
        if e.get('reply_text'):
            self.view.insert('end',' ↪ ','quoted');self.insert_content(e['reply_text'],('quoted',))
        self.view.insert('end','\n',e['channel'])

    def redraw(self,scroll=True):
        self.display_dirty=False
        position=self.view.yview()[0];self.view.configure(state='normal');self.view.delete('1.0','end');self.line_targets={};self.line_events={}
        for e in self.messages:
            if self.matches(e):self.insert(e)
        self.view.configure(state='disabled')
        if scroll:self.latest()
        else:self.view.yview_moveto(position)

    def latest(self):
        self.view.see('end');self.unread=0;self.latest_button.configure(text='最新')

    def reply(self,event):
        line=int(self.view.index(f'@{event.x},{event.y}').split('.')[0]);target=self.line_targets.get(line)
        if target:
            self.cancel_quote();self.channel.set('密語');self.target.set(str(target));self.target_state();self.entry.focus_set()
        return 'break'

    def context_menu(self,event):
        line=int(self.view.index(f'@{event.x},{event.y}').split('.')[0]);message=self.line_events.get(line)
        if not message:return 'break'
        menu=tk.Menu(self.view,tearoff=False)
        if message['channel'] in CHANNELS and message.get('role_id'):
            menu.add_command(label='引用回覆',command=lambda:self.quote_message(message))
        if line in self.line_targets:
            menu.add_command(label='密語',command=lambda:self.whisper_message(message))
        menu.add_command(label='複製訊息',command=lambda:self.copy_message(message))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return 'break'

    def whisper_message(self,message):
        target=message['role_id'] if message['role_id']!=message.get('own_id') else message.get('target_id')
        if target:
            self.cancel_quote();self.channel.set('密語');self.target.set(str(target));self.target_state();self.entry.focus_set()

    def copy_message(self,message):
        self.clipboard_clear();self.clipboard_append(plain_text(message['text']))

    def quote_message(self,message):
        if self.pending:self.status.set('請等待目前訊息送出後再選擇引用');return
        if message['channel'] not in CHANNELS or not message.get('role_id'):self.status.set('此頻道不支援引用回覆');return
        self.cancel_quote();self.channel.set(message['channel']);self.target_state()
        quote={'role_id':message['role_id'],'channel':message['channel'],'text':message['text'],'has_at':bool(message.get('reply_id')),'items':[v['item_id'] for v in message.get('items',[])]}
        if message['channel']=='密語':
            target=message['role_id'] if message['role_id']!=message.get('own_id') else message.get('target_id')
            if not target:self.status.set('密語對象資料不足');return
            quote['whisper_target']=target;self.target.set(str(target))
        self.quote=quote;self.quote_text.set('引用 '+message['name']+'：'+plain_text(message['text'])[:50])
        self.quote_bar.pack(side='bottom',fill='x',before=self.body)
        prefix='@'+message['name']+' '
        if not self.text.get().startswith(prefix):self.text.set(prefix+self.text.get())
        self.entry.focus_set()

    def cancel_quote(self):
        self.quote=None
        if hasattr(self,'quote_bar'):self.quote_bar.pack_forget()

    def show_emoji_picker(self):
        if self.emoji_picker and self.emoji_picker.winfo_exists():self.emoji_picker.lift();return
        w=self.emoji_picker=tk.Toplevel(self);w.title('遊戲表情');configure_dialog(w,600,480);w.resizable(False,False)
        box=ttk.Frame(w,padding=8);box.pack(fill='both',expand=True)
        bottom=ttk.Frame(box);bottom.pack(side='bottom',fill='x');grid=ttk.Frame(box);grid.pack(fill='both',expand=True)
        rows=[int(k) for k,v in self.emojis.catalog.items() if v.get('show_in_list',True) and v.get('available',True)];self.emoji_page=0
        label=tk.StringVar();ttk.Label(bottom,textvariable=label).pack(side='left')
        def refresh(delta=0):
            self.emoji_page=max(0,min(self.emoji_page+delta,max(0,(len(rows)-1)//32)))
            for child in grid.winfo_children():child.destroy()
            for i,index in enumerate(rows[self.emoji_page*32:(self.emoji_page+1)*32]):
                token=f'[Emoji{index}]';picture=self.emojis.get(token,32)
                button=ttk.Button(grid,text=str(index),image=picture,compound='top',width=4,command=lambda t=token:self.insert_emoji(t));button.grid(row=i//8,column=i%8,padx=2,pady=2)
            label.set(f'{self.emoji_page+1}/{max(1,(len(rows)+31)//32)} · 點選插入輸入框')
        ttk.Button(bottom,text='上一頁',command=lambda:refresh(-1)).pack(side='right');ttk.Button(bottom,text='下一頁',command=lambda:refresh(1)).pack(side='right')
        refresh()

    def insert_emoji(self,token):
        self.entry.insert('insert',token);self.entry.focus_set()

    def cleanup(self,event):
        if event.widget is self:
            if self.emoji_picker and self.emoji_picker.winfo_exists():self.emoji_picker.destroy()
            self.emojis.close()
