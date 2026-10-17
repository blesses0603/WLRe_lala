"""Packet-slot battle formation; selection only, never sends an attack."""
import tkinter as tk
from tkinter import ttk

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
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Button-1>',self.pick)
        self.note=tk.StringVar(value='尚無戰鬥資料。左右各八格依封包位置排列。')
        ttk.Label(self,textvariable=self.note,wraplength=350).pack(fill='x',pady=(4,0))

    def set_state(self,state,actor=None,target=None):
        cards=cards_from_state(state)
        signature=(str(cards),actor,target,state.get('battle',{}).get('active'))
        if signature==self.signature:return
        self.signature=signature
        self.cards=cards;self.actor=actor;self.target=target
        if not cards:self.note.set('尚無戰鬥資料。左右各八格依封包位置排列。')
        else:self.note.set(('戰鬥中' if state.get('battle',{}).get('active') else '末次戰場')+'｜自動辨識本機角色與夥伴；點選敵方可標示目標位置。')
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
                    c.create_text(x+cw/2,y+ch/2,text=f'{slot} 空位',fill='#7292a4',font=('Microsoft JhengHei UI',-14))
                    continue
                element,color=ELEMENTS.get(u.get('element'),('?', '#888888'))
                c.create_oval(x+5,y+6,x+21,y+22,fill=color,outline='')
                c.create_text(x+13,y+14,text=element,fill='white',font=('Microsoft JhengHei UI',-14,'bold'))
                c.create_text(x+25,y+14,text=u['name'],width=max(10,cw-28),anchor='w',fill='#dce6f1' if u['dead'] or u['exited'] else '#eff7ff',font=('Microsoft JhengHei UI',-14,'bold'))
                if u['dead'] or u['exited']:
                    label='已陣亡' if u['dead'] else '已離場'
                    c.create_text(x+cw/2,y+ch*.62,text=label,fill='white',font=('Microsoft JhengHei UI',-14,'bold'))
                else:
                    c.create_text(x+cw/2,y+ch*.56,text=f"HP {u['hp']}/{u['max_hp']}",fill='#d1e7f0',font=('Segoe UI',-14))
                    fraction=max(0,min(1,u['hp']/max(1,u['max_hp'])))
                    c.create_rectangle(x+5,y+ch*.68,x+cw-5,y+ch*.73,fill='#122739',outline='')
                    c.create_rectangle(x+5,y+ch*.68,x+5+(cw-10)*fraction,y+ch*.73,fill='#63a45f' if fraction>.3 else '#d56b54',outline='')
                    c.create_text(x+cw/2,y+ch*.88,text=f"{slot} · {('已有結果' if u['command_status']=='resolved' else '已送出' if u['command_status']=='sent' else '可操作') if u['owned'] else '目標'}",fill='#a7cbdc',font=('Microsoft JhengHei UI',-14))

    def pick(self,event):
        for x1,y1,x2,y2,col,row in self.rects:
            if x1<=event.x<=x2 and y1<=event.y<=y2:
                unit=self.cards.get((col,row))
                if unit and not unit.get('dead',False) and not unit['exited']:self.on_select(f'{col}:{row}',unit['owned'])
                return
