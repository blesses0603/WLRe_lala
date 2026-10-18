"""Complete mobile AI form editor; drafts apply only on explicit save."""
import copy
import json
from kivy.core.clipboard import Clipboard
from android_app.widgets import column, label, button, field, select, check, row, dialog, pick
from wlre.services.battle.auto_battle import defaults, validate, ACTION_IDS
from wlre.services.battle.battle_commands import ACTIONS, owned_units
from wlre.services.items.combat_resources import CAT, item_name, skill_rows, field_context, heal_effects

GROUPS = (('bDeadAction','deadAction','同方陣亡',1), ('bEnemyHPAction','enemyHpAction','敵HP條件',1),
    ('bLowHpAction','lowHpAction','低HP條件',1), ('bLowSpAction','lowSpAction','低SP條件',1),
    ('bRoundAction','roundAction','指定回合',3), ('bRepeatAction','repeatAction','循環行動',5),
    ('bOrderAction','orderAction','順序行動',2))
NAMES = {0:'略過此格', **{sid:ACTIONS[mode] for sid, mode in ACTION_IDS.items()}}
TARGETS = {1:'最低HP', 2:'屬性優先', 3:'最高HP'}
NOTICES = {1:'同方任一單位', 2:'本機角色', 3:'出戰夥伴'}


def action_name(value):
    sid = value['id']
    return NAMES.get(sid) or (item_name(sid) if value['kind'] == 2 else CAT['skills'].get(str(sid), {}).get('name', '尚未同步特技'))


def known_actions(state, who, item=False):
    if item:
        return [(sid, NAMES[sid]) for sid in (0, -2, -3)] + [(int(sid), value['name']+f'（{sid}）')
            for sid, value in CAT['items'].items() if value['kind'] in (23,32)]
    entries = [(sid, NAMES[sid]) for sid in (0,-1,10001,60021,60041,10008)]
    actors = owned_units(state, False) if state.get('battle', {}).get('active') else list(field_context(state)[0]['battle_units'].values())
    pid = state.get('player', {}).get('role_id'); known = {}
    if pid:
        for actor in actors:
            if (actor.get('pid') == pid) != (who == 'player'): continue
            for skill in skill_rows(state, actor):
                known[skill['id']] = skill['name']+f"（{skill['id']}） · {skill['source']} Lv.{skill['level']}"
    return entries+[(sid, text) for sid, text in sorted(known.items()) if sid not in NAMES]


class SettingsEditor:
    TABS = ('一般設定','角色規則','夥伴規則','HP／SP補給','必要成員','匯入／匯出')
    def __init__(self, app, sid, initial='一般設定'):
        self.app, self.sid = app, sid
        session = app.manager.sessions.get(sid)
        self.value = validate(copy.deepcopy(getattr(session, 'ai_settings', None) or defaults()))
        self.collectors = []; self.body = column()
        self.tabs = select(self.body, '設定頁面', self.TABS, initial)
        self.form = column(); self.body.add_widget(self.form)
        self.message = label('設定只在按下保存後生效；下次啟動自動戰鬥時套用。'); self.body.add_widget(self.message)
        self.body.add_widget(row(button('保存設定', self.save), button('取消', lambda: self.popup.dismiss())))
        self.tabs.bind(text=self.switch)
        self.current = initial; self.render(initial)
        self.popup = dialog('完整 AI／補給設定', self.body)
    def state(self):
        try: return self.app.manager.session_detail(self.sid).get('state', {})
        except ValueError: return {}
    def collect(self):
        draft = copy.deepcopy(self.value)
        for collect in self.collectors: collect(draft)
        self.value = validate(draft)
    def switch(self, _spinner, name):
        try: self.collect()
        except (ValueError, TypeError) as exc:
            self.message.text = str(exc)
            self.tabs.unbind(text=self.switch); self.tabs.text = self.current; self.tabs.bind(text=self.switch)
            return
        self.current = name; self.render(name)
    def render(self, name):
        self.form.clear_widgets(); self.collectors = []
        if name == '一般設定': self.general()
        elif name in ('角色規則','夥伴規則'): self.rules('player' if name == '角色規則' else 'partner')
        elif name == 'HP／SP補給': self.recovery()
        elif name == '必要成員': self.guard()
        else: self.exchange()
    def general(self):
        for key, title in (('bPlayerDieCloseAI','角色陣亡時停止 AI／徘徊'), ('bNPCDieCloseAI','出戰夥伴陣亡時停止 AI／徘徊'), ('field_heal','啟用戰後 HP／SP 補給')):
            control = check(self.form, title, self.value[key])
            self.collectors.append(lambda draft, k=key, v=control: draft.__setitem__(k, v.active))
        self.form.add_widget(label('戰後門檻與指定補品在「HP／SP補給」頁設定。規則由上到下判斷；沒有可用規則時沿用核心普攻後備行動。'))
    def rules(self, who):
        self.form.add_widget(label('由上到下判斷條件。點選行動可更改技能／物品、目標與門檻；多格規則可調整順序。'))
        profile = self.value['profiles'][who]
        for flag, key, title, count in GROUPS:
            control = check(self.form, '啟用：'+title, profile[flag])
            self.collectors.append(lambda draft, k=flag, c=control: draft['profiles'][who].__setitem__(k, c.active))
            for index in range(count):
                value = profile[key][index] if count > 1 else profile[key]
                b = button(f'{index+1}. '+action_name(value), lambda k=key, i=index: self.edit_action(who, k, i))
                self.form.add_widget(b)
                if count > 1:
                    self.form.add_widget(row(button('上移', lambda k=key, i=index: self.swap(who,k,i,-1)),
                                             button('下移', lambda k=key, i=index: self.swap(who,k,i,1))))
    def swap(self, who, key, index, delta):
        try: self.collect()
        except ValueError as exc: self.message.text = str(exc); return
        values = self.value['profiles'][who][key]
        if 0 <= index+delta < len(values):
            values[index], values[index+delta] = values[index+delta], values[index]
            self.render(self.current)
    def edit_action(self, who, key, index):
        try: self.collect()
        except ValueError as exc: self.message.text = str(exc); return
        source = self.value['profiles'][who][key]
        value = copy.deepcopy(source[index] if isinstance(source,list) else source)
        body = column(); selected = {'id':value['id']}
        kind = select(body, '行動類型', ['技能／基本行動','包包道具'], '包包道具' if value['kind']==2 else '技能／基本行動')
        chosen = label(action_name(value)); body.add_widget(chosen)
        def choose():
            def commit(sid): selected['id'] = sid; chosen.text = NAMES.get(sid) or (item_name(sid) if kind.text=='包包道具' else CAT['skills'].get(str(sid),{}).get('name','未知'))
            pick('選擇行動（特技僅列本單位已確認項目）', known_actions(self.state(),who,kind.text=='包包道具'), commit)
        body.add_widget(button('選擇行動', choose))
        def kind_change(*_): selected['id'] = 0; chosen.text = '略過此格'
        kind.bind(text=kind_change)
        target = select(body, '目標排序', list(TARGETS.values()), TARGETS[value['target']])
        next_skill = check(body, '允許次階特技（僅技能）', value.get('bUseNextSkill'))
        extras = {}
        if 'notice' in value: extras['notice'] = select(body,'觀察對象',list(NOTICES.values()),NOTICES[value['notice']])
        if 'compareKind' in value: extras['compareKind'] = select(body,'敵方HP比較',['大於','小於'],'大於' if value['compareKind']==1 else '小於')
        if 'value' in value: extras['value'] = field(body,'HP／SP門檻（依該規則的數值單位）',value['value'])
        error = label(); body.add_widget(error)
        def save():
            try:
                result = copy.deepcopy(value)
                result.update(id=selected['id'],kind=2 if kind.text=='包包道具' else 1,target=next(k for k,v in TARGETS.items() if v==target.text))
                if result['kind']==1: result['bUseNextSkill'] = next_skill.active
                else: result.pop('bUseNextSkill',None)
                for k, c in extras.items():
                    result[k] = next(n for n,v in NOTICES.items() if v==c.text) if k=='notice' else (1 if c.text=='大於' else 2) if k=='compareKind' else float(c.text)
                draft = copy.deepcopy(self.value); entry = draft['profiles'][who][key]
                if isinstance(entry,list): entry[index] = result
                else: draft['profiles'][who][key] = result
                self.value = validate(draft); popup.dismiss(); self.render(self.current)
            except (ValueError, StopIteration) as exc: error.text = str(exc)
        body.add_widget(row(button('保存此行動',save),button('取消',lambda:popup.dismiss())))
        popup = dialog('編輯行動與條件',body)
    def recovery(self):
        enabled = check(self.form,'啟用戰後補給',self.value['field_heal'])
        self.collectors.append(lambda d, master=enabled: d.__setitem__('field_heal',master.active))
        for resource in ('hp','sp'):
            data = self.value['recovery'][resource]
            self.form.add_widget(label(resource.upper()+' 補給'))
            storage = self.state().get('potion_storage',{}).get(resource,{}).get('value','待同步')
            self.form.add_widget(label('藥水儲存槽餘額：'+str(storage)))
            enabled = check(self.form,'自動使用指定補品',data['enabled'])
            others = check(self.form,'指定補品不足時使用其他包包補品',data['other_items'])
            order = select(self.form,'藥水儲存槽順序',['不使用','優先使用','指定補品用完後使用'],{'off':'不使用','first':'優先使用','after':'指定補品用完後使用'}[data['storage']])
            percents = {who:field(self.form,title+'低於門檻（0～100%）',data[who+'_percent'],True) for who,title in (('player','角色'),('partner','夥伴'))}
            for i,sid in enumerate(data['items']):
                self.form.add_widget(button(f'{i+1}. '+(item_name(sid) if sid else '選擇補品'),lambda res=resource,n=i:self.supply(res,n)))
            def collect(d,res=resource,e=enabled,o=others,s=order,p=percents):
                d['recovery'][res].update(enabled=e.active,other_items=o.active,storage={'不使用':'off','優先使用':'first','指定補品用完後使用':'after'}[s.text],
                    **{who+'_percent':int(control.text) for who,control in p.items()})
                d['field_'+res+'_percent'] = int(p['player'].text)
            self.collectors.append(collect)
    def supply(self,resource,index):
        try: self.collect()
        except ValueError as exc:self.message.text=str(exc);return
        counts = {}
        for value in self.state().get('inventory',{}).get('items',{}).values(): counts[value['item_id']] = counts.get(value['item_id'],0)+value['count']
        entries = [(0,'清除此格')]+[(sid,item_name(sid)+f' · 持有 {number}') for sid,number in counts.items() if heal_effects(sid).get(resource)]
        def choose(sid): self.value['recovery'][resource]['items'][index]=sid; self.render(self.current)
        pick('選擇 '+resource.upper()+' 補品',entries,choose)
    def guard(self):
        config = self.value['party_guard']
        enabled = check(self.form,'必要隊員未到齊時優先逃跑',config['enabled'])
        controls = []
        self.form.add_widget(label('最多四位；只以伺服器確認的同隊名單判斷，附近玩家不算已到齊。'))
        for i in range(4):
            member = config['members'][i] if i<len(config['members']) else {}
            rid = field(self.form,f'必要成員 {i+1} 角色ID（留空略過）',member.get('role_id',''),True)
            name = field(self.form,'名稱',member.get('name','')); controls.append((rid,name))
        def collect(d):
            d['party_guard'] = dict(enabled=enabled.active,members=[dict(role_id=int(r.text),name=n.text) for r,n in controls if r.text.strip()])
        self.collectors.append(collect)
    def exchange(self):
        self.form.add_widget(label('使用與電腦版相同的 AI JSON 格式交換。匯入只更新草稿，按保存才會套用。'))
        self.form.add_widget(row(button('複製設定',self.export),button('從剪貼簿匯入',self.import_value)))
        self.form.add_widget(button('恢復預設草稿',self.reset))
    def reset(self):self.value=defaults();self.render(self.current);self.message.text='已恢復預設草稿，尚未保存'
    def export(self):
        try:self.collect();Clipboard.copy(json.dumps(self.value,ensure_ascii=False,indent=2));self.message.text='已複製設定，可保存為 JSON 檔與電腦版交換'
        except ValueError as exc:self.message.text=str(exc)
    def import_value(self):
        try:
            raw=Clipboard.paste()
            if len(raw)>65536:raise ValueError('設定內容過長')
            self.value=validate(json.loads(raw));self.render(self.current);self.message.text='已載入設定草稿，尚未保存'
        except (ValueError,TypeError) as exc:self.message.text=str(exc)
    def save(self):
        try:
            self.collect()
            if not self.app.manager.save_ai_settings(self.sid,self.value):raise ValueError('背景服務未就緒')
            self.popup.dismiss()
        except (ValueError,OSError) as exc:self.message.text=str(exc)
