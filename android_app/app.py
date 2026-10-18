"""Minimal portrait, touch-operated Android login smoke-test UI."""
import queue
from pathlib import Path

from kivy.app import App
from kivy.core.text import LabelBase, DEFAULT_FONT
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
from kivy.uix.checkbox import CheckBox
from kivy.utils import platform

from android_app.sessions import SessionManager
from android_app.version import ANDROID_VERSION


# SDL2's bundled Roboto does not contain Chinese glyphs. Register the included
# OFL font for Labels, Buttons, Spinners and TextInputs before creating widgets.
FONT = str(Path(__file__).resolve().parent / 'assets/fonts/NotoSansTC-Regular.ttf')
LabelBase.register(DEFAULT_FONT, fn_regular=FONT, fn_bold=FONT,
                   fn_italic=FONT, fn_bolditalic=FONT)


def text_label(text, height=32):
    return Label(text=text, size_hint_y=None, height=dp(height),
                 halign="left", valign="middle")


class LaLaApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.manager = SessionManager()
        self.cards = {}
        self.dashboard = None
        self.lines = []
        self.vault = None
        self.saved_accounts = []
        self.vault_error = False
        self.android_initializing = False
        self.android_ready_reported = False

    def on_start(self):
        print('WLRE_ANDROID_UI_READY', flush=True)
        if platform == 'android':
            Clock.schedule_once(self.prepare_android, 0.5)

    def prepare_android(self, *_):
        try:
            from jnius import autoclass
            from android.permissions import check_permission, request_permissions
            permission = 'android.permission.POST_NOTIFICATIONS'
            if autoclass('android.os.Build$VERSION').SDK_INT >= 33 and not check_permission(permission):
                request_permissions([permission], lambda *_: Clock.schedule_once(self.initialize_android, 0.5))
                return
        except Exception:
            self.message.text = '通知權限請由系統設定開啟（A05）'
        self.initialize_android()

    def initialize_android(self, *_):
        if self.android_initializing: return
        self.android_initializing = True
        stage = 'A01'
        try:
            from jnius import autoclass
            from android_app.runtime import ServiceManager
            from android_app.vault import AndroidCipher, AccountVault
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            directory = Path(str(activity.getNoBackupFilesDir().getAbsolutePath()))
            stage = 'A02'
            service = autoclass('org.lala.client.wlrelala.ServiceConnections')
            service.start(activity, '')
            self.android_service, self.android_activity = service, activity
            if not getattr(self.manager, 'background', False):
                self.manager = ServiceManager(directory / 'runtime/sessions.sock')
            stage = 'A03'
            try:
                cipher = AndroidCipher()
                import os
                probe = os.urandom(32)
                if cipher.decrypt(cipher.encrypt(probe)) != probe:
                    raise ValueError('Keystore roundtrip failed')
                self.vault = AccountVault(directory / 'accounts.enc', cipher)
                self.saved_accounts = self.vault.load()
                self.saved.values = self.saved_names()
                self.remember.disabled = False
                print('WLRE_ANDROID_KEYSTORE_READY', flush=True)
            except Exception:
                self.vault_error = True
                self.vault = None
                self.remember.disabled = True
                self.message.text = '帳密解密／金鑰初始化失敗；原資料已保留，可不保存帳密登入（A03）'
        except Exception as exc:
            # Never show exception text: it may include credentials or paths.
            self.message.text = 'Android 服務初始化失敗：' + stage + ' / ' + type(exc).__name__
            print('WLRE_ANDROID_STARTUP_ERROR ' + stage + ' ' + type(exc).__name__, flush=True)
        finally:
            self.android_initializing = False

    def stop_android_service(self, *_):
        try:
            self.android_service.stop(self.android_activity)
        except Exception as exc:
            self.message.text = '停止服務失敗（A04 / ' + type(exc).__name__ + '）'


    def build(self):
        self.title = "WLRe_LaLa Android v" + ANDROID_VERSION
        Window.softinput_mode = "below_target"
        Window.clearcolor = (0.05, 0.09, 0.16, 1)

        base = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        base.add_widget(Label(text="WLRe_LaLa  Android  v" + ANDROID_VERSION,
                              size_hint_y=None, height=dp(52), font_size="21sp"))
        base.add_widget(Label(text="多帳號獨立連線｜背景服務需允許通知",
                              size_hint_y=None, height=dp(30), font_size="13sp"))

        saved_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        self.saved = Spinner(text='已保存帳號', values=self.saved_names())
        self.saved.bind(text=self.switch_saved)
        saved_row.add_widget(self.saved)
        delete = Button(text='刪除帳號', size_hint_x=.45)
        delete.bind(on_release=self.delete_saved)
        saved_row.add_widget(delete)
        base.add_widget(saved_row)
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
        self.password = TextInput(hint_text="密碼", multiline=False,
                                  password=True, size_hint_y=None, height=dp(48))
        base.add_widget(self.password)

        remember_row = BoxLayout(size_hint_y=None, height=dp(36))
        self.remember = CheckBox(active=False, size_hint_x=None, width=dp(48), disabled=self.vault is None)
        remember_row.add_widget(self.remember)
        remember_row.add_widget(Label(text='使用 Keystore 加密保存帳密'))
        base.add_widget(remember_row)
        button = Button(text="新增連線並登入", size_hint_y=None, height=dp(52))
        button.bind(on_release=self.connect_account)
        base.add_widget(button)

        self.message = Label(text="選擇分流登入後，可開啟各帳號的角色功能。",
                             size_hint_y=None, height=dp(46))
        if self.vault_error: self.message.text = '帳密解密失敗；原資料已保留，請重新輸入登入'
        base.add_widget(self.message)
        self.resources = Label(text='資源監控：等待服務取樣', size_hint_y=None, height=dp(84), font_size='12sp')
        self.resources.bind(size=lambda view, size: setattr(view, 'text_size', (size[0], None)))
        self.message.bind(size=lambda view, size: setattr(view, 'text_size', (size[0], None)))
        base.add_widget(self.resources)
        if platform == 'android':
            service_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
            restart = Button(text='啟動背景服務')
            restart.bind(on_release=self.initialize_android)
            stop_service = Button(text='停止全部連線與服務')
            stop_service.bind(on_release=self.stop_android_service)
            service_row.add_widget(restart)
            service_row.add_widget(stop_service)
            base.add_widget(service_row)
        base.add_widget(Label(text="帳號連線列表（不限固定數量）",
                              size_hint_y=None, height=dp(34)))

        scroll = ScrollView(do_scroll_x=False)
        self.list_box = GridLayout(cols=1, spacing=dp(8), padding=dp(4),
                                   size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        base.add_widget(scroll)
        Clock.schedule_interval(self.drain_events, 0.25)
        # Entire form scrolls on small phones and when the keyboard is visible.
        base.size_hint_y = None
        base.bind(minimum_height=base.setter('height'))
        scroll.size_hint_y = None
        scroll.height = dp(300)
        outer = ScrollView(do_scroll_x=False)
        outer.add_widget(base)
        return outer

    def connect_account(self, *_):
        if platform == 'android' and not getattr(self.manager, 'background', False):
            self.message.text = '背景服務未就緒，請點擊啟動背景服務'
            return
        record = self.lookup.get(self.server.text)
        account = self.account.text.strip()
        password = self.password.text
        if not record or not account or not password:
            self.message.text = "請選擇分流並輸入帳號、密碼"
            return
        self.password.text = ""
        if self.remember.active and self.vault:
            records = [r for r in self.saved_accounts if (r['server'], r['account']) != (self.server.text, account)]
            records.append(dict(server=self.server.text, account=account, password=password))
            try:
                self.vault.save(records)
                self.saved_accounts = records
                self.saved.values = self.saved_names()
            except Exception:
                self.message.text = '安全保存失敗，未建立連線'
                return
        try:
            session = self.manager.start(
                label=self.server.text, host=record["host"], port=record["port"],
                account=account, password=password)
        except ValueError as exc:
            self.message.text = str(exc)
            return
        self.message.text = "已建立新連線；可繼續新增其他帳號"
        if session is not None: self.add_card(session)

    def add_card(self, session):
        account = session.account
        card = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(6),
                         size_hint_y=None, height=dp(230))
        title = Label(text=account + " | " + session.label,
                      size_hint_y=None, height=dp(38))
        status = Label(text="準備連線", size_hint_y=None, height=dp(110))
        status.bind(size=lambda view, size: setattr(view, "text_size", (size[0], None)))
        controls = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        choices = {}
        for index in (1, 2):
            choice = Button(text="角色 " + str(index), disabled=True)
            choice.bind(on_release=lambda _button, sid=session.session_id, n=index:
                        self.choose_role(sid, n))
            controls.add_widget(choice)
            choices[index] = choice
        stop = Button(text="停止")
        stop._lala_stop_callback = lambda _button, sid=session.session_id: self.manager.stop(sid)
        stop.bind(on_release=stop._lala_stop_callback)
        controls.add_widget(stop)
        card.add_widget(title)
        card.add_widget(status)
        card.add_widget(controls)
        from android_app.widgets import button as mobile_button
        card.add_widget(mobile_button('開啟角色功能', lambda sid=session.session_id: self.open_dashboard(sid)))
        from android_app.automation_ui import attach
        attach(self, card, session.session_id)
        self.list_box.add_widget(card)
        self.cards[session.session_id] = (status, choices, title, stop, card)

    def open_dashboard(self, sid):
        if self.dashboard: self.dashboard.close()
        from android_app.dashboard import Dashboard
        self.dashboard = Dashboard(self, sid)

    def saved_names(self):
        return [r['account'] + ' | ' + r['server'] for r in self.saved_accounts]

    def switch_saved(self, _spinner, name):
        for record, label in zip(self.saved_accounts, self.saved_names()):
            if label == name:
                self.account.text = record['account']
                self.server.text = record['server']
                self.password.text = record['password']
                return

    def delete_saved(self, *_):
        if not self.vault: return
        records = [r for r, label in zip(self.saved_accounts, self.saved_names()) if label != self.saved.text]
        try: self.vault.save(records)
        except Exception:
            self.message.text = '安全刪除失敗，原資料已保留'
            return
        self.saved_accounts = records
        self.saved.values = self.saved_names()
        self.saved.text = '已保存帳號'
        self.password.text = ''
        self.message.text = '已刪除保存的帳密；既有連線可個別停止'

    def choose_role(self, session_id, index):
        if self.manager.select_role(session_id, index):
            record = self.cards.get(session_id)
            if record:
                record[0].text = "正在登入角色"
                for button in record[1].values(): button.disabled = True

    def remove_card(self, session_id):
        if self.manager.remove(session_id):
            record = self.cards.pop(session_id, None)
            if record: self.list_box.remove_widget(record[4])

    def drain_events(self, *_):
        if getattr(self.manager, 'background', False):
            for session in list(self.manager.sessions.values()):
                if session.session_id not in self.cards: self.add_card(session)
            metrics = self.manager.metrics
            if not self.manager.available:
                self.resources.text = '服務無回應／已停止；連線狀態未知，請重啟服務'
                for record in self.cards.values():
                    record[0].text = '服務無回應；連線狀態未知'
                    for button in record[1].values(): button.disabled = True
            elif metrics:
                if not self.android_ready_reported:
                    print('WLRE_ANDROID_SERVICE_CONNECTED', flush=True)
                    self.android_ready_reported = True
                try:
                    self.render_metrics(metrics)
                except Exception:
                    self.resources.text = '資源監控暫時無法讀取（A06）；連線由服務管理'
        for _ in range(80):
            try:
                sid, kind, value = self.manager.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'error':
                self.message.text = value
                continue
            if kind == 'removed':
                record = self.cards.pop(sid, None)
                if record: self.list_box.remove_widget(record[4])
                continue
            record = self.cards.get(sid)
            if not record:
                continue
            session = self.manager.sessions.get(sid)
            if session is None: continue
            status, choices, title, stop, card = record
            if kind == 'chat_ack':
                if self.dashboard and self.dashboard.sid == sid: self.dashboard.chat_ack(value)
            elif kind == "notice":
                self.message.text = value
                if self.dashboard and self.dashboard.sid == sid: self.dashboard.message.text = value
            elif kind == "status":
                status.text = value
                if session.stop_event.is_set():
                    for button in choices.values(): button.disabled = True
            elif kind == "roles":
                for index, button in choices.items():
                    role = next((r for r in value if r["index"] == index), None)
                    button.disabled = (role is None or bool(role.get("locked")) or not session.active
                        or session.stop_event.is_set() or session.selection_pending
                        or session.phase != "role_selection")
                    suffix = "（無法使用）" if role and role.get("locked") else ""
                    level = role.get("level") if role else None
                    button.text = "角色 " + str(index) + (" Lv." + str(level) if level is not None else "") + suffix
            elif kind == "snapshot":
                if value["phase"] != "role_selection":
                    for button in choices.values(): button.disabled = True
                if value["character"]:
                    def known(key): return str(value[key]) if value.get(key) is not None else "—"
                    point = value.get("position")
                    location = (point.get("label", "角色位置") + "：" + str(point["x"]) + ", " + str(point["y"])) if point else "位置待同步"
                    status.text = ("角色 " + value["character"] + " Lv." + known("level") +
                        "\nHP " + known("hp") + "/" + known("max_hp") + "  SP " + known("sp") + "/" + known("max_sp") +
                        "\n地圖 " + known("scene") + "｜" + location)
            elif kind == "finished":
                status.text = value
                for button in choices.values(): button.disabled = True
                stop.unbind(on_release=stop._lala_stop_callback)
                stop.text = "移除"
                stop.bind(on_release=lambda _button, session_id=sid: self.remove_card(session_id))
        from android_app.automation_ui import refresh
        for sid in self.cards: refresh(self, sid)
        return True

    def render_metrics(self, metrics):
        import time
        from jnius import autoclass
        memory = autoclass('android.os.Debug$MemoryInfo')()
        autoclass('android.os.Debug').getMemoryInfo(memory)
        self.resources.text = ('在線 {online}／活動連線 {active}｜服務 PSS {service_pss_kib} KiB'.format(**metrics)
            + '\n畫面 PSS ' + str(memory.getTotalPss()) + ' KiB｜裝置電量 ' + str(metrics.get('battery_percent') if metrics.get('battery_percent') is not None else '未知')
            + '%｜裝置溫度 ' + str(metrics.get('device_temperature_c') if metrics.get('device_temperature_c') is not None else '未知') + '°C｜App 耗電未知｜' + time.strftime('%H:%M:%S', time.localtime(metrics['sample_time'])))

    def on_pause(self):
        self.password.text = ""
        if hasattr(self.manager, 'set_paused'): self.manager.set_paused(True)
        if not getattr(self.manager, 'background', False): self.manager.stop_all()
        return True

    def on_resume(self):
        if hasattr(self.manager, 'set_paused'): self.manager.set_paused(False)

    def on_stop(self):
        self.password.text = ""
        if not getattr(self.manager, 'background', False): self.manager.stop_all()
