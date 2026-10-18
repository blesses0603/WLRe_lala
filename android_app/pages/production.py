import copy
import json
from types import SimpleNamespace
from kivy.core.clipboard import Clipboard
from android_app.pages.general import Page
from android_app.widgets import column, label, button, row, field, select, dialog, pick
from android_app.assets import item_image
from wlre.services.items.combat_resources import item_name
from wlre.services.items.alchemy import modes, prepare, material_problem
from wlre.services.items.crafting import RECIPES, confirmed_unlocked, recipe_plan, effective_time, elapsed
from wlre.services.items.crafting_browser_model import availability, material_rows, owned_counts, tool_status
from wlre.services.items.crafting_plan import validate_rows
from wlre.core.efficiency import duration


class Alchemy(Page):
    def __init__(self, d):
        super().__init__(d); self.materials = [None]*5
        self.mode = select(self, '煉金術', ['無技能'])
        self.runs = field(self, '執行次數（1～999）', 1, True)
        self.slots = []
        for index in range(5):
            b = button(f'材料 {index+1}：選擇', lambda i=index: self.choose(i))
            self.add_widget(b); count = field(self, '每次數量', 1, True)
            self.slots.append((b, count))
        self.info = label(); self.add_widget(self.info)
        self.add_widget(button('預覽消耗／開始連續煉金', self.begin))
        self.add_widget(row(button('停止後續煉金', lambda: d.send({'type':'stop_alchemy'})), button('清空材料', self.clear)))
    def clear(self):
        self.materials = [None]*5
        for i, (b, _) in enumerate(self.slots): b.text = f'材料 {i+1}：選擇'
    def choose(self, index):
        entries = [(None, '清除此格')] + [(dict(v), f"#{v['index']} {item_name(v['item_id'])} ×{v['count']}")
            for v in self.state.get('inventory', {}).get('items', {}).values() if not material_problem(v)]
        pick('選擇背包材料', entries, lambda value: self.set_slot(index, value))
    def set_slot(self, index, value):
        self.materials[index] = value
        self.slots[index][0].text = f'材料 {index+1}：'+(f"#{value['index']} {item_name(value['item_id'])}" if value else '選擇')
    def begin(self):
        try:
            command = dict(type='start_alchemy', mode=self.mode.text, runs=int(self.runs.text), materials=[
                dict(index=v['index'], item_id=v['item_id'], count=int(self.slots[i][1].text))
                for i, v in enumerate(self.materials) if v])
            state = SimpleNamespace(**self.state); state.snapshot = lambda: self.state
            plan = prepare(state, command)
            text = f"{plan['mode']}煉金，共 {plan['runs']} 次\n"+'\n'.join(
                f"#{v['index']} {item_name(v['item_id'])} 每次 {v['count']}，共消耗 {v['count']*plan['runs']}" for v in plan['consumption'])
            self.d.send(command, text+'\n\n確認消耗材料並開始？')
        except (ValueError, KeyError, TypeError, AttributeError) as exc: self.d.message.text = str(exc)
    def refresh(self):
        options = modes(self.state); self.mode.values = options
        if self.mode.text not in options and options: self.mode.text = options[-1]
        a = self.state.get('alchemy', {}); busy = a.get('enabled') or a.get('pending')
        self.mode.disabled = self.runs.disabled = bool(busy)
        for b, count in self.slots: b.disabled = count.disabled = bool(busy)
        self.info.text = a.get('status', '等待同步')+f"\n完成 {a.get('completed', 0)}/{a.get('requested', 0)}"+'\n'+'\n'.join(
            f"{v.get('name', item_name(v['item_id']))} ×{v['count']}" for v in a.get('history', [])[-10:])


class Crafting(Page):
    def __init__(self, d):
        super().__init__(d); self.selected = None; self.offset = 0
        self.add_widget(row(button('自訂清單', self.plan), button('進入自家帳篷', lambda: d.send(dict(type='craft', action='enter')))))
        self.tool = select(self, '工作設備', ['全部', '我的最愛'])
        self.only_owned = select(self, '設備篩選', ['全部已確認開放配方', '只列小屋已擺設備'])
        self.query = field(self, '搜尋配方名稱／ID')
        self.catalog = column(); self.add_widget(self.catalog)
        self.add_widget(row(button('上一頁', lambda: self.move(-1)), button('下一頁', lambda: self.move(1))))
        self.queue_info = label(); self.add_widget(self.queue_info)
        self.queue = column(); self.add_widget(self.queue)
        self.add_widget(row(button('開始／接續製作', lambda: d.send(dict(type='craft', action='start'))),
                            button('暫停製作', lambda: d.send(dict(type='craft', action='pause')))))
        self.add_widget(button('停止後續自動接續', lambda: d.send(dict(type='craft', action='stop_auto'))))
        self.tool.bind(text=lambda *_: self.find()); self.only_owned.bind(text=lambda *_: self.find()); self.query.bind(text=lambda *_: self.find())
        self.tools = {}
    def find(self): self.offset = 0; self.key = None; self.refresh()
    def move(self, delta): self.offset = max(0, self.offset+delta); self.key = None; self.refresh()
    def refresh(self):
        favorites = self.d.data.get('preferences', {}).get('favorites', [])
        s = self.state; craft = s.get('crafting', {})
        tools = {item_name(r['tool_id'])+f"（{r['tool_id']}）": r['tool_id'] for r in RECIPES.values() if confirmed_unlocked(r)}
        self.tools = tools; self.tool.values = ['全部', '我的最愛', *sorted(tools)]
        key = (str(s.get('inventory')), str(s.get('furniture')), str(craft), str(favorites), self.query.text, self.tool.text, self.only_owned.text, self.offset)
        if key == self.key: return
        self.key = key; self.catalog.clear_widgets(); self.queue.clear_widgets()
        q = self.query.text.casefold(); selected_tool = tools.get(self.tool.text)
        recipes = [r for sid, r in RECIPES.items() if confirmed_unlocked(r)
            and q in (item_name(int(sid))+sid).casefold()
            and (self.tool.text != '我的最愛' or int(sid) in favorites)
            and (selected_tool is None or r['tool_id'] == selected_tool)
            and (self.only_owned.text != '只列小屋已擺設備' or tool_status(s, r['tool_id']) == '已擺放')]
        pages = max(1, (len(recipes)+11)//12); self.offset = min(self.offset, pages-1)
        self.catalog.add_widget(label(f'{self.offset+1}/{pages} 頁 · {len(recipes)} 項 · 收藏 {len(favorites)}/100'))
        for recipe in recipes[self.offset*12:self.offset*12+12]:
            sid = recipe['item_id']; status, _ = availability(s, recipe)
            self.catalog.add_widget(row(item_image(sid), button(('♥ ' if sid in favorites else '')+item_name(sid)+'\n'+status,
                lambda r=recipe: self.recipe(r), 64)))
            self.catalog.children[0].height = 64
        self.queue_info.text = craft.get('status', '等待排程同步')+f"\n完成 {craft.get('completed',0)} 項｜伺服器排程 {len(craft.get('queue',{}))} 項"
        for value in sorted(craft.get('queue', {}).values(), key=lambda r: r['index']):
            sid = value['item_id']; index = value['index']
            seconds = effective_time(s, value)
            remaining = max(0, seconds*value['count']-elapsed(craft, value, __import__('time').monotonic())) if seconds is not None else None
            self.queue.add_widget(label(f"#{index} {item_name(sid)} ×{value['count']} · 剩餘 {duration(remaining)}"))
            self.queue.add_widget(row(*(button(text, lambda action=action, i=index: self.queue_action(action, i))
                for text, action in (('上移','up'),('下移','down'),('刪除','delete')))))
    def queue_action(self, action, index):
        self.d.send(dict(type='craft', action=action, index=index, revision=self.state.get('crafting', {}).get('revision')),
                    '確認移除排程？材料是否退還依伺服器規則。' if action == 'delete' else None)
    def recipe(self, recipe):
        sid = recipe['item_id']; body = column(); body.add_widget(item_image(sid, 64))
        status, reason = availability(self.state, recipe)
        counts = owned_counts(self.state, sid)
        body.add_widget(label(item_name(sid)+f"\n產量 {recipe['output']}｜時間 {duration(recipe['seconds'])}\n"+
            f"設備：{item_name(recipe['tool_id'])} · {tool_status(self.state, recipe['tool_id'])}\n"+
            '背包 {}｜已擺 {}｜保管 {}｜排程產出 {}'.format(*(counts[k] if counts[k] is not None else '待同步' for k in ('bag','placed','stored','queued')))+
            '\n'+status+'：'+reason))
        count = field(body, '批數', 1, True); materials = label(); body.add_widget(materials)
        def refresh(*_):
            try:
                number = int(count.text)
                if number < 1: raise ValueError()
                materials.text = '\n'.join(f"{r['name']}：可用 {r['usable'] if r['usable'] is not None else '待同步'}／需求 {r['required']}" for r in material_rows(self.state, recipe, number))
            except ValueError: materials.text = '請輸入有效批數'
        count.bind(text=refresh); refresh()
        def favorite():
            prefs = copy.deepcopy(self.d.data.get('preferences') or {'favorites': [], 'plan': []})
            ids = prefs['favorites']; prefs['favorites'] = [i for i in ids if i != sid] if sid in ids else ids+[sid]
            if self.d.preferences(prefs): popup.dismiss()
        def add():
            try:
                number = int(count.text)
                state = SimpleNamespace(**self.state)
                r, allocations, _ = recipe_plan(state, sid, number)
                text = item_name(sid)+f" ×{r['output']*number}\n"+'\n'.join(f"{item_name(a['item_id'])} ×{a['count']}" for a in allocations)
                self.d.send(dict(type='craft', action='add', item_id=sid, count=number), text+'\n\n確認消耗背包材料並加入排程？')
            except (ValueError, KeyError, TypeError, AttributeError) as exc: self.d.message.text = str(exc)
        def plan_add():
            try:
                prefs = copy.deepcopy(self.d.data.get('preferences') or {'favorites': [], 'plan': []})
                prefs['plan'] = validate_rows(prefs['plan']+[dict(item_id=sid, count=int(count.text))])
                if self.d.preferences(prefs): popup.dismiss()
            except (ValueError, TypeError) as exc: self.d.message.text = str(exc)
        body.add_widget(row(button('切換收藏', favorite), button('加入自訂清單', plan_add)))
        body.add_widget(button('加入伺服器製作排程', add))
        popup = dialog('配方詳情', body)
    def plan(self): PlanEditor(self.d)


class PlanEditor:
    def __init__(self, d):
        self.d = d; self.rows = copy.deepcopy(d.data.get('preferences', {}).get('plan', [])); self.offset = 0
        self.body = column(); self.message = label('編輯本地自訂清單；保存不會自動開始製作。'); self.body.add_widget(self.message)
        self.list = column(); self.body.add_widget(self.list)
        self.body.add_widget(row(button('上一頁', lambda: self.move(-1)), button('下一頁', lambda: self.move(1))))
        self.body.add_widget(row(button('保存清單', self.save), button('複製方案', self.export), button('貼上匯入', self.import_plan)))
        self.body.add_widget(row(button('清空草稿', self.clear), button('取回服務剩餘清單', self.from_runtime)))
        self.body.add_widget(row(button('開始清單', self.start), button('暫停清單', lambda: d.send(dict(type='craft', action='plan_pause')))))
        runtime = d.state.get('crafting', {}).get('local_plan', {})
        self.runtime_status = label(); self.body.add_widget(self.runtime_status)
        self.popup = dialog('自訂製作清單', self.body); self.render()
        from kivy.clock import Clock
        self.timer = Clock.schedule_interval(self.runtime_refresh, 1)
        self.popup.bind(on_dismiss=lambda *_: self.timer.cancel())
        self.runtime_refresh()
    def runtime_refresh(self, *_):
        if self.d.closed: return False
        runtime = self.d.state.get('crafting', {}).get('local_plan', {})
        self.runtime_status.text = '服務清單狀態：'+runtime.get('status','尚未啟動')+f"\n待送出 {len(runtime.get('rows', []))} 項 · 已送入 {runtime.get('sent',0)} 項"
    def clear(self):
        from android_app.widgets import confirm
        def apply(): self.rows = []; self.render()
        confirm('清空草稿', '清空未送出的編輯草稿？服務中的排程不受影響。', apply)
    def from_runtime(self):
        self.rows = copy.deepcopy(self.d.state.get('crafting', {}).get('local_plan', {}).get('rows', []))
        self.render(); self.message.text = '已讀取服務剩餘清單到草稿，尚未保存'
    def move(self, delta): self.offset = max(0, self.offset+delta); self.render()
    def render(self):
        self.list.clear_widgets(); pages = max(1, (len(self.rows)+9)//10); self.offset = min(self.offset, pages-1)
        self.list.add_widget(label(f'{self.offset+1}/{pages} 頁 · {len(self.rows)} 項'))
        for i in range(self.offset*10, min(len(self.rows), self.offset*10+10)):
            value = self.rows[i]
            self.list.add_widget(button(f"{i+1}. {item_name(value['item_id'])} · {value['count']} 批（點選修改）", lambda n=i: self.edit(n)))
            self.list.add_widget(row(button('上移', lambda n=i: self.swap(n, -1)), button('下移', lambda n=i: self.swap(n, 1)), button('移除', lambda n=i: self.remove(n))))
    def swap(self, i, delta):
        if 0 <= i+delta < len(self.rows): self.rows[i], self.rows[i+delta] = self.rows[i+delta], self.rows[i]; self.render()
    def remove(self, i): self.rows.pop(i); self.render()
    def edit(self, i):
        body = column(); value = field(body, '批數', self.rows[i]['count'], True)
        popup = None
        def commit():
            try:
                rows = copy.deepcopy(self.rows); rows[i]['count'] = int(value.text); self.rows = validate_rows(rows)
                self.render(); popup.dismiss()
            except ValueError as exc: self.message.text = str(exc)
        body.add_widget(button('套用', commit)); popup = dialog('編輯批數', body, .5)
    def save(self):
        prefs = copy.deepcopy(self.d.data.get('preferences') or {'favorites': [], 'plan': []}); prefs['plan'] = self.rows
        if self.d.preferences(prefs): self.message.text = '已送出保存，等待服務確認'
    def export(self):
        Clipboard.copy(json.dumps(dict(format='wlre-crafting-plan', version=1, rows=self.rows), ensure_ascii=False, indent=2))
        self.message.text = '方案已複製，可貼到檔案保存或傳給電腦版'
    def import_plan(self):
        try:
            text = Clipboard.paste()
            if len(text) > 65536: raise ValueError('方案內容過長')
            data = json.loads(text)
            if not isinstance(data, dict) or data.get('format') != 'wlre-crafting-plan' or data.get('version') != 1: raise ValueError('方案格式不支援')
            self.rows = validate_rows(data['rows']); self.render(); self.message.text = '已載入草稿，尚未保存或執行'
        except (ValueError, KeyError, TypeError) as exc: self.message.text = str(exc)
    def start(self):
        try: rows = validate_rows(self.rows)
        except ValueError as exc: self.message.text = str(exc); return
        if not rows: self.message.text = '清單為空'; return
        revision = self.d.state.get('crafting', {}).get('local_plan', {}).get('revision', 0)
        from android_app.widgets import confirm
        def begin():
            if self.d.send(dict(type='craft', action='plan_set', rows=rows, revision=revision)):
                self.d.send(dict(type='craft', action='plan_start', revision=revision+1))
        confirm('開始自訂清單', f'依順序製作 {len(rows)} 項，將消耗材料。材料、設備不足時核心會暫停。確認開始？', begin)
