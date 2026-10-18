"""Companion selection and authoritative deployment status."""
import tkinter as tk
from tkinter import ttk

from wlre.services.items.combat_resources import CAT
from wlre.ui.layout import heading, scroll_table
from wlre.services.battle.companions import problem


class CompanionPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=6)
        self.app = app
        self.state = {}
        self.signature = None
        heading(self, '選擇夥伴出戰', '選取夥伴查看能力與目前出戰狀態。')
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, wraplength=680).pack(fill='x', pady=(0, 6))
        frame, self.companions = scroll_table(
            self, ('index', 'name', 'level', 'hp', 'sp', 'status'),
            ('編號', '夥伴', '等級', 'HP', 'SP', '狀態'),
            (48, 170, 50, 90, 90, 100), height=5)
        frame.pack(fill='both', expand=True)
        self.companions.bind('<<TreeviewSelect>>', lambda event: self.select())
        self.detail = tk.StringVar(value='請從清單選擇夥伴。')
        ttk.Label(self, textvariable=self.detail, wraplength=680).pack(fill='x', pady=8)
        buttons = ttk.Frame(self)
        buttons.pack(fill='x')
        self.deploy = ttk.Button(buttons, text='設為出戰', command=lambda: self.act('deploy'), state='disabled')
        self.deploy.pack(side='left')
        self.rest = ttk.Button(buttons, text='休息', command=lambda: self.act('rest'), state='disabled')
        self.rest.pack(side='left', padx=6)
        self.notice = tk.StringVar(value='選取後按「設為出戰」，結果以伺服器回覆為準。')
        ttk.Label(self, textvariable=self.notice,
                  style='Muted.TLabel', wraplength=680).pack(fill='x', pady=(6, 0))
        self.render({})

    @staticmethod
    def name(profile):
        return (profile.get('stats', {}).get('name')
                or CAT['npcs'].get(str(profile.get('npc_id')), {}).get('name')
                or f"夥伴 #{profile.get('index', '?')}")

    @staticmethod
    def amount(stats, key):
        value = stats.get(key)
        maximum = stats.get('max_' + key)
        return '待同步' if value is None else f'{value}/{maximum}' if maximum is not None else str(value)

    def render(self, state):
        self.state = state
        knowledge = state.get('knowledge', {})
        profiles = knowledge.get('companions', {})
        active = knowledge.get('active_npc_id')
        live = bool(self.app.live_active)
        self.status.set(('' if live else '已離線｜以下為最後收到的資料。') + (
            f'已同步 {len(profiles)} 位夥伴；出戰狀態依伺服器回覆顯示。'
            if knowledge.get('companions_ready') else '等待夥伴清單同步。'))
        signature = repr((profiles, active))
        if signature != self.signature:
            self.signature = signature
            selected = self.companions.selection()
            self.companions.delete(*self.companions.get_children())
            for index, profile in sorted(profiles.items(), key=lambda item: int(item[0])):
                stats = profile.get('stats', {})
                status = '出戰中' if active is not None and profile.get('npc_id') == active else '未出戰'
                self.companions.insert('', 'end', iid=str(index), values=(
                    index, self.name(profile), stats.get('level', '待同步'),
                    self.amount(stats, 'hp'), self.amount(stats, 'sp'), status))
            if selected and self.companions.exists(selected[0]):
                self.companions.selection_set(selected[0])
        self.select()

    def select(self):
        selected = self.companions.selection()
        profile = self.state.get('knowledge', {}).get('companions', {}).get(selected[0]) if selected else None
        if profile is None:
            self.detail.set('請從清單選擇夥伴。')
            self.deploy.configure(state='disabled')
            self.rest.configure(state='disabled')
            return
        stats = profile.get('stats', {})
        self.detail.set(f"已選擇：{self.name(profile)}｜忠誠 {stats.get('faith', '待同步')}\n" + '｜'.join(
            f'{label} {stats.get(key, "待同步")}'
            for key, label in (('str', '力量'), ('con', '體質'), ('int', '智力'), ('wis', '智慧'), ('agi', '敏捷'))))
        reasons = {}
        for action, button in (('deploy', self.deploy), ('rest', self.rest)):
            reasons[action] = problem(self.state, int(selected[0]), profile['npc_id'], action)
            button.configure(state='normal' if self.app.live_active and not reasons[action] else 'disabled')
        if not self.app.live_active:
            self.notice.set('請先登入後再操作。')
        elif all(reasons.values()):
            self.notice.set(reasons['rest'] if self.state.get('knowledge', {}).get('active_npc_id') == profile['npc_id'] else reasons['deploy'])
        else:
            self.notice.set('選取後按「設為出戰」或「休息」，結果以伺服器回覆為準。')

    def act(self, action):
        selected = self.companions.selection()
        if not selected:
            return
        profile = self.state.get('knowledge', {}).get('companions', {}).get(selected[0])
        if not profile or not self.app.live_active:
            return
        reason = problem(self.state, int(selected[0]), profile['npc_id'], action)
        if reason:
            self.notice.set(reason)
            return
        self.app.send({'type': 'companion', 'action': action, 'index': int(selected[0]), 'npc_id': profile['npc_id']})
        self.notice.set('已提交夥伴指令，等待伺服器確認。')
