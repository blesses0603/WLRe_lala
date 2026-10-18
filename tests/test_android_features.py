"""Mobile commands, bounded private histories, scoped preferences and touch pages."""
import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests import test_android_sessions as fixtures
from android_app import features, preferences
from android_app.sessions import Session, SessionManager
from android_app.runtime import Runtime
from wlre.core.state import State
from wlre.services.items.crafting import RECIPES, confirmed_unlocked


class MobileFeatures(unittest.TestCase):
    setUp = fixtures.AndroidSessions.setUp
    start = fixtures.AndroidSessions.start
    runner = fixtures.AndroidSessions.runner
    cleanup = fixtures.AndroidSessions.cleanup
    drain = fixtures.AndroidSessions.drain

    def test_commands_are_isolated_gated_and_core_validated(self):
        first = self.start(); self.ready.clear(); second = self.start('other')
        self.assertFalse(self.manager.game_command(first.session_id, {'type':'reset_efficiency'}))
        first.phase = second.phase = 'world_ready'
        runtime = Runtime(self.manager)
        for command in ({'type':'team','action':'flag','enabled':True}, {'type':'stop_alchemy'},
                        {'type':'craft','action':'pause'}, {'type':'reset_efficiency'}):
            self.assertTrue(runtime.dispatch({'op':'game','id':first.session_id,'command':command}))
            self.assertEqual(first.commands.get_nowait(), command)
            self.assertTrue(second.commands.empty())
        for command in ({'type':'packet','payload':'x'}, {'type':'select_role','index':1}, {'type':'chat','text':'a'*65537}):
            with self.assertRaises(ValueError): self.manager.game_command(first.session_id,command)
        self.manager.stop(first.session_id)
        self.assertFalse(self.manager.game_command(first.session_id,{'type':'reset_efficiency'}))

    def test_histories_survive_activity_and_are_bounded_without_credentials(self):
        session = self.start(); state = State().snapshot()
        state['player'] = dict(role_id=123,name='測試',scene=60000); state['phase']='world_ready'
        self.calls[0][1]['on_state'](state)
        emit = self.calls[0][0]
        for i in range(220):
            emit(dict(type='chat_message',channel='區域',role_id=456,name='附近',text=str(i)))
            emit(dict(type='alchemy_result',item_id=40001,count=1))
        data = Runtime(self.manager).dispatch({'op':'detail','id':session.session_id})
        self.assertEqual(len(data['chat']),200);self.assertEqual(len(data['log']),200)
        self.assertEqual(data['chat'][-1]['name'],'附近')
        self.assertEqual(data['chat'][0]['text'],'20')
        self.assertNotIn('fixture-secret',json.dumps(data))
        self.assertNotIn('password',data['state'])
        state['inventory']['items']['new'] = dict(item_id=1)
        self.assertNotIn('new',data['state']['inventory']['items'])
        self.assertTrue(self.manager.game_command(session.session_id,dict(type='chat',channel='密語',target='附近',text='測試')))
        self.assertEqual(session.commands.get_nowait()['target'],456)
        emit(dict(type='chat_message',channel='密語',role_id=123,target_id=456,text='本機密語'))
        self.assertEqual(self.manager.session_detail(session.session_id)['chat'][-1]['target_id'],456)

    def test_preferences_are_private_and_scoped_without_auto_start(self):
        with tempfile.TemporaryDirectory() as base:
            self.manager.settings_base=base
            session=self.start()
            sid=next(int(k) for k,r in RECIPES.items() if confirmed_unlocked(r))
            value={'favorites':[sid],'plan':[dict(item_id=sid,count=1000)]}
            self.assertTrue(self.manager.save_preferences(session.session_id,value))
            self.assertTrue(session.commands.empty())
            self.assertEqual(self.manager.session_detail(session.session_id)['preferences'],value)
            value['favorites'].clear()
            self.assertEqual(session.preferences['favorites'],[sid])
            files=list(Path(base).rglob('*.json'));self.assertEqual(len(files),1)
            self.assertNotIn('fixture-user',files[0].read_text())
            self.assertNotIn('fixture-secret',files[0].read_text())
            with self.assertRaises(ValueError): preferences.validate({'favorites':[0]})
            with self.assertRaises(ValueError): preferences.validate({'plan':[dict(item_id=sid,count=0)]})


HAS_KIVY=importlib.util.find_spec('kivy') is not None
@unittest.skipUnless(HAS_KIVY and (os.environ.get('DISPLAY') or os.name=='nt'),'Requires Kivy display')
class MobilePages(unittest.TestCase):
    def setUp(self):
        from android_app.app import LaLaApp
        from kivy.clock import Clock
        self.app=LaLaApp();self.root=self.app.build()
        self.addCleanup(lambda:Clock.unschedule(self.app.drain_events))
        self.session=Session('fixture','測試伺服器','fixture-user','fixture.invalid',1234)
        self.session.phase='world_ready';self.app.manager.sessions['fixture']=self.session
        self.session.game_state=State().snapshot()
        self.session.game_state['phase']='world_ready'
        self.session.game_state['player']=dict(role_id=123,name='測試',scene=60000)
        self.session.game_state['knowledge']['player']['stats']=dict(level=14,hp=20,max_hp=50,sp=0,max_sp=30)
        self.app.add_card(self.session)
        self.patch=patch('android_app.widgets.Popup.open');self.patch.start();self.addCleanup(self.patch.stop)
    def test_every_page_constructs_and_refreshes_empty_and_live_state(self):
        from android_app.dashboard import Dashboard,PAGES
        d=Dashboard(self.app,'fixture');self.addCleanup(d.dismissed)
        for name in PAGES:
            d.data={};d.show(name);d.page.refresh()
            d.data=self.app.manager.session_detail('fixture');d.page.refresh()
        self.assertEqual(len(PAGES),11)
        self.assertFalse(any('tkinter' in type(w).__module__ for w in d.popup.walk()))
    def test_full_settings_drafts_all_fields_cancel_and_validate(self):
        from android_app.settings_ui import SettingsEditor,GROUPS
        editor=SettingsEditor(self.app,'fixture')
        for name in editor.TABS:
            editor.tabs.text=name;editor.collect()
        self.assertEqual(editor.value,self.session.ai_settings)
        editor.value['profiles']['player']['orderAction'][0]['id']=60021
        self.assertNotEqual(editor.value,self.session.ai_settings)
        editor.save()
        self.assertEqual(self.session.ai_settings['profiles']['player']['orderAction'][0]['id'],60021)
        self.assertTrue(self.session.commands.empty())
    def test_recipe_and_plan_preview_do_not_send(self):
        from android_app.dashboard import Dashboard
        d=Dashboard(self.app,'fixture');self.addCleanup(d.dismissed)
        d.data=self.app.manager.session_detail('fixture');d.show('製作')
        recipe=next(r for r in RECIPES.values() if confirmed_unlocked(r))
        d.page.recipe(recipe);d.page.plan()
        self.assertTrue(self.session.commands.empty())
    def test_disconnected_dashboard_refuses_game_command(self):
        from android_app.dashboard import Dashboard
        d=Dashboard(self.app,'fixture');self.addCleanup(d.dismissed)
        self.session.active=False
        self.assertFalse(d.send({'type':'reset_efficiency'}));self.assertTrue(self.session.commands.empty())

    def test_alchemy_form_previews_real_core_consumption(self):
        from test_release import setup
        from android_app.dashboard import Dashboard
        state, command = setup()
        self.session.game_state = state.snapshot()
        d = Dashboard(self.app, 'fixture'); self.addCleanup(d.dismissed)
        d.data = self.app.manager.session_detail('fixture'); d.show('煉金')
        page = d.page; page.runs.text = '3'
        for i, value in enumerate(command['materials']):
            page.set_slot(i, state.inventory['items'][str(value['index'])])
            page.slots[i][1].text = str(value['count'])
        with patch.object(d, 'send') as send:
            page.begin()
            send.assert_called_once()
            payload, question = send.call_args.args
            self.assertEqual(payload['runs'], 3)
            self.assertIn('共消耗', question)
        self.assertTrue(self.session.commands.empty())

    def test_manual_battle_form_payload_passes_actual_core_round_guards(self):
        from test_party_guard import battle
        from android_app.dashboard import Dashboard
        state, logic = battle()
        self.session.game_state = state.snapshot()
        d = Dashboard(self.app, 'fixture'); self.addCleanup(d.dismissed)
        d.data = self.app.manager.session_detail('fixture'); d.show('戰場陣形')
        page = d.page
        page.set_mode('3:1', 'defend'); page.set_mode('3:2', 'defend')
        page.submit()
        command = self.session.commands.get_nowait()
        self.assertEqual(command['actor_pids'], {'3:1': 111, '3:2': 9101})
        packets = logic.command(command, state)
        self.assertEqual(len(packets), 2)
        state.battle['round'] += 1
        with self.assertRaises(ValueError): logic.command(command, state)

    def test_card_ai_button_attaches_account_before_loading_skill_choices(self):
        from android_app.automation_ui import edit_settings
        self.app.manager.background = True
        self.app.manager.available = True
        self.app.manager.watch = __import__('unittest.mock', fromlist=['Mock']).Mock()
        with patch.object(self.app.manager, 'session_detail', return_value={}):
            d = edit_settings(self.app, 'fixture')
        self.addCleanup(d.dismissed)
        self.app.manager.watch.assert_called_once_with('fixture')
        self.assertEqual(d.page_name, 'AI與補給設定')
        self.assertEqual(d.data, {})
        d.page.open('角色規則')
        self.assertIn('等待本帳號設定', d.message.text)

    def test_tab_switch_preserves_forms_and_chat_waits_for_matching_ack(self):
        from android_app.dashboard import Dashboard
        d = Dashboard(self.app, 'fixture'); self.addCleanup(d.dismissed)
        d.data = self.app.manager.session_detail('fixture')
        d.show('煉金'); alchemy = d.page; alchemy.runs.text = '7'
        d.show('聊天'); chat = d.page; chat.text.text = '測試聊天'
        chat.send()
        command = self.session.commands.get_nowait()
        self.assertEqual(command['text'], '測試聊天')
        self.assertEqual(chat.text.text, '測試聊天')
        self.assertTrue(chat.pending)
        d.show('煉金'); self.assertIs(d.page, alchemy); self.assertEqual(d.page.runs.text,'7')
        chat.ack({'status':'sent','request_id':'old','text':'測試聊天'})
        self.assertTrue(chat.pending)
        d.chat_ack({'status':'rejected','request_id':command['request_id']})
        self.assertFalse(chat.pending); self.assertEqual(chat.text.text,'測試聊天')
        d.show('聊天'); chat.send(); sent = self.session.commands.get_nowait()
        d.chat_ack({'status':'sent','request_id':sent['request_id'],'text':'測試聊天'})
        self.assertFalse(chat.pending); self.assertEqual(chat.text.text,'')
