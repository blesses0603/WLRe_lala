"""Packet-slot battle formation; selection only, never sends an attack."""
import tkinter as tk
from tkinter import ttk,font as tkfont

ELEMENTS={0:('無','#8665a9'),1:('地','#b58b40'),2:('水','#3f8fc5'),3:('火','#d36056'),4:('風','#5d9e61')}


def cards_from_state(state):
    """Keep server col/row unchanged: cols 1/2 left, 3/4 right."""
    pid=state.get('player',{}).get('role_id')
    cards={}
    for unit in state.get('battle_units',{}).values():
        col,row=unit['col'],unit['row']
        if not (1<=col<=4 and 1<=row<=4):continue
        cards[(col,row)]={**unit,'owned':bool(pid and (unit['pid']==pid or unit['master_id']==pid)),
                          'command_status':state.get('battle',{}).get('commands',{}).get(f'{col}:{row}',{}).get('status'),
                          'dead':unit['hp']<=0,'exited':bool(unit.get('exited'))}
    return cards


class BattleView(ttk.Frame):
    def __init__(self,parent,on_select):
        super().__init__(parent)
        self.on_select=on_select
        self.cards={}
        self.actor=None
        self.target=None
        self.rects=[]
        self.signature=None
        self.canvas=tk.Canvas(self,height=290,width=480,background='#101c2b',highlightthickness=0)
        self.text_font=tkfont.nametofont('TkDefaultFont',root=self)
        self.bold_font=self.text_font.copy();self.bold_font.configure(weight='bold')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Button-1>',self.pick)
        self.base_note='尚無戰鬥資料。\n左右各八格依封包位置排列。'
        self.note=tk.StringVar(value=self.base_note)
        footer=ttk.Frame(self,height=40);footer.pack(fill='x',pady=(4,0));footer.pack_propagate(False)
        ttk.Label(footer,textvariable=self.note,wraplength=350).pack(fill='x')
        self.canvas.bind('<Motion>',self.inspect_unit)
        self.canvas.bind('<Leave>',lambda e:self.note.set(self.base_note))

    def set_state(self,state,actor=None,target=None):
        cards=cards_from_state(state)
        signature=(str(cards),actor,target,state.get('battle',{}).get('active'))
        if signature==self.signature:return
        self.signature=signature
        self.cards=cards;self.actor=actor;self.target=target
        if not cards:self.base_note='尚無戰鬥資料。\n左右各八格依封包位置排列。'
        else:self.base_note=('戰鬥中' if state.get('battle',{}).get('active') else '末次戰場')+'｜點選敵方標示目標。\n移入格子查看完整名稱與 HP。'
        self.note.set(self.base_note)
        self.draw()

    def draw(self):
        c=self.canvas;c.delete('all');self.rects=[]
        w,h=max(1,c.winfo_width()),max(1,c.winfo_height())
        margin,gap,center=4,3,22
        cw=max(1,(w-margin*2-center-gap*2)/4)
        ch=max(1,(h-2*margin-3*gap)/4)
        c.create_text(w/2,h/2,text='VS',fill='#d16d3c',font=('Segoe UI',16,'bold'))
        for col in range(1,5):
            x=margin+(col-1)*(cw+gap)+(center-gap if col>2 else 0)
            for row in range(1,5):
                y=margin+(row-1)*(ch+gap)
                u=self.cards.get((col,row));slot=f'{col}:{row}'
                fill='#183044' if not u else '#203f53'
                if u and (u['dead'] or u['exited']):fill='#737c88'
                outline='#397c98';line=1
                if slot==self.actor:outline='#62c9e0';line=3
                if slot==self.target:outline='#dc8740';line=3
                c.create_rectangle(x,y,x+cw,y+ch,fill=fill,outline=outline,width=line)
                self.rects.append((x,y,x+cw,y+ch,col,row))
                if not u:
                    c.create_text(x+cw/2,y+ch/2,text=self.fit_text(f'{slot} 空位',cw-8),fill='#7292a4',font=self.text_font)
                    continue
                element,color=ELEMENTS.get(u.get('element'),('?', '#888888'))
                c.create_oval(x+5,y+6,x+21,y+22,fill=color,outline='')
                c.create_text(x+13,y+14,text=element,fill='white',font=self.bold_font)
                c.create_text(x+25,y+14,text=self.fit_text(u['name'],cw-30,bold=True),anchor='w',fill='#dce6f1' if u['dead'] or u['exited'] else '#eff7ff',font=self.bold_font)
                if u['dead'] or u['exited']:
                    label='已陣亡' if u['dead'] else '已離場'
                    c.create_text(x+cw/2,y+ch*.62,text=label,fill='white',font=self.bold_font)
                else:
                    c.create_text(x+cw/2,y+ch*.56,text=self.fit_text(f"{u['hp']}/{u['max_hp']}",cw-10),fill='#d1e7f0',font=self.text_font)
                    fraction=max(0,min(1,u['hp']/max(1,u['max_hp'])))
                    c.create_rectangle(x+5,y+ch*.68,x+cw-5,y+ch*.73,fill='#122739',outline='')
                    c.create_rectangle(x+5,y+ch*.68,x+5+(cw-10)*fraction,y+ch*.73,fill='#63a45f' if fraction>.3 else '#d56b54',outline='')
                    status=('已有結果' if u['command_status']=='resolved' else '已送出' if u['command_status']=='sent' else '可操作') if u['owned'] else '目標'
                    c.create_text(x+cw/2,y+ch*.88,text=self.fit_text(status,cw-8),fill='#a7cbdc',font=self.text_font)

    def fit_text(self,text,width,bold=False):
        font=self.bold_font if bold else self.text_font
        if font.measure(text)<=width:return text
        while text and font.measure(text+'…')>width:text=text[:-1]
        return text+'…' if text else ''

    def inspect_unit(self,event):
        for x1,y1,x2,y2,col,row in self.rects:
            if x1<=event.x<=x2 and y1<=event.y<=y2:
                unit=self.cards.get((col,row))
                if unit:
                    status='已陣亡' if unit['dead'] else '已離場' if unit['exited'] else '角色／夥伴' if unit['owned'] else '目標'
                    self.note.set(f"{unit['name']}｜{col}:{row}｜{status}\nHP {unit['hp']}/{unit['max_hp']}")
                else:self.note.set(self.base_note)
                return
        self.note.set(self.base_note)


    def pick(self,event):
        for x1,y1,x2,y2,col,row in self.rects:
            if x1<=event.x<=x2 and y1<=event.y<=y2:
                unit=self.cards.get((col,row))
                if unit and not unit.get('dead',False) and not unit['exited']:self.on_select(f'{col}:{row}',unit['owned'])
                return
