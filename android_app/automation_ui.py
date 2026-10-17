"""Touch controls backed by core state; settings contain no credentials."""
import copy
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from wlre.services.battle.auto_battle import defaults, summary as battle_summary
from wlre.services.world.roaming import summary as roaming_summary


def attach(app, card, sid):
    card.bind(minimum_height=card.setter('height'))
    card.automation_buttons = {}
    row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
    for feature, label in (('battle', '戰鬥'), ('roaming', '徘徊')):
        button = Button(text='啟動' + label, disabled=True)
        button.bind(on_release=lambda _, f=feature: toggle(app, sid, f))
        card.automation_buttons[feature] = button
        row.add_widget(button)
    settings = Button(text='AI 設定')
    settings.bind(on_release=lambda _: edit_settings(app, sid))
    row.add_widget(settings)
    card.settings_button = settings
    card.add_widget(row)
    card.automation_status = Label(text='登入角色後可啟動自動戰鬥／自動徘徊',
        size_hint_y=None, height=dp(116), font_size='13sp', halign='left', valign='top')
    card.automation_status.bind(size=lambda view, size: setattr(view, 'text_size', size))
    card.add_widget(card.automation_status)


def refresh(app, sid):
    session = app.manager.sessions.get(sid)
    record = app.cards.get(sid)
    if not session or not record: return
    card = record[4]
    available = getattr(app.manager, 'available', True)
    ready = available and session.active and not session.stop_event.is_set() and session.phase == 'world_ready'
    state = getattr(session, 'automation', {})
    pending = getattr(session, 'automation_pending', set())
    for feature, button in card.automation_buttons.items():
        button.disabled = not ready or feature in pending
        button.text = ('處理中' if feature in pending else
            ('停止' if state.get(feature, {}).get('enabled') else '啟動') +
            ('戰鬥' if feature == 'battle' else '徘徊'))
    card.settings_button.disabled = not available or not session.active
    if not available: text = '服務無回應；自動操作狀態未知'
    elif not session.active or session.stop_event.is_set(): text = '連線已停止，自動操作已結束'
    elif session.phase != 'world_ready': text = '登入角色後可啟動自動戰鬥／自動徘徊'
    else: text = '戰鬥：' + battle_summary(state.get('battle', {})) + '\n徘徊：' + roaming_summary(state.get('roaming', {}))
    card.automation_status.text = text


def toggle(app, sid, feature):
    session = app.manager.sessions.get(sid)
    if not session: return
    enabled = not getattr(session, 'automation', {}).get(feature, {}).get('enabled', False)
    if not app.manager.automation_command(sid, feature, enabled):
        app.message.text = '請等待角色登入完成及前一項操作回應'
    refresh(app, sid)


def edit_settings(app, sid):
    session = app.manager.sessions.get(sid)
    if not session: return
    value = copy.deepcopy(getattr(session, 'ai_settings', None) or defaults())
    body = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(10))
    modes = {'普通攻擊': 10001, '自動選擇已知技能': -1, '防禦': 60021}
    selectors = {}
    for profile, name in (('player', '角色'), ('partner', '夥伴')):
        body.add_widget(Label(text=name + '優先行動', size_hint_y=None, height=dp(28)))
        actions = value['profiles'][profile]['orderAction']
        current = actions[0]['id'] if actions else 0
        selector = Spinner(text=next((k for k, v in modes.items() if v == current), '保留既有規則'),
                           values=['保留既有規則'] + list(modes), size_hint_y=None, height=dp(48))
        selectors[profile] = selector
        body.add_widget(selector)
    checks = {}
    for key, text in (('bPlayerDieCloseAI', '角色陣亡時停止'), ('bNPCDieCloseAI', '夥伴陣亡時停止')):
        row = BoxLayout(size_hint_y=None, height=dp(44))
        check = CheckBox(active=value[key], size_hint_x=None, width=dp(48))
        checks[key] = check
        row.add_widget(check); row.add_widget(Label(text=text)); body.add_widget(row)
    note = Label(text='依帳號＋伺服器保存，不依角色區分\n保存後於下次啟動自動戰鬥套用', font_size='13sp')
    body.add_widget(note)
    row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
    save = Button(text='保存'); cancel = Button(text='取消')
    row.add_widget(save); row.add_widget(cancel); body.add_widget(row)
    popup = Popup(title='AI 設定', content=body, size_hint=(.95, .9))
    def persist(*_):
        for key, check in checks.items(): value[key] = check.active
        for profile, selector in selectors.items():
            if selector.text in modes:
                rules = value['profiles'][profile]
                rules['bOrderAction'] = True
                rules['orderAction'] = [dict(id=modes[selector.text], kind=1, target=1)]
        try:
            if not app.manager.save_ai_settings(sid, value): raise ValueError()
        except (ValueError, OSError):
            note.text = '保存失敗，請確認服務連線後重試'; return
        popup.dismiss()
    save.bind(on_release=persist); cancel.bind(on_release=popup.dismiss)
    popup.open()
