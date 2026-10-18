from android_app.pages.general import Page
from android_app.widgets import button, label
from android_app.settings_ui import SettingsEditor

class SettingsPage(Page):
    def __init__(self,d):
        super().__init__(d)
        self.add_widget(label('完整 AI／戰後補給設定依帳號＋伺服器保存。規則編輯為草稿，按保存後於下次啟動自動戰鬥套用。'))
        for name in SettingsEditor.TABS:
            self.add_widget(button(name,lambda tab=name:SettingsEditor(d.app,d.sid,tab)))
