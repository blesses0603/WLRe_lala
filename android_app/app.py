"""Minimal portrait, touch-operated Android login smoke-test UI."""
import queue

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from android_app.sessions import SessionManager
from android_app.version import ANDROID_VERSION


def text_label(text, height=32):
    return Label(text=text, size_hint_y=None, height=dp(height),
                 halign="left", valign="middle")


class LaLaApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.manager = SessionManager()
        self.cards = {}
        self.lines = []

    def build(self):
        self.title = "飄流 RE:LaLa Android v" + ANDROID_VERSION
        Window.softinput_mode = "below_target"
        Window.clearcolor = (0.05, 0.09, 0.16, 1)

        base = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        base.add_widget(Label(text="飄流 RE:LaLa  Android  v" + ANDROID_VERSION,
                              size_hint_y=None, height=dp(52), font_size="21sp"))
        base.add_widget(Label(text="測試版：單機多連線｜暫不支援鎖屏背景作業",
                              size_hint_y=None, height=dp(30), font_size="13sp"))

        # Only bundled official endpoints are selectable, no user-defined host input.
        from wlre.storage.server_lines import load
        self.lines = load()
        self.lookup = {row["name"]: row for row in self.lines}
        choices = list(self.lookup)
        self.server = Spinner(text=choices[0] if choices else "沒有伺服器",
                              values=choices, size_hint_y=None, height=dp(48))
        base.add_widget(self.server)
        self.account = TextInput(hint_text="遊戲帳號", multiline=False,
                                 size_hint_y=None, height=dp(48))
        base.add_widget(self.account)
        self.password = TextInput(hint_text="密碼（只使用於此次連線）", multiline=False,
                                  password=True, size_hint_y=None, height=dp(48))
        base.add_widget(self.password)

        button = Button(text="新增連線並登入", size_hint_y=None, height=dp(52))
        button.bind(on_release=self.connect_account)
        base.add_widget(button)

        self.message = Label(text="尚未登入。正式伺服器相容性仍待實機驗證。",
                             size_hint_y=None, height=dp(46))
        base.add_widget(self.message)
        base.add_widget(Label(text="帳號連線列表（不限固定數量）",
                              size_hint_y=None, height=dp(34)))

        scroll = ScrollView(do_scroll_x=False)
        self.list_box = GridLayout(cols=1, spacing=dp(8), padding=dp(4),
                                   size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        base.add_widget(scroll)
        Clock.schedule_interval(self.drain_events, 0.25)
        return base

    def connect_account(self, *_):
        record = self.lookup.get(self.server.text)
        account = self.account.text.strip()
        password = self.password.text
        if not record or not account or not password:
            self.message.text = "請選擇分流並輸入帳號、密碼"
            return
        self.password.text = ""
        try:
            session = self.manager.start(
                label=self.server.text, host=record["host"], port=record["port"],
                account=account, password=password)
        except ValueError as exc:
            self.message.text = str(exc)
            return
        self.message.text = "已建立新連線；可繼續新增其他帳號"
        card = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(6),
                         size_hint_y=None, height=dp(150))
        title = Label(text=account + " | " + session.label,
                      size_hint_y=None, height=dp(38))
        status = Label(text="準備連線", size_hint_y=None, height=dp(35))
        controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        for index in (1, 2):
            choice = Button(text="角色 " + str(index), disabled=True)
            choice.bind(on_release=lambda _button, sid=session.session_id, n=index:
                        self.manager.select_role(sid, n))
            controls.add_widget(choice)
        stop = Button(text="停止")
        stop.bind(on_release=lambda _button, sid=session.session_id:
                  self.manager.stop(sid))
        controls.add_widget(stop)
        card.add_widget(title)
        card.add_widget(status)
        card.add_widget(controls)
        self.list_box.add_widget(card)
        self.cards[session.session_id] = (status, controls.children, title)

    def drain_events(self, *_):
        for _ in range(80):
            try:
                sid, kind, value = self.manager.events.get_nowait()
            except queue.Empty:
                break
            record = self.cards.get(sid)
            if not record:
                continue
            status, controls, title = record
            if kind == "status":
                status.text = value
            elif kind == "roles":
                for button in controls:
                    if button.text.startswith("角色 "):
                        index = int(button.text.split()[1])
                        role = next((r for r in value if r["index"] == index), None)
                        button.disabled = role is None
                        if role:
                            button.text = "角色 " + str(index) + " Lv." + str(role["level"])
            elif kind == "snapshot":
                role = value["character"]
                if role:
                    status.text = "角色 " + role + " Lv." + str(value["level"])
            elif kind == "finished":
                status.text = value
        return True

    def on_stop(self):
        self.manager.stop_all()
