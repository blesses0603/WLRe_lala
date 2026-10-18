import copy
from android_app.pages.general import Page
from android_app.widgets import column, label, button, row, field, select, pick, confirm
from wlre.services.battle.party import own_team, player_name
from wlre.services.social.chat import CHANNELS, plain_text


class Party(Page):
    def __init__(self, d):
        super().__init__(d)
        self.info = label(); self.add_widget(self.info)
        self.target = field(self, '目標角色 ID（可由附近玩家選取）', numeric=True)
        self.add_widget(button('選擇附近玩家', self.choose_nearby))
        self.add_widget(row(button('邀請組隊', lambda: self.act('invite')), button('申請入隊', lambda: self.act('apply'))))
        self.add_widget(row(button('開關組隊邀請', self.flag), button('離隊／解散', lambda: d.send(
            {'type': 'team', 'action': 'leave'}, '確認離開隊伍？隊長離隊會解散隊伍。'))))
        self.add_widget(button('必要成員設定', self.guard))
        self.members = column(); self.requests = column()
        self.add_widget(label('隊伍成員')); self.add_widget(self.members)
        self.add_widget(label('待確認邀請／申請')); self.add_widget(self.requests)
    def act(self, action, rid=None):
        try: rid = int(rid if rid is not None else self.target.text)
        except ValueError: self.d.message.text = '請選擇玩家或輸入有效角色 ID'; return
        command = dict(type='team', action=action, role_id=rid)
        self.d.send(command, f"確認對 {player_name(self.state, rid)} 執行"+
                    ('移除隊員？' if action == 'kick' else '轉交隊長？')) if action in ('kick', 'leader') else self.d.send(command)
    def choose_nearby(self):
        scene = self.state.get('player', {}).get('scene')
        pick('附近玩家', [(v['role_id'], f"{v['name']}（{v['role_id']}）") for v in
            self.state.get('party', {}).get('nearby', {}).values() if v.get('scene') == scene],
            lambda rid: setattr(self.target, 'text', str(rid)))
    def flag(self):
        p = self.state.get('party', {})
        self.d.send(dict(type='team', action='flag', enabled=not p.get('enabled_requested', p.get('enabled'))))
    def guard(self):
        if 'ai_settings' not in self.d.data:
            self.d.message.text = '等待本帳號設定同步，請稍候再試'
            return
        from android_app.settings_ui import SettingsEditor
        SettingsEditor(self.d.app, self.d.sid, initial='必要成員')
    def refresh(self):
        p = self.state.get('party', {}); team = own_team(self.state)
        key = (str(p), self.d.live)
        if self.key == key: return
        self.key = key
        self.info.text = p.get('status', '等待同步')+'\n'+('隊長：'+player_name(self.state, team['leader_id']) if team else '目前未組隊')
        self.members.clear_widgets(); self.requests.clear_widgets()
        if team:
            for rid in team['members']:
                self.members.add_widget(label(player_name(self.state, rid)+f'（{rid}）'+(' · 隊長' if rid == team['leader_id'] else '')))
                if team['leader_id'] == self.state.get('player', {}).get('role_id') and rid != team['leader_id']:
                    self.members.add_widget(row(button('移除', lambda r=rid: self.act('kick', r)),
                                                button('交接隊長', lambda r=rid: self.act('leader', r))))
        for key, request in p.get('requests', {}).items():
            self.requests.add_widget(label({'team_invite': '組隊邀請', 'team_application': '入隊申請', 'team_leader_offer': '隊長交接'}.get(request['type'], '請求')+
                '：'+player_name(self.state, request['role_id'])+' · '+request['status']))
            if request['status'] == 'pending':
                self.requests.add_widget(row(button('接受', lambda k=key: self.d.send(dict(type='team', action='respond', request=k, answer=1))),
                    button('拒絕', lambda k=key: self.d.send(dict(type='team', action='respond', request=k, answer=2)))))


class Chat(Page):
    def __init__(self, d):
        super().__init__(d); self.offset = 0; self.quote = None
        self.filter = select(self, '顯示頻道', ['全部', *CHANNELS, '跨服', '系統']); self.filter.bind(text=lambda *_: self.render())
        self.messages = column(); self.add_widget(self.messages)
        self.add_widget(row(button('較早訊息', lambda: self.move(-1)), button('最新訊息', lambda: self.move(999))))
        self.channel = select(self, '發送頻道', list(CHANNELS))
        self.target = field(self, '密語名稱／角色 ID')
        self.quote_label = label('未引用訊息'); self.add_widget(self.quote_label)
        self.add_widget(button('取消引用', self.cancel_quote))
        self.text = field(self, '聊天內容')
        self.add_widget(row(button('表情', self.emojis), button('送出', self.send)))
    def cancel_quote(self): self.quote = None; self.quote_label.text = '未引用訊息'
    def emojis(self):
        from android_app.assets import emoji_entries, emoji_texture
        from kivy.uix.image import Image
        from kivy.metrics import dp
        entries = [(int(i), '[Emoji'+i+']') for i, data in emoji_entries().items() if data.get('available', True)]
        def icon(index):
            value = emoji_texture(index)
            return Image(texture=value, size_hint=(None, None), size=(dp(40),dp(40))) if value else None
        pick('選擇表情', entries, lambda i: setattr(self.text, 'text', self.text.text.text + f'[Emoji{i}]'), icon=icon)
    def send(self):
        command = dict(type='chat', channel=self.channel.text, target=self.target.text, text=self.text.text)
        if self.quote: command['reply'] = copy.deepcopy(self.quote)
        if self.d.send(command):
            self.d.message.text = '聊天已排入佇列；請以伺服器轉送／回覆為準'
            self.text.text = ''; self.cancel_quote()
    def move(self, delta):
        self.offset = max(0, self.offset+delta); self.render()
    def actions(self, message):
        body = column()
        body.add_widget(label(plain_text(message.get('text', ''))))
        popup = None
        def whisper():
            if message.get('channel') == '跨服': self.d.message.text = '跨服訊息不能當作本服密語對象'; return
            pid = self.state.get('player', {}).get('role_id')
            rid = message.get('role_id')
            target = message.get('whisper_target') if rid == pid else rid
            self.channel.text = '密語'; self.target.text = str(target or ''); popup.dismiss()
        def quote():
            channel = message.get('channel')
            if channel not in CHANNELS or not message.get('role_id'): return
            self.channel.text = channel
            pid = self.state.get('player', {}).get('role_id')
            target = message.get('whisper_target') if message['role_id'] == pid else message['role_id']
            if channel == '密語': self.target.text = str(target)
            self.quote = dict(role_id=message['role_id'], text=message['text'], channel=channel,
                items=[v['item_id'] if isinstance(v, dict) else v for v in message.get('items', [])],
                has_at=False, whisper_target=target)
            self.quote_label.text = '引用：'+plain_text(message['text']); popup.dismiss()
        body.add_widget(row(button('密語回覆', whisper), button('引用回覆', quote)))
        from android_app.widgets import dialog
        popup = dialog('訊息操作', body, .6)
    def render(self):
        rows = [r for r in self.d.data.get('chat', []) if self.filter.text == '全部' or r.get('channel') == self.filter.text]
        pages = max(1, (len(rows)+19)//20); self.offset = min(self.offset, pages-1)
        self.messages.clear_widgets()
        for message in rows[self.offset*20:self.offset*20+20]:
            text = '['+message.get('channel', '?')+'] '+message.get('name', str(message.get('role_id', '')))+'：'+plain_text(message.get('text', ''))
            if message.get('reply_text'): text += '\n↳ '+plain_text(message['reply_text'])
            self.messages.add_widget(button(text, lambda m=message: self.actions(m), max(64, min(210, 34+len(text)//18*22))))
            import re
            from android_app.assets import emoji_texture
            from kivy.uix.image import Image
            from kivy.metrics import dp
            tokens = re.findall(r'\[Emoji([0-9]+)\]', message.get('text', ''))[:8]
            images = []
            for index in tokens:
                value = emoji_texture(index)
                if value: images.append(Image(texture=value, size_hint=(None,None), size=(dp(32),dp(32))))
            if images: self.messages.add_widget(row(*images))
        self.messages.add_widget(label(f'{self.offset+1}/{pages} 頁 · 保留最近 200 則'))
    def refresh(self):
        key = (str(self.d.data.get('chat')), self.filter.text)
        if key != self.key:
            was_latest = self.offset >= max(0, ((len(getattr(self, '_previous', []))+19)//20)-1)
            self._previous = self.d.data.get('chat', [])
            if was_latest: self.offset = 999
            self.key = key; self.render()
