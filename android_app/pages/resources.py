from kivy.metrics import dp
from kivy.uix.gridlayout import GridLayout
from android_app.pages.general import Page
from android_app.widgets import column, label, button, row, field, select, pick, dialog
from android_app.assets import item_image
from wlre.services.items.combat_resources import (CAT, item_name, available, heal_effects,
    field_context, food_command, skill_rows, learned_command)
from wlre.services.battle.battle_commands import owned_units, slot, action_command, ACTIONS


def actors(state, include_inactive=False):
    if state.get('battle', {}).get('active'): return owned_units(state, False)
    context, actor = field_context(state)
    result = list(context.get('battle_units', {}).values()) if state.get('player', {}).get('role_id') else []
    if include_inactive:
        existing = {a.get('npc_index') for a in result}
        for profile in state.get('knowledge', {}).get('companions', {}).values():
            if profile.get('index') in existing: continue
            result.append(dict(col=0, row=0, pid=profile.get('npc_id'), master_id=state.get('player', {}).get('role_id'),
                npc_index=profile.get('index'), name=CAT['npcs'].get(str(profile.get('npc_id')), {}).get('name','夥伴'),
                equips=profile.get('equips', []), **profile.get('stats', {})))
    return result


def actor_label(actor): return actor.get('name') or ('夥伴' if actor.get('master_id') else '角色')


def battle_guard(command, state):
    return dict(command, battle_count=state.get('battle_count'), round=state.get('battle', {}).get('round'))


class Resources(Page):
    def __init__(self, d):
        super().__init__(d); self.offset = 0
        self.kind = select(self, '顯示', ['包包', '已確認特技'])
        self.query = field(self, '搜尋名稱／ID')
        self.info = label(); self.add_widget(self.info)
        self.add_widget(button('使用 HP／SP 藥水儲存槽', self.storage))
        self.rows = column(); self.add_widget(self.rows)
        self.add_widget(row(button('上一頁', lambda: self.move(-1)), button('下一頁', lambda: self.move(1))))
        self.kind.bind(text=lambda *_: self.find()); self.query.bind(text=lambda *_: self.find())
    def find(self): self.offset = 0; self.key = None; self.refresh()
    def move(self, delta): self.offset = max(0, self.offset+delta); self.key = None; self.refresh()
    def refresh(self):
        s = self.state; inv = s.get('inventory', {})
        key = (str(inv), str(s.get('knowledge')), str(s.get('battle_units')), self.query.text, self.kind.text, self.offset)
        if key == self.key: return
        self.key = key; q = self.query.text.casefold()
        self.rows.clear_widgets()
        if self.kind.text == '包包':
            data = [v for _, v in sorted(inv.get('items', {}).items(), key=lambda pair: int(pair[0]))
                    if q in (item_name(v['item_id'])+str(v['item_id'])).casefold()]
        else:
            data = [(a, skill) for a in actors(s, True) for skill in skill_rows(s, a)
                    if q in (actor_label(a)+skill['name']+str(skill['id'])).casefold()]
        pages = max(1, (len(data)+14)//15); self.offset = min(self.offset, pages-1)
        self.info.text = ('包包已同步' if inv.get('ready') else '等待包包同步')+' · '+('數量可靠' if inv.get('reliable') else '數量未確認')+f'\n{self.offset+1}/{pages} 頁 · {len(data)} 項'
        for value in data[self.offset*15:self.offset*15+15]:
            if self.kind.text == '包包':
                index = value['index']; sid = value['item_id']
                effects = '／'.join(f'{k.upper()}+{v}' for k, v in heal_effects(sid).items())
                text = f'#{index} {item_name(sid)} ×{value["count"]}\n可用 {available(inv, str(index))} · {effects}'
                self.rows.add_widget(row(item_image(sid), button(text, lambda v=value: self.use_item(v), 68)))
                self.rows.children[0].height = dp(68)
            else:
                actor, skill = value
                text = actor_label(actor)+'｜'+skill['name']+f" Lv.{skill['level']} · SP {skill['sp']}\n"+('；'.join(skill['reasons']) or '基礎條件可用')+' · '+skill['source']
                self.rows.add_widget(button(text, lambda a=actor, v=skill: self.use_skill(a, v), 90))
    def storage(self):
        entries = [((a.get('npc_index',0),res),actor_label(a)+' 補'+res.upper()+' · 儲存槽 '+
                    str(self.state.get('potion_storage',{}).get(res,{}).get('value','待同步')))
                    for a in actors(self.state) for res in ('hp','sp')]
        def choose(value):
            index,resource=value
            self.d.send(dict(type='field_storage',npc_index=index,resource=resource), '確認使用藥水儲存槽補給？')
        pick('藥水儲存槽補給（非戰鬥）',entries,choose)
    def use_item(self, item):
        body = column(); body.add_widget(label(item_name(item['item_id'])+'｜選擇補給資源與目標'))
        popup = None
        state = self.state
        targets = actors(state)
        for target in targets:
            for resource in ('hp', 'sp'):
                def use(t=target, r=resource):
                    try:
                        if state.get('battle', {}).get('active'):
                            owned = [a for a in owned_units(state) if slot(a) not in state['battle'].get('commands', {})]
                            if not owned: raise ValueError('本回合沒有尚未下令的可操作單位')
                            cmd = food_command(state, owned[0], r, item['item_id'], slot(t), index=item['index'])
                            cmd = battle_guard(cmd, state)
                        else:
                            context, actor = field_context(state)
                            cmd = food_command(context, actor, r, item['item_id'], slot(t), True, index=item['index'])
                            cmd['npc_index'] = t.get('npc_index', 0)
                        self.d.send(cmd, '確認使用 '+item_name(item['item_id'])+' 補給 '+actor_label(t)+'？')
                        popup.dismiss()
                    except (ValueError, KeyError, TypeError) as exc: self.d.message.text = str(exc)
                body.add_widget(button(actor_label(target)+' 補'+resource.upper(), use))
        popup = dialog('使用道具', body)
    def use_skill(self, actor, skill):
        if not self.state.get('battle', {}).get('active'):
            self.d.message.text = '手動特技需在戰鬥回合內使用；生活與被動特技僅供檢視'; return
        def target(key):
            try:
                command = learned_command(self.state, actor, skill['id'], key)
                self.d.send(battle_guard(command, self.state))
            except (ValueError, KeyError, TypeError) as exc: self.d.message.text = str(exc)
        pick('選擇特技目標', [(key, value.get('name', key)+f" HP {value.get('hp', '—')}")
            for key, value in self.state.get('battle_units', {}).items()], target)


class Battle(Page):
    def __init__(self, d):
        super().__init__(d); self.target = None; self.modes = {}
        self.info = label(); self.add_widget(self.info)
        self.grid = GridLayout(cols=4, spacing=dp(3), size_hint_y=None, height=dp(340)); self.add_widget(self.grid)
        self.buttons = {}
        for r in range(1, 5):
            for c in range(1, 5):
                key = f'{c}:{r}'
                b = button(key+' 空位', lambda k=key: self.choose(k), 82)
                self.grid.add_widget(b); self.buttons[key] = b
        self.actions = column(); self.add_widget(self.actions)
        self.add_widget(button('本回合送出角色／夥伴指令', self.submit))
    def choose(self, key):
        unit = self.state.get('battle_units', {}).get(key)
        if not unit: return
        if unit in owned_units(self.state, False):
            pick('此單位的行動', list(ACTIONS.items()), lambda mode: self.set_mode(key, mode))
        else: self.target = key; self.key = None; self.refresh()
    def set_mode(self, key, mode): self.modes[key] = mode; self.key = None; self.refresh()
    def submit(self):
        s = self.state
        self.d.send(dict(type='battle_submit', battle_count=s.get('battle_count'), round=s.get('battle', {}).get('round'),
            actor_pids={slot(a): a['pid'] for a in owned_units(s)}, modes=dict(self.modes), target_slot=self.target))
    def refresh(self):
        s = self.state; battle = s.get('battle', {}); units = s.get('battle_units', {})
        round_key = s.get('battle_count'), battle.get('round')
        if getattr(self, 'round_key', None) != round_key:
            self.round_key = round_key; self.modes = {}; self.target = None
        self.info.text = ('戰鬥中' if battle.get('active') else '末次戰場')+f"｜第 {battle.get('round', 0)} 回合\n點選自己的單位設定行動；點選敵方指定目標。"
        for key, view in self.buttons.items():
            u = units.get(key)
            if not u: view.text = key+' 空位'; continue
            status = '已離場' if u.get('exited') else '已陣亡' if u.get('hp', 0) <= 0 else f"{u.get('hp', '—')}/{u.get('max_hp', '—')}"
            name = u.get('name', '?'); element = {0:'無',1:'地',2:'水',3:'火',4:'風'}.get(u.get('element'), '?')
            view.text = ('◎ ' if self.target == key else '')+element+' '+name+'\n'+status
            view.background_color = (.3,.55,.65,1) if self.target == key else (.6,.7,.8,1)
        key = (str(units), str(self.modes), str(battle.get('commands')))
        if key != self.key:
            self.key = key; self.actions.clear_widgets()
            for actor in owned_units(s, False):
                key = slot(actor); mode = self.modes.get(key, 'normal')
                self.actions.add_widget(button(actor_label(actor)+'：'+ACTIONS[mode]+'｜'+str(battle.get('commands', {}).get(key, {}).get('status', '未下令')),
                                              lambda k=key: self.choose(k)))
