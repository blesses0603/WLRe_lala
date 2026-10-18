"""One account's mobile workspace, reattaches to foreground service state."""
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from android_app.widgets import button, label, select, column

PAGES = ('角色概況', '包包與特技', '小地圖', '戰場陣形', '聊天', '組隊', '煉金', '製作', '經驗效率', '事件紀錄', 'AI與補給設定')


class Dashboard:
    def __init__(self, app, sid):
        self.app, self.sid = app, sid
        self.data = {}; self.page = None; self.page_name = None; self.signature = None
        self.closed = False
        session = app.manager.sessions[sid]
        base = BoxLayout(orientation='vertical', spacing=dp(6), padding=dp(6))
        self.status = label('等待服務同步', 50); base.add_widget(self.status)
        nav = column(); self.navigation = select(nav, '功能', PAGES); base.add_widget(nav)
        self.content = BoxLayout(orientation='vertical'); base.add_widget(self.content)
        self.message = label('', 60); base.add_widget(self.message)
        base.add_widget(button('返回帳號列表', self.close))
        self.popup = Popup(title=session.account+'｜'+session.label, content=base, size_hint=(1, 1))
        self.popup.bind(on_dismiss=lambda *_: self.dismissed())
        self.navigation.bind(text=lambda _, value: self.show(value))
        if hasattr(app.manager, 'watch'): app.manager.watch(sid)
        self.timer = Clock.schedule_interval(self.tick, .5)
        self.show(PAGES[0]); self.popup.open(); self.tick()

    @property
    def state(self): return self.data.get('state', {})

    @property
    def live(self):
        s = self.app.manager.sessions.get(self.sid)
        return bool(s and s.active and not s.stop_event.is_set() and s.phase == 'world_ready'
                    and getattr(self.app.manager, 'available', True))

    def send(self, command, question=None):
        if question:
            from android_app.widgets import confirm
            return confirm('確認操作', question, lambda: self.send(command))
        try:
            if not self.live or not self.app.manager.game_command(self.sid, command): raise ValueError('請先完成角色登入，並確認背景服務正常')
            self.message.text = '已排入操作佇列，等待核心與伺服器回覆'
            return True
        except (ValueError, OSError) as exc: self.message.text = str(exc); return False

    def preferences(self, value):
        try:
            if not self.app.manager.save_preferences(self.sid, value): raise ValueError('背景服務未就緒')
            self.message.text = '偏好已送出保存，等待服務確認'; return True
        except (ValueError, OSError) as exc: self.message.text = str(exc); return False

    def show(self, name):
        if self.page and hasattr(self.page, 'close'): self.page.close()
        self.page_name = name; self.content.clear_widgets()
        from android_app.pages.general import Overview, Events, Efficiency
        from android_app.pages.resources import Resources, Battle
        from android_app.pages.social import Party, Chat
        from android_app.pages.production import Alchemy, Crafting
        from android_app.pages.map import MapPage
        from android_app.pages.settings import SettingsPage
        classes = dict(zip(PAGES, (Overview, Resources, MapPage, Battle, Chat, Party, Alchemy, Crafting, Efficiency, Events, SettingsPage)))
        self.page = classes[name](self)
        scroll = ScrollView(do_scroll_x=False); scroll.add_widget(self.page)
        self.content.add_widget(scroll)
        self.page.refresh()

    def tick(self, *_):
        if self.closed: return False
        session = self.app.manager.sessions.get(self.sid)
        if not session: self.close(); return False
        if not getattr(self.app.manager, 'available', True):
            self.status.text = '服務失聯，資料為最後同步內容；操作已停用'
            return True
        try: data = self.app.manager.session_detail(self.sid)
        except ValueError: return True
        if data:
            self.data = data
            self.status.text = '已連線' if self.live else '連線已停止／等待角色登入；以下為最後同步資料'
            if self.page: self.page.refresh()
        return True

    def close(self): self.popup.dismiss()

    def dismissed(self):
        if self.closed: return
        self.closed = True; self.timer.cancel()
        if self.page and hasattr(self.page, 'close'): self.page.close()
        if hasattr(self.app.manager, 'watch'): self.app.manager.watch(None)
        self.app.dashboard = None
