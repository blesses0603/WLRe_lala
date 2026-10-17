"""Read-only overview of the current session; commands stay in their own panels."""
import time
import tkinter as tk
from tkinter import ttk
from wlre.ui.theme import group
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
        canvas=tk.Canvas(self,highlightthickness=0,borderwidth=0)
        scroll=ttk.Scrollbar(self,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        body=ttk.Frame(canvas,padding=8)
        item=canvas.create_window(0,0,window=body,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        ttk.Label(body,text='狀態總覽',style='Heading.TLabel').pack(anchor='w',pady=(0,6))
        for key,title,destination in (
            ('role','角色與夥伴',None),('activity','目前活動',None),
            ('ai','自動戰鬥','ai_page'),('roaming','自動徘徊','roam_page'),
            ('supply','補給紀錄',None),('alchemy','自動煉金','alchemy_panel'),
            ('crafting','家具製作','crafting_panel'),('party','隊伍與必要隊員','party_panel'),
            ('efficiency','經驗效率','efficiency_panel')):
            frame=group(body,text=title,padding=(8,5));frame.pack(fill='x',pady=(0,5))
            value=tk.StringVar();self.values[key]=value
            label=ttk.Label(frame,textvariable=value,justify='left',wraplength=450)
            label.pack(side='left',fill='x',expand=True)
            label.bind('<Configure>',lambda e,w=label:w.configure(wraplength=max(80,e.width)))
            if destination:
                ttk.Button(frame,text='查看',command=lambda d=destination:self.open_panel(d)).pack(side='right',padx=(6,0))
            elif key in ('role','supply'):
                ttk.Button(frame,text='包包／特技' if key=='role' else '補給設定',command=app.open_resources if key=='role' else lambda:self.open_panel('ai_page',settings=True)).pack(side='right',padx=(6,0))
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
            for key,value in values.items():self.values[key].set(value)

    def tick(self):
        if self.winfo_exists():
            if self.winfo_ismapped():self.refresh()
            self.after(1000,self.tick)
