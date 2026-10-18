from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from android_app.widgets import column, label, button, select, row
from wlre.core.efficiency import rates, progress, forecast, STAGES
from wlre.services.items.combat_resources import CAT


class Page(BoxLayout):
    def __init__(self, dashboard):
        super().__init__(orientation='vertical', size_hint_y=None, spacing=dp(8), padding=dp(6))
        self.bind(minimum_height=self.setter('height'))
        self.d = dashboard; self.key = None
    @property
    def state(self): return self.d.state
    def refresh(self): pass


class Overview(Page):
    def __init__(self, d):
        super().__init__(d); self.info = label(); self.add_widget(self.info)
        from android_app.automation_ui import toggle
        self.add_widget(row(button('切換自動戰鬥', lambda: toggle(d.app, d.sid, 'battle')),
                            button('切換自動徘徊', lambda: toggle(d.app, d.sid, 'roaming'))))
        self.add_widget(button('開啟完整 AI／補給設定', lambda: setattr(d.navigation, 'text', 'AI與補給設定')))
    def refresh(self):
        s = self.state; k = s.get('knowledge', {}); p = s.get('player', {})
        rows = [p.get('name', '等待角色同步')]
        profiles = [('角色', k.get('player', {}))] + [
            (CAT['npcs'].get(str(v.get('npc_id')), {}).get('name', '夥伴') +
             ('（出戰）' if v.get('npc_id') == k.get('active_npc_id') else ''), v)
            for v in k.get('companions', {}).values()]
        for name, profile in profiles:
            stats = profile.get('stats', {})
            rows.append(name + ' Lv.' + str(stats.get('level', '—')) + '\n' +
                'HP {}/{} · SP {}/{}'.format(*(stats.get(key, '—') for key in ('hp', 'max_hp', 'sp', 'max_sp'))))
        from wlre.services.battle.auto_battle import summary as battle
        from wlre.services.world.roaming import summary as roaming
        rows += ['自動戰鬥：'+battle(s.get('auto_battle', {})), '自動徘徊：'+roaming(s.get('roaming', {})),
                 '事件：'+('等待伺服器事件結束' if s.get('event_flow', {}).get('blocked') else '待機'),
                 '煉金：'+s.get('alchemy', {}).get('status', '待同步'),
                 '製作：'+s.get('crafting', {}).get('status', '待同步'),
                 '補給：'+str(s.get('inventory', {}).get('field_supply', {}).get('reason', '尚無紀錄'))]
        self.info.text = '\n\n'.join(rows)


class Events(Page):
    def __init__(self, d):
        super().__init__(d); self.info = label(); self.add_widget(self.info)
    def refresh(self): self.info.text = '\n'.join(self.d.data.get('log', [])) or '尚無事件紀錄'


class Efficiency(Page):
    def __init__(self, d):
        super().__init__(d)
        self.subject = select(self, '統計對象', ['等待資料']); self.subject.bind(text=lambda *_: self.render())
        self.unit = select(self, '效率單位', ['分', '時', '秒']); self.unit.bind(text=lambda *_: self.render())
        self.info = label(); self.add_widget(self.info)
        self.add_widget(button('重新統計', lambda: d.send({'type': 'reset_efficiency'}, '重設本帳號的經驗效率統計？')))
        self.lookup = {}
    def refresh(self):
        self.lookup = {r['name']+'｜'+key: r for key, r in self.state.get('efficiency', {}).get('rows', {}).items()}
        self.subject.values = list(self.lookup)
        if self.subject.text not in self.lookup and self.lookup: self.subject.text = next(iter(self.lookup))
        self.render()
    def render(self):
        r = self.lookup.get(self.subject.text)
        if not r: self.info.text = '等待角色經驗資料；首場作為基準'; return
        remaining, percent, reborn = progress(r['exp'], r['level'], r['degree']) if all(r.get(k) is not None for k in ('exp', 'level', 'degree')) else (None, None, None)
        text = [f"{r['name']}｜{STAGES.get(r.get('degree'), '階段未同步')}｜Lv.{r.get('level')}",
                '進度 '+(f'{percent:.1f}%' if percent is not None else '待同步'),
                f"累積經驗 {r.get('exp')}｜本次 +{r['earned']}｜本場 +{r.get('last_gain')}"]
        factor = {'分': 1, '時': 60, '秒': 1/60}[self.unit.text]
        for title, (rate, count) in zip(('總平均', '近10場', '近30場'), rates(r)):
            speed = f'{rate*factor:,.1f}' if rate is not None else '等待樣本'
            text += [f'{title}（{count} 場）：{speed}／{self.unit.text}',
                     '升級：'+forecast(remaining, rate)+'｜一轉190：'+forecast(reborn, rate)]
        self.info.text = '\n\n'.join(text)+'\n\n預估採用已完成戰鬥的有效樣本；未同步時不推算。'
