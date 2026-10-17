"""Read-only overview of the current session; commands stay in their own panels."""
import time
import tkinter as tk
from tkinter import ttk, font as tkfont
from wlre.core.efficiency import rates, progress, forecast
from wlre.services.battle.auto_battle import summary as ai_summary
from wlre.services.battle.party import own_team, player_name
from wlre.services.battle.party_guard import missing
from wlre.services.world.roaming import summary as roaming_summary


def health(stats):
    def value(key):
        return str(stats[key]) if stats.get(key) is not None else '待同步'
    return f"HP {value('hp')}/{value('max_hp')}　SP {value('sp')}/{value('max_sp')}"


def summarize(state, live, guard, now=None):
    """Format only known state; missing data must not look like success or zero HP."""
    player=state.get('player',{});knowledge=state.get('knowledge',{})
    if not player.get('role_id'):
        return dict.fromkeys(('role','activity','ai','roaming','supply','alchemy','crafting','party','efficiency'),'等待登入與角色資料同步')
    stats=dict(knowledge.get('player',{}).get('stats',{}))
    if state.get('battle',{}).get('active'):
        unit=next((u for u in state.get('battle_units',{}).values() if u.get('pid')==player['role_id'] and not u.get('master_id')),None)
        if unit:
            stats.update({k:unit[k] for k in ('hp','sp','max_hp','max_sp','level') if k in unit})
    role=f"{player.get('name','角色')}｜等級 {stats.get('level','待同步')}\n{health(stats)}"
    companions=knowledge.get('companions',{})
    if companions:
        from wlre.services.items.combat_resources import CAT
        rows=[]
        for profile in companions.values():
            s=profile.get('stats',{});npc=profile.get('npc_id')
            name=s.get('name') or CAT['npcs'].get(str(npc),{}).get('name') or '夥伴／坐騎'
            marker='（出戰）' if npc==knowledge.get('active_npc_id') else ''
            rows.append(f"{name}{marker}｜{health(s)}")
        role+='\n'+'\n'.join(rows)
    else:
        role+='\n夥伴／坐騎：'+('尚無資料' if knowledge.get('companions_ready') else '待同步')
    supply=state.get('inventory',{}).get('field_supply',{})
    activity=[]
    if state.get('battle',{}).get('active'):
        activity.append(f"戰鬥中｜第 {state['battle'].get('round',0)} 回合")
    if state.get('local_movement') and state['local_movement'].get('status')=='running':
        activity.append('移動中（本機推算，抵達待確認）')
    if state.get('event_flow',{}).get('blocked'):activity.append('等待伺服器事件結束')
    if supply.get('uncertain'):activity.append('補給結果未確認，已鎖定重複使用')
    elif supply.get('pending'):activity.append('等待補給確認')
    activity.extend(state.get('activities',{}))
    if not live:activity=['已離線｜以下為最後收到的資料']
    elif not activity:activity=['待機｜自動功能狀態見下方']
    alchemy=state.get('alchemy',{});craft=state.get('crafting',{})
    supply_text=('結果未確認' if supply.get('uncertain') else '等待確認' if supply.get('pending') else '已確認' if supply.get('status')=='confirmed' else '尚無補給紀錄')
    if supply.get('reason'):supply_text+='｜'+supply['reason']
    team=own_team(state)
    party=(f"隊長：{player_name(state,team['leader_id'])}｜{len(team['members'])}/4 人" if team else '目前未組隊')
    if guard.get('enabled'):
        absent=missing(state,guard)
        party+='\n必要隊員：'+('缺少 '+ '、'.join(m['name'] for m in absent) if absent else '已到齊')
        if not state.get('auto_battle',{}).get('enabled'):party+='（AI 未啟動）'
    else:party+='\n必要隊員檢查未啟用'
    eff=state.get('efficiency',{});row=eff.get('rows',{}).get('self')
    efficiency='等待角色經驗資料；首場作基準'
    if row:
        rate,_=rates(row)[1]
        remaining=progress(row['exp'],row['level'],row['degree'])[0] if all(row.get(k) is not None for k in ('exp','level','degree')) else None
        elapsed=0
        if live and not eff.get('offline') and row.get('last_time') is not None:
            elapsed=max(0,(time.monotonic() if now is None else now)-row['last_time'])
        speed=f'{rate:,.0f}／分' if rate is not None else '等待樣本'
        efficiency=f"本次 +{row.get('earned',0):,}｜近10場 {speed}\n預估升級：{forecast(remaining,rate,elapsed)}"
    return {
        'role':role,'activity':'\n'.join(activity),
        'ai':ai_summary(state['auto_battle']) if 'auto_battle' in state else '待同步',
        'roaming':roaming_summary(state['roaming']) if 'roaming' in state else '待同步',
        'supply':supply_text,
        'alchemy':f"{alchemy.get('status','待同步')}｜完成 {alchemy.get('completed',0)}/{alchemy.get('requested',0)}",
        'crafting':f"{craft.get('status','待同步')}｜本次完成 {craft.get('completed',0)} 項",
        'party':party,'efficiency':efficiency,
    }


class OverviewPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.values={};self.signature=None
        self.labels={};self.full_values={};self.cards={}
        self.columnconfigure(0,weight=1)
        layout=(
            ('role','角色與夥伴',None,3,84),
            ('activity','目前活動',None,1,38),
            ('ai','自動戰鬥','ai_page',1,32),
            ('roaming','自動徘徊','roam_page',1,32),
            ('supply','補給紀錄',None,1,32),
            ('alchemy','自動煉金','alchemy_panel',1,32),
            ('crafting','家具製作','crafting_panel',1,32),
            ('party','隊伍檢查','party_panel',2,48),
            ('efficiency','經驗效率','efficiency_panel',2,48),
        )
        self.actions={}
        for row,(key,title,destination,lines,height) in enumerate(layout):
            self.rowconfigure(row,minsize=height,weight=1 if key=='role' else 0)
            frame=ttk.Frame(self,padding=(8,3))
            frame.grid(row=row,column=0,sticky='nsew')
            frame.grid_propagate(False)
            frame.columnconfigure(1,weight=1)
            frame.rowconfigure(0,weight=1)
            self.cards[key]=frame
            ttk.Label(frame,text=title,style='Section.TLabel',width=9,anchor='nw').grid(row=0,column=0,sticky='nw',padx=(0,6))
            value=tk.StringVar();self.values[key]=value
            label=ttk.Label(frame,textvariable=value,justify='left',anchor='w')
            label.grid(row=0,column=1,sticky='nsew')
            self.labels[key]=(label,lines)
            label.bind('<Configure>',lambda e,k=key:self.fit_value(k))
            label.bind('<Double-1>',lambda e,k=key:self.show_detail(k))
            if destination:
                callback=lambda d=destination:self.open_panel(d)
                text='開啟'
            elif key=='role':callback=app.open_resources;text='包包'
            elif key=='supply':callback=lambda:self.open_panel('ai_page',settings=True);text='設定'
            else:callback=lambda k=key:self.show_detail(k);text='詳情'
            button=ttk.Button(frame,text=text,width=4,command=callback,padding=(3,2))
            button.grid(row=0,column=2,sticky='e',padx=(6,0))
            self.actions[key]=button
        self.after(1000,self.tick)

    def open_panel(self,name,settings=False):
        if name in ('ai_page','roam_page'):
            self.app.left_tabs.select(self.app.battle_page)
            self.app.battle_tabs.select(getattr(self.app,name))
            if settings:
                from wlre.ui.auto_battle_ui import open_settings
                editor=open_settings(self.app)
                editor.tabs.select(editor.recovery_pages['hp'])
        else:self.app.left_tabs.select(getattr(self.app,name))

    def update_state(self,state):
        self.state=state;self.refresh()

    def refresh(self):
        values=summarize(getattr(self,'state',{}),self.app.live_active,self.app.ai_settings.get('party_guard',{}))
        if values!=self.signature:
            self.signature=values
            self.full_values=values
            for key in values:self.fit_value(key)

    def fit_value(self,key):
        label,limit=self.labels[key]
        text=self.full_values.get(key,'等待同步')
        lines=text.splitlines()
        if len(lines)>limit:
            lines=lines[:limit-1]+['｜'.join(lines[limit-1:])]
        font=tkfont.nametofont('TkDefaultFont',root=self)
        width=max(1,label.winfo_width()-4)
        height=max(1,label.winfo_height())
        visible=max(1,min(limit,height//max(1,font.metrics('linespace'))))
        lines=lines[:visible-1]+['｜'.join(lines[visible-1:])] if len(lines)>visible else lines
        fitted=[]
        for line in lines:
            if font.measure(line)>width:
                low,high=0,len(line)
                while low<high:
                    middle=(low+high+1)//2
                    if font.measure(line[:middle]+'…')<=width:low=middle
                    else:high=middle-1
                line=line[:low]+'…'
            fitted.append(line)
        self.values[key].set('\n'.join(fitted))

    def show_detail(self,key):
        window=tk.Toplevel(self)
        window.title('狀態詳情')
        window.geometry('640x420')
        body=ttk.Frame(window)
        body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=1);body.rowconfigure(0,weight=1)
        # A read-only detail window keeps the dashboard itself fixed in size.
        text=tk.Text(body,wrap='word',font='TkDefaultFont',padx=12,pady=12)
        text.grid(row=0,column=0,sticky='nsew')
        text.insert('1.0',self.full_values.get(key,'等待同步'));text.configure(state='disabled')
        ttk.Button(body,text='關閉',command=window.destroy).grid(row=1,column=0,pady=8)
        self.app.theme.attach(window)

    def tick(self):
        if self.winfo_exists():
            if self.winfo_ismapped():self.refresh()
            self.after(1000,self.tick)
