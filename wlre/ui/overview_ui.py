"""Session overview with direct battle and roaming controls."""
import time
import tkinter as tk
from tkinter import ttk, font as tkfont
from wlre.ui.halo_button import HaloButton
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
        return dict.fromkeys(('role','activity','ai','roaming','supply','alchemy','crafting','party','efficiency','expedition'),'等待登入與角色資料同步')
    stats=dict(knowledge.get('player',{}).get('stats',{}))
    if state.get('battle',{}).get('active'):
        unit=next((u for u in state.get('battle_units',{}).values() if u.get('pid')==player['role_id'] and not u.get('master_id')),None)
        if unit:
            stats.update({k:unit[k] for k in ('hp','sp','max_hp','max_sp','level') if k in unit})
    role=f"{player.get('name','角色')}｜等級 {stats.get('level','待同步')}\n{health(stats)}"
    companions=knowledge.get('companions',{})
    active=knowledge.get('active_npc_id')
    profile=next((p for p in companions.values() if active is not None and p.get('npc_id')==active),None)
    if profile is not None:
        from wlre.services.items.combat_resources import CAT
        s=profile.get('stats',{});npc=profile.get('npc_id')
        name=s.get('name') or CAT['npcs'].get(str(npc),{}).get('name') or '夥伴'
        role+=f"\n{name}（出戰）｜{health(s)}"
    elif active:
        role+='\n出戰夥伴：資料待同步'
    else:
        role+='\n夥伴：未出戰'
    supply=state.get('inventory',{}).get('field_supply',{})
    activity=[]
    if state.get('battle',{}).get('active'):
        activity.append(f"戰鬥中｜第 {state['battle'].get('round',0)} 回合")
    if state.get('local_movement') and state['local_movement'].get('status')=='running':
        activity.append('移動中')
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
    expedition=state.get('expedition',{})
    active_teams=[t for t in expedition.get('teams',{}).values() if t.get('quest')]
    expedition_text=('自動派遣已啟用' if expedition.get('enabled') else '自動派遣未啟用')
    if not live: expedition_text='已離線｜'+expedition_text
    if not expedition.get('ready') or not expedition.get('outpost_ready'):
        expedition_text+='｜資料待同步'
    elif active_teams:
        clock=time.monotonic() if now is None else now
        due=[max(0,t['due']-clock) for t in active_teams if t.get('due') is not None]
        timing=('可領獎' if min(due)==0 else f'最近完成 {min(due)/3600:.1f} 小時') if due else '時間待同步'
        expedition_text+=f"\n遠征中 {len(active_teams)} 隊｜{timing}"
    else:
        expedition_text+='\n目前沒有進行中的遠征'
    if expedition.get('uncertain'):
        expedition_text+='｜結果未確認'
    elif expedition.get('enabled') and expedition.get('status'):
        expedition_text+='｜'+expedition['status']
    return {
        'role':role,'activity':'\n'.join(activity),
        'ai':ai_summary(state['auto_battle']) if 'auto_battle' in state else '待同步',
        'roaming':roaming_summary(state['roaming']) if 'roaming' in state else '待同步',
        'supply':supply_text,
        'alchemy':f"{alchemy.get('status','待同步')}｜完成 {alchemy.get('completed',0)}/{alchemy.get('requested',0)}",
        'crafting':f"{craft.get('status','待同步')}｜本次完成 {craft.get('completed',0)} 項",
        'party':party,'efficiency':efficiency,'expedition':expedition_text,
    }


class OverviewPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.values={};self.signature=None
        self.labels={};self.full_values={};self.cards={}
        for column in range(6):
            self.columnconfigure(column,weight=1,uniform='overview')
        layout=(
            ('role','角色與夥伴',None,3,0,0,3,100),
            ('activity','目前活動',None,3,0,3,3,100),
            ('ai','自動戰鬥',None,3,1,0,2,100),
            ('roaming','自動徘徊',None,3,1,2,2,100),
            ('expedition','遠征','expedition_panel',3,1,4,2,100),
            ('supply','補給紀錄',None,2,2,0,2,76),
            ('alchemy','煉金','alchemy_panel',2,2,2,2,76),
            ('crafting','製作','crafting_panel',2,2,4,2,76),
            ('party','隊伍檢查','party_panel',2,3,0,3,76),
            ('efficiency','經驗效率','efficiency_panel',2,3,3,3,76),
        )
        self.actions={}
        for key,title,destination,lines,row,col,span,height in layout:
            self.rowconfigure(row,minsize=height,weight=1 if row in (0,1) else 0)
            frame=ttk.Frame(self,padding=(10,4))
            frame._surface_fill=(17,46,64,220) if key in ('ai','roaming','expedition') else (13,32,48,210)
            frame.grid(row=row,column=col,columnspan=span,sticky='nsew',padx=3,pady=3)
            frame.grid_propagate(False);frame.columnconfigure(0,weight=1);frame.rowconfigure(1,weight=1)
            self.cards[key]=frame
            ttk.Label(frame,text=title,style='Section.TLabel',anchor='w').grid(row=0,column=0,sticky='w')
            tools=ttk.Frame(frame);tools.grid(row=0,column=1,sticky='e')
            value=tk.StringVar();self.values[key]=value
            label=ttk.Label(frame,textvariable=value,justify='left',anchor='w')
            label.grid(row=1,column=0,columnspan=2,sticky='nsew',pady=(2,0))
            self.labels[key]=(label,lines)
            label.bind('<Configure>',lambda e,k=key:self.fit_value(k))
            if key in ('ai','roaming','expedition'):
                if key=='ai':
                    self.ai_settings_button=ttk.Button(tools,text='AI設定',width=6,padding=(3,2),command=self.open_ai_settings)
                    self.ai_settings_button.pack(side='left',padx=(0,6))
                elif key=='expedition':
                    self.expedition_settings_button=ttk.Button(tools,text='遠征設定',width=6,padding=(3,2),
                        command=lambda:self.open_panel('expedition_panel'))
                    self.expedition_settings_button.pack(side='left',padx=(0,6))
                button=HaloButton(tools,command=lambda k=key:self.toggle(k));button.pack(side='left')
            else:
                if destination:callback=lambda d=destination:self.open_panel(d);text='開啟'
                elif key=='role':callback=app.open_resources;text='包包'
                elif key=='supply':callback=lambda:self.open_panel(None,settings=True);text='設定'
                else:continue
                button=ttk.Button(tools,text=text,width=4,command=callback,padding=(3,2));button.pack(side='left')
            self.actions[key]=button
        self.after(1000,self.tick)

    def open_ai_settings(self):
        from wlre.ui.auto_battle_ui import open_settings
        return open_settings(self.app)

    def toggle(self,key):
        state=self.app.snapshot
        section={'ai':'auto_battle','roaming':'roaming','expedition':'expedition'}[key]
        active=self.app.live_active and state.get(section,{}).get('enabled',False)
        if key=='ai':
            command={'type':'stop_auto_battle'} if active else {'type':'start_auto_battle','settings':self.app.ai_settings}
            self.app.send(command)
        elif key=='expedition':
            if active:self.app.send({'type':'stop_expedition'})
            else:self.app.expedition_panel.start()
        elif active:self.app.send({'type':'stop_roaming'})
        else:self.app.start_roaming()

    def open_panel(self,name,settings=False):
        if settings:
            editor=self.open_ai_settings()
            editor.tabs.select(editor.recovery_tab)
        else:self.app.left_tabs.select(getattr(self.app,name))

    def update_state(self,state):
        self.state=state;self.refresh()

    def refresh(self):
        state=getattr(self,'state',{})
        for key,section in (('ai','auto_battle'),('roaming','roaming'),('expedition','expedition')):
            self.actions[key].set_active(self.app.live_active and state.get(section,{}).get('enabled',False))
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

    def tick(self):
        if self.winfo_exists():
            if self.winfo_ismapped():self.refresh()
            self.after(1000,self.tick)
