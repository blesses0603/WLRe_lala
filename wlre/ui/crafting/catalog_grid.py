"""Crafting catalog icon grid and visibility updates.

Keep the original widget geometry and presentation rules intact. Collaborators
are supplied by CraftingBrowser so existing callers and test patch points work.
"""
import math
from PIL import Image, ImageDraw, ImageTk
from tkinter import ttk


def build_catalog_grid(self, middle, w, embedded):
    self.grid=ttk.Frame(middle);self.grid.pack(fill='both',expand=True)
    self.cards=[]
    self.favorite_images={}
    for selected in (False,True):
        image=Image.new('RGBA',(72,72));draw=ImageDraw.Draw(image)
        points=[]
        for step in range(121):
            t=step/120*math.tau
            x=16*math.sin(t)**3;y=13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t)
            points.append((36+x*1.8,31-y*1.8))
        if selected:draw.polygon(points,fill='#ffd784')
        else:draw.line(points,fill='#9acddd',width=5,joint='curve')
        self.favorite_images[selected]=ImageTk.PhotoImage(image.resize((18,18),Image.Resampling.LANCZOS),master=w)
    columns=4
    for i in range(self.page_size):
        cell=ttk.Frame(self.grid,padding=3);cell.grid(row=i//columns,column=i%columns,sticky='nsew',padx=2,pady=2)
        self.grid.columnconfigure(i%columns,weight=1,uniform='cards');self.grid.rowconfigure(i//columns,weight=1,uniform='cards')
        footer=ttk.Frame(cell);footer.pack(side='bottom',fill='x',pady=(2,0))
        favorite=ttk.Button(footer,text='收藏',image=self.favorite_images[False],width=2,padding=(2,1),command=lambda n=i:self.toggle_favorite(n))
        favorite.pack(side='right',padx=(2,0))
        status=ttk.Label(footer,anchor='w',style='Muted.TLabel',width=1);status.pack(side='left',fill='x',expand=True)
        button=ttk.Button(cell,compound='top',padding=(3,2) if embedded else (9,5),command=lambda n=i:self.pick_card(n));button.pack(fill='both',expand=True)
        self.cards.append({'frame':cell,'button':button,'favorite':favorite,'status':status,'id':None,'image':None})
    

def render_catalog_grid(self, force=False, *, recipes, confirmed_unlocked,
                        room_known, tool_status, item_name, availability):
    q=self.search.get().strip().casefold();favs=set(self.favorite_store.ids)
    rows=[r for r in recipes.values() if confirmed_unlocked(r) and (self.filter_key=='all' or self.filter_key=='favorites' and r['item_id'] in favs or str(r['tool_id'])==self.filter_key) and q in (item_name(r['item_id'])+' '+str(r['item_id'])+' '+item_name(r['tool_id'])).casefold()]
    if self.only_tools.get() and room_known(self.state) and self.filter_key!='favorites':rows=[r for r in rows if tool_status(self.state,r['tool_id'])=='已擺放']
    self.rows=rows;pages=max(1,math.ceil(len(rows)/self.page_size));self.page=min(self.page,pages-1)
    self.page_label.set(f'{self.page+1}/{pages} · 已解鎖 {len(rows)} 項')
    visible=rows[self.page*self.page_size:(self.page+1)*self.page_size]
    signature=(tuple((r['item_id'],availability(self.state,r)[0],r['item_id'] in favs) for r in visible),self.selected)
    if not force and signature==self.grid_key:return
    self.grid_key=signature
    for i,card in enumerate(self.cards):
        if i>=len(visible):card['frame'].grid_remove();card['id']=None;continue
        card['frame'].grid();r=visible[i];sid=r['item_id'];card['id']=sid
        im=card['image']=self.icons.get(sid,32 if self.embedded else 56);name=item_name(sid)
        # Fixed-size grid and bounded 2-line names, no control per all recipes.
        limit=5 if self.embedded else 7
        caption=name if len(name)<=limit else name[:limit-1]+'…'
        card['button'].configure(text=caption,image=im)
        card['favorite'].configure(text='取消收藏' if sid in favs else '收藏',image=self.favorite_images[sid in favs])
        status=availability(self.state,r)[0]
        card['status'].configure(text=('✓ ' if sid==self.selected else '')+status)
    if self.selected not in [r['item_id'] for r in visible]:self.selected=visible[0]['item_id'] if visible else None;self.detail_key=None
    self.refresh_detail()

