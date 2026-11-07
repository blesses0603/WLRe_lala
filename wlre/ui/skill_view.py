"""Independent confirmed-skill window; never constructs inventory/storage UI."""
import tkinter as tk
from tkinter import ttk, messagebox
from wlre.ui.window_layout import configure_dialog
from wlre.ui.layout import heading
from wlre.ui.skill_browser import SkillBrowser
from wlre.services.items.combat_resources import CAT, field_context, learned_command
from wlre.services.battle.battle_commands import owned_units


class SkillView:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('角色／夥伴特技')
        configure_dialog(self.window, 1040, 700)
        self.signature = None
        header = ttk.Frame(self.window, padding=(12, 10, 12, 0))
        header.pack(fill='x')
        heading(header, '角色與夥伴特技', '只顯示伺服器已確認的特技，點選僅查看。')
        bar = ttk.Frame(self.window, padding=(12, 0, 12, 8))
        bar.pack(fill='x')
        ttk.Label(bar, text='搜尋名稱／ID').pack(side='left')
        self.query = tk.StringVar()
        ttk.Entry(bar, textvariable=self.query, width=25).pack(side='left', padx=6)
        ttk.Button(bar, text='更新顯示', command=self.refresh).pack(side='left')
        self.status = tk.StringVar()
        ttk.Label(self.window, textvariable=self.status, wraplength=970).pack(fill='x', padx=10)
        self.skill_browser = SkillBrowser(self.window, self.use_skill)
        self.skill_browser.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        self.skills = self.skill_browser.list
        self.query.trace_add('write', lambda *args: self.refresh())
        self.set_state(app.snapshot)

    def refresh(self):
        self.signature = None
        self.set_state(self.app.snapshot)

    def actors(self,state):
        if state.get('battle',{}).get('active'):return owned_units(state,False)
        k=state.get('knowledge',{});context,role=field_context(state);role.update(col=0,row=0)
        actors=[role] if state.get('player',{}).get('role_id') else []
        for profile in k.get('companions',{}).values():
            actors.append({'col':0,'row':0,'pid':profile['npc_id'],'master_id':state['player']['role_id'],
                'npc_index':profile['index'],'name':CAT['npcs'].get(str(profile['npc_id']),{}).get('name','夥伴'),
                'equips':profile.get('equips',[]),**profile.get('stats',{})})
        return actors

    def set_state(self, state):
        from wlre.services.items.live_combat_catalog import source_token
        token = source_token()
        signature = (token, self.app.live_active, str(state.get('player')),
                     str(state.get('knowledge')), str(state.get('inventory')), str(state.get('battle_units')),
                     str(state.get('battle')), self.query.get())
        if signature == self.signature:
            return
        self.signature = signature
        knowledge = state.get('knowledge', {})
        self.status.set(('角色特技已同步' if knowledge.get('player', {}).get('ready') else '等待角色特技同步')
                        + ('｜官方戰鬥資料已同步' if token is not None else '｜官方戰鬥資料尚未同步'))
        self.skill_browser.render(state, self.actors(state), self.query.get().casefold(), self.app.live_active)

    def use_skill(self):
        selected=self.skills.selection()
        if not selected or selected[0] not in self.skill_browser.skill_map:return
        actor,sid=self.skill_browser.skill_map[selected[0]];state=self.app.snapshot
        if not self.app.live_active:
            messagebox.showinfo('特技','請先登入角色',parent=self.window);return
        try:
            if not state.get('battle',{}).get('active'):raise ValueError('請在可下令的戰鬥回合施放特技')
            target=self.app.priority_target
            data=CAT['skills'].get(str(sid),{})
            if data.get('TargetKind') in (1,3,5):target=None
            cmd=learned_command(state,actor,sid,target)
            cmd.update(battle_count=state['battle_count'],round=state['battle']['round'])
            self.app.send(cmd)
        except (ValueError,KeyError) as exc:messagebox.showinfo('特技',str(exc),parent=self.window)
