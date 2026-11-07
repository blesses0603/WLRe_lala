"""Ark protocol, bounded currency consumption and real scheduler regressions."""
import struct
import unittest
import tempfile
from pathlib import Path
from functools import partial
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch,Mock
from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet,Writer,ProtocolError
from wlre.network.client import SessionLogic
from wlre.services import star_ark as ark
from wlre.services.world import ark_catalog as schema


def raw_catalogs(tail=True):
    star=struct.pack('<iB6H',1,1,120,240,345,445,530,600)
    agent=struct.pack('<iB6IH',1,1,*([10]*6),8246)
    agent+=struct.pack('<BHIHHBH',2,1,10,0,1,50,40001)
    agent+=struct.pack('<BHIHHBH',1,1,10,1,1,50,40001)
    fight=struct.pack('<iHBH',1,1,0,0)+struct.pack('<3IH4H4HB',10,10,10,0,1,0,0,0,500,1,10,0,0)
    fight+=struct.pack('<BII',6,8,28)+b'\0'*36
    if tail:fight+=b'\x01'
    return dict(ArkStarData_C=star,ArkAgentData_C=agent,ArkFightData_C=fight)


def catalog():
    raw=raw_catalogs()
    c=dict(stars=schema.parse_stars(raw['ArkStarData_C']),agents=schema.parse_agents(raw['ArkAgentData_C']),
           fights=schema.parse_fights(raw['ArkFightData_C']),texts={10:'事件',20:'題目',21:'甲',22:'乙',23:'丙',24:'丁'})
    c['agents'][1]['name']='情報員';c['fights'][1]['name']='戰鬥事件'
    return c


def snapshot():
    w=Writer().u8(1).u16(0).u8(1).u8(1).u8(1).u8(1).u8(1).u8(0)
    w.raw(b'\0'*6+b'\0'*60)
    return Packet(191,1,w.build())


def events(kind=1,event_id=1):
    return Packet(191,2,Writer().u16(event_id).u8(kind).u8(1).raw(b'\0'*44).u8(0).build())


class StarArkTests(unittest.TestCase):
    def setUp(self):
        from wlre.storage.ark_questions import QuestionStore
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.question_db=Path(temporary.name)/'ark_questions.sqlite3'
        store_patch=patch.object(ark,'QuestionStore',partial(QuestionStore,self.question_db))
        store_patch.start();self.addCleanup(store_patch.stop)
        self.catalog=catalog();self.runtime=SimpleNamespace(ark_catalog=self.catalog,
            catalog_identity=SimpleNamespace(key='a'*64))
        for name,value in [('current_runtime',self.runtime),('current_catalog_token',(True,'a'*64))]:
            p=patch('wlre.services.world.dynamic_bundle_runtime.'+name,return_value=value)
            p.start();self.addCleanup(p.stop)
        self.state=State(phase='world_ready',initial_data_complete=True)
        self.state.apply(dict(type='world_player',player=dict(role_id=1,x=0,y=0,scene=500)))
        self.state.phase='world_ready'
        self.state.inventory.update(ready=True,reliable=True,capacity=10,items={},revision=1)
        self.state.daily_tasks.update(ready=True,groups_ready=True,catalog_ready=True,catalog_token=(True,'a'*64),
            rows=[dict(cycle=1,condition_kind=9,condition_params=[1,3,0],progress=0,goal=3),
                  dict(cycle=1,condition_kind=9,condition_params=[2,1,0],progress=0,goal=1)])
        self.feed(snapshot());self.feed(events());self.coin(1000)
        self.state.star_ark['enabled']=False
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        ark.tick(self.state,True,0)

    def feed(self,p):self.state.apply(decode(p))

    def coin(self,amount,offset=0,add=True):
        self.feed(Packet(75,24,Writer().u32(amount).u32(offset).u8(int(add)).u8(0).build()))

    def progress(self,subtype,value):
        self.state.daily_tasks['rows'][subtype-1]['progress']=value

    def dispatched(self):self.feed(Packet(191,3,b'\x01\x01\x01\x00'+struct.pack('<H',3636)))

    def test_dispatch_exact_packet_waits_for_money_ship_and_daily_progress_in_any_order(self):
        for order in [('ship','coin','daily'),('daily','coin','ship'),('coin','ship','daily')]:
            with self.subTest(order=order):
                self.setUp()
                self.assertEqual(ark.begin(self.state,'dispatch',True,now=1),[Packet(191,1,b'\x01\x01\x01\x00')])
                for i,part in enumerate(order):
                    if part=='ship':self.dispatched()
                    elif part=='coin':self.coin(880,120,False)
                    else:self.progress(2,1)
                    ark.tick(self.state,True,2+i)
                    self.assertEqual(self.state.star_ark['pending'] is None,i==2)
                self.assertEqual(self.state.star_ark['confirmed'],120)
                self.assertEqual(self.state.star_ark['reserved'],120)
                with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=8)

    def test_discount_and_unity_midpoint_rounding(self):
        a=self.state.star_ark['agents'][1]
        self.catalog['agents'][1]['skills'][0].update(initial=125,add=0)
        self.catalog['stars'][1]['prices'][0]=100
        self.assertEqual(schema.dispatch_quote(self.catalog,1,1,a)['price'],88) # 87.5 -> even
        self.catalog['agents'][1]['skills'][0]['initial']=135
        self.assertEqual(schema.dispatch_quote(self.catalog,1,1,a)['price'],86) # 86.5 -> even

    def test_cost_budget_balance_busy_and_unknown_skills_fail_closed(self):
        for key,value in [('budget',119),('hours',6)]:
            original=self.state.star_ark[key];self.state.star_ark[key]=value
            with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=1)
            self.state.star_ark[key]=original
        self.coin(119)
        with self.assertRaisesRegex(ProtocolError,'星力不足'):ark.begin(self.state,'dispatch',True,now=1)
        self.coin(1000);self.catalog['agents'][1]['skills'][0]['kind']=99
        with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=1)
        self.assertEqual(self.state.star_ark['reserved'],0)

    def test_timeout_and_pause_never_refund_or_resend(self):
        ark.begin(self.state,'dispatch',True,now=1)
        ark.command(self.state,dict(action='pause'),True)
        ark.tick(self.state,True,21)
        self.assertTrue(self.state.star_ark['uncertain'])
        self.assertEqual(self.state.star_ark['reserved'],120)
        with self.assertRaises(ProtocolError):ark.begin(self.state,'dispatch',True,now=30)
        self.assertEqual(ark.tick(self.state,True,30),[])

    def test_duplicate_unrelated_currency_and_mismatched_ship_stop(self):
        for variant in ('duplicate','snapshot','delta','ship','skill'):
            with self.subTest(variant=variant):
                self.setUp();ark.begin(self.state,'dispatch',True,now=1)
                if variant=='duplicate':self.coin(880,120,False);self.coin(760,120,False)
                elif variant=='snapshot':self.coin(880)
                elif variant=='delta':self.coin(990,10,False)
                elif variant=='skill':self.feed(Packet(191,6,b'\x01\x01\x02'))
                else:self.feed(Packet(191,3,b'\x01\x01\x01\x00'+struct.pack('<H',3600)))
                self.assertTrue(self.state.star_ark['uncertain'])

    def test_role_version_daily_generation_disconnect_and_error_invalidate(self):
        for variant in ('role','version','day','disconnect','error'):
            with self.subTest(variant=variant):
                self.setUp();ark.begin(self.state,'dispatch',True,now=1)
                if variant=='role':self.state.player['role_id']=2
                elif variant=='version':
                    p=patch('wlre.services.world.dynamic_bundle_runtime.current_catalog_token',return_value=(True,'b'*64))
                    p.start();self.addCleanup(p.stop)
                elif variant=='day':self.state.daily_tasks['generation']+=1
                elif variant=='disconnect':self.logic.disconnect(self.state)
                else:self.feed(Packet(191,0,b'\x04'))
                ark.tick(self.state,True,2)
                self.assertTrue(self.state.star_ark['uncertain'])

    def start_fight(self):
        self.state.auto_battle['enabled']=True
        return ark.begin(self.state,'fight',True,self.state.star_ark['events'][1],1)

    def win(self):self.feed(Packet(191,15,b'\x01\x01\x00\x01'+struct.pack('<BII',6,8,28)))

    def test_fight_requires_result_completion_and_daily_progress(self):
        self.assertEqual(self.start_fight(),[Packet(191,4,b'\x01\x01\x00')])
        self.feed(Packet(191,10,b'\x01\x01\x00'));ark.tick(self.state,True,2)
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.win();ark.tick(self.state,True,3)
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.progress(1,1);ark.tick(self.state,True,4)
        self.assertIsNone(self.state.star_ark['pending'])
        self.assertEqual(self.state.star_ark['events'][1]['id'],0)

    def test_fight_loss_stops_continuation_and_unknown_rewards_do_not_start(self):
        self.start_fight();self.feed(Packet(191,15,b'\x00'))
        self.assertFalse(self.state.star_ark['enabled'])
        self.assertIsNone(self.state.star_ark['pending'])
        self.state.star_ark['attempted']=[]
        self.catalog['fights'][1]['awards'][0]['kind']=20
        with self.assertRaises(ProtocolError):self.start_fight()

    def test_auto_battle_can_act_in_own_ark_fight_but_other_consumers_wait(self):
        from wlre.services.coordination import reason,command_reason
        self.start_fight();self.state.battle.update(active=True,war_style=19)
        self.assertEqual(reason(self.state,'auto_battle'),'')
        self.assertEqual(command_reason(self.state,dict(type='battle_action')),'')
        for service in ('daily_tasks','guild_actions','crafting','roaming','maintenance'):
            self.assertTrue(reason(self.state,service))
        for command in ('start_alchemy','walk','instance_start','field_item','companion'):
            self.assertTrue(command_reason(self.state,dict(type=command)))
        ark.freeze(self.state.star_ark,'測試結果不明')
        self.assertTrue(reason(self.state,'auto_battle'))
        self.assertTrue(command_reason(self.state,dict(type='battle_action')))

    def test_question_manual_answer_and_only_server_confirmed_correct_answer_is_reused(self):
        self.feed(events(3,2));ark.tick(self.state,True,0)
        self.assertEqual(ark.command(self.state,dict(action='question',index=1),True,1),[Packet(191,6,b'\x01\x02\x00')])
        question=Packet(191,11,struct.pack('<IBII4I',20,6,8,10,21,22,23,24))
        self.feed(question);self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertEqual(self.state.star_ark['question']['text'],'題目')
        self.assertEqual(ark.command(self.state,dict(action='answer',index=2),True,3),[Packet(191,7,b'\x02')])
        with self.assertRaises(ProtocolError):ark.command(self.state,dict(action='answer',index=2),True,4)
        self.feed(Packet(191,12,b'\x01\x02'));self.feed(Packet(191,10,b'\x01\x02\x00'))
        self.progress(1,1);ark.tick(self.state,True,5)
        self.assertEqual(list(self.state.star_ark['answers'].values()),[22])
        self.feed(events(3,3));ark.tick(self.state,True,6)
        ark.command(self.state,dict(action='question',index=1),True,7);self.feed(question)
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,8),[Packet(191,7,b'\x02')])

    def open_question(self,options=(21,22,23,24),event_id=2,now=1):
        self.feed(events(3,event_id));ark.tick(self.state,True,now-1)
        ark.command(self.state,dict(action='question',index=1),True,now)
        self.feed(Packet(191,11,struct.pack('<IBII4I',20,6,8,10,*options)))

    def confirm_question(self):
        self.open_question()
        ark.command(self.state,dict(action='answer',index=2),True,2)
        self.feed(Packet(191,12,b'\x01\x02'));self.feed(Packet(191,10,b'\x01\x02\x00'))
        self.progress(1,1);ark.tick(self.state,True,3)

    def test_persistent_answer_survives_login_reset_and_option_shuffle(self):
        self.confirm_question()
        self.state.apply(dict(type='role_list_available',roles=[]))
        self.state.apply(dict(type='world_player',player=dict(role_id=1,x=0,y=0,scene=500)))
        self.state.phase='world_ready';self.state.initial_data_complete=True
        self.feed(snapshot());self.coin(1000)
        self.state.star_ark.update(enabled=False,dispatch_enabled=False)
        self.open_question((24,23,21,22),event_id=3,now=4)
        self.assertEqual(self.state.star_ark['question']['known_answer'],22)
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,5),[Packet(191,7,b'\x04')])
        self.assertEqual(ark.tick(self.state,True,6),[])

    def test_cached_answer_respects_global_and_local_pause(self):
        self.confirm_question();self.open_question(event_id=3,now=4)
        self.assertEqual(ark.tick(self.state,True,5),[])
        self.state.star_ark['enabled']=True;self.state.automation['enabled']=False
        self.assertEqual(ark.tick(self.state,True,6),[])
        self.state.automation['enabled']=True
        self.assertEqual(ark.tick(self.state,True,7),[Packet(191,7,b'\x02')])

    def test_changed_question_text_does_not_reuse_session_or_permanent_answer(self):
        self.confirm_question();self.catalog['texts'][20]='新題目'
        self.open_question(event_id=3,now=4);self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,5),[])
        self.assertIsNone(self.state.star_ark['question']['known_answer'])

    def test_wrong_reply_never_creates_a_correct_answer(self):
        self.open_question();ark.command(self.state,dict(action='answer',index=1),True,2)
        self.feed(Packet(191,12,b'\x00\x02'))
        self.assertEqual(self.state.star_ark['answers'],{})
        from wlre.storage.ark_questions import QuestionStore
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,
            self.state.star_ark['question']),(None,'unknown'))

    def test_stale_result_cannot_poison_permanent_answers_before_next_tick(self):
        for change in ('day','version','role'):
            with self.subTest(change=change):
                self.setUp();self.open_question()
                ark.command(self.state,dict(action='answer',index=2),True,2)
                if change=='day':self.state.daily_tasks['generation']+=1
                elif change=='role':self.state.player['role_id']=2
                else:
                    with patch.object(ark,'runtime_catalog',return_value=(self.catalog,(True,'b'*64),'new')):
                        self.feed(Packet(191,12,b'\x01\x02'))
                if change!='version':self.feed(Packet(191,12,b'\x01\x02'))
                self.assertEqual(self.state.star_ark['answers'],{})
                from wlre.storage.ark_questions import QuestionStore
                self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,
                    self.state.star_ark['question']),(None,'unknown'))

    def test_corrupt_question_database_preserves_manual_answering(self):
        self.question_db.write_bytes(b'corrupt')
        self.open_question()
        self.assertIn('無法讀寫',self.state.star_ark['question_store_status'])
        self.assertEqual(ark.command(self.state,dict(action='answer',index=2),True,2),[Packet(191,7,b'\x02')])
        self.feed(Packet(191,12,b'\x01\x02'))
        self.assertFalse(self.state.star_ark['uncertain'])
        self.assertEqual(self.question_db.read_bytes(),b'corrupt')

    def test_conflict_recorded_by_another_instance_blocks_cached_automatic_send(self):
        self.confirm_question();self.open_question(event_id=3,now=4)
        from wlre.storage.ark_questions import QuestionStore
        QuestionStore(self.question_db).confirm((True,'a'*64),1,self.state.star_ark['question'],23)
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,5),[])
        self.assertIn('衝突',self.state.star_ark['question_store_status'])

    def arithmetic_question(self):
        self.catalog['texts'].update({20:'3乘上4=？',21:'3',22:'12',23:'7',24:'0'})
        self.open_question((24,21,23,22))

    def test_first_arithmetic_answer_sends_once_and_is_not_stored_as_confirmed(self):
        from wlre.storage.ark_questions import QuestionStore
        self.arithmetic_question()
        q=self.state.star_ark['question']
        self.assertEqual(q['known_answer'],22)
        self.assertIn('尚待伺服器確認',q['answer_source'])
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,q),(None,'unknown'))
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[Packet(191,7,b'\x04')])
        self.assertEqual(ark.tick(self.state,True,3),[])
        self.feed(Packet(191,12,b'\x01\x04'))
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,q),(22,'confirmed'))

    def test_first_arithmetic_answer_respects_pause_and_switch(self):
        self.arithmetic_question()
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.state.star_ark.update(enabled=True,questions_enabled=False)
        self.assertEqual(ark.tick(self.state,True,3),[])
        self.state.star_ark['questions_enabled']=True
        self.state.automation['enabled']=False
        self.assertEqual(ark.tick(self.state,True,4),[])

    def test_rejected_computed_answer_is_quarantined_across_encounters(self):
        self.arithmetic_question();self.state.star_ark['enabled']=True
        ark.tick(self.state,True,2)
        self.feed(Packet(191,12,b'\x00\x01'))
        q=self.state.star_ark['question'];p=self.state.star_ark['pending']
        ark._remember_question(self.state,p,q)
        self.assertIsNone(q['known_answer'])
        self.assertIn('衝突',self.state.star_ark['question_store_status'])

    def test_manual_different_wrong_answer_does_not_quarantine_calculation(self):
        self.arithmetic_question()
        ark.command(self.state,dict(action='answer',index=1),True,2)
        self.feed(Packet(191,12,b'\x00\x01'))
        q=self.state.star_ark['question'];p=self.state.star_ark['pending']
        ark._remember_question(self.state,p,q)
        self.assertEqual(q['known_answer'],22)

    def prepare_candidate(self,qid=63901):
        from wlre.services import ark_candidate_data as data
        from wlre.storage.ark_questions import fingerprint
        record=next(r for r in data.QUESTIONS if r[0]==qid)
        answer,options=record[1:3]
        labels=['離線甲','離線乙','離線丙','離線丁'];text='人工候選測試題'
        q=dict(question=qid,text=text,options=list(options),labels=labels)
        entries=tuple((qid,answer,options,fingerprint(q)[0]) if r[0]==qid else r for r in data.QUESTIONS)
        from wlre.services.ark_candidates import index_digest
        checksum=index_digest(entries,data.QUARANTINED)
        p=patch.object(data,'QUESTIONS',entries);p.start();self.addCleanup(p.stop)
        p=patch.object(data,'INDEX_SHA256',checksum);p.start();self.addCleanup(p.stop)
        self.runtime.catalog_identity=SimpleNamespace(key='a'*64,data_ver=data.DATA_VER,
            packages=[SimpleNamespace(name='DataPackage',full_version=data.PACKAGE_VERSION,
                                      manifest_sha256=data.MANIFEST_SHA256)])
        self.catalog['texts'].update({qid:text,**dict(zip(options,labels))})
        self.feed(events(3,2));ark.tick(self.state,True,0)
        return qid,answer,options

    def open_candidate(self,qid=63901):
        qid,answer,options=self.prepare_candidate(qid)
        ark.command(self.state,dict(action='question',index=1),True,1)
        order=tuple(reversed(options))
        self.feed(Packet(191,11,struct.pack('<IBII4I',qid,6,8,10,*order)))
        return answer,order.index(answer)+1

    def test_reviewed_first_answer_matches_shuffled_id_sends_once_and_learns_only_result(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,position=self.open_candidate();q=self.state.star_ark['question']
        store=QuestionStore(self.question_db)
        self.assertEqual(store.observe((True,'a'*64),1,q),(None,'unknown'))
        self.assertEqual(q['answer_kind'],'reviewed_candidate')
        self.assertIn('可能答錯',q['answer_source'])
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[Packet(191,7,bytes([position]))])
        self.assertEqual(ark.tick(self.state,True,3),[])
        self.assertEqual(store.observe((True,'a'*64),1,q),(None,'unknown'))
        self.feed(Packet(191,12,bytes([1,position])))
        self.assertEqual(store.observe((True,'a'*64),1,q),(answer,'confirmed'))
        self.assertEqual(q['answer_kind'],'server_confirmed')

    def test_candidate_scheduler_requires_no_manual_open_or_answer(self):
        from wlre.network.service_scheduler import advance_services
        qid,answer,options=self.prepare_candidate()
        self.state.star_ark.update(enabled=True,dispatch_enabled=False,fights_enabled=False)
        sent=[]
        def advance():
            with patch('wlre.services.daily_tasks.tick',return_value=[]):
                advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        advance();advance()
        self.assertEqual(sent,[Packet(191,6,b'\x01\x02\x00')])
        self.feed(Packet(191,11,struct.pack('<IBII4I',qid,6,8,10,*reversed(options))))
        advance();advance()
        self.assertEqual(sent[-1],Packet(191,7,bytes([list(reversed(options)).index(answer)+1])))
        self.assertEqual(len(sent),2)

    def test_candidate_quarantine_never_sends_but_manual_answer_available(self):
        from wlre.services import ark_candidate_data as data
        from wlre.services.ark_candidates import index_digest
        quarantined={63906:'測試隔離原因'}
        users={k:v for k,v in data.USER_REVIEWED.items() if k!=63906}
        for name,value in [('QUARANTINED',quarantined),('USER_REVIEWED',users)]:
            p=patch.object(data,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(data,'INDEX_SHA256',index_digest(data.QUESTIONS,quarantined));p.start();self.addCleanup(p.stop)
        _,position=self.open_candidate(63906)
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertIn('有爭議',self.state.star_ark['question_store_status'])
        self.assertEqual(ark.command(self.state,dict(action='answer',index=position),True,3),
                         [Packet(191,7,bytes([position]))])

    def test_candidate_error_quarantines_durably_without_using_reported_other_answer(self):
        from wlre.storage.ark_questions import QuestionStore
        _,position=self.open_candidate();self.state.star_ark['enabled']=True
        ark.tick(self.state,True,2);self.feed(Packet(191,12,b'\x00\x02'))
        q=self.state.star_ark['question']
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,q),(None,'conflict'))
        self.assertEqual(ark.tick(self.state,True,3),[])
        self.assertIsNone(q['known_answer'])

    def test_candidate_pause_toggle_and_unacknowledged_world_do_not_claim_or_send(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,_=self.open_candidate();q=self.state.star_ark['question']
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.state.star_ark.update(enabled=True,questions_enabled=False)
        self.assertEqual(ark.tick(self.state,True,3),[])
        self.state.star_ark['questions_enabled']=True;self.state.automation['enabled']=False
        self.assertEqual(ark.tick(self.state,True,4),[])
        self.state.automation['enabled']=True
        self.assertEqual(ark.tick(self.state,False,5),[])
        self.assertTrue(QuestionStore(self.question_db).claim_candidate((True,'a'*64),1,q,answer))

    def test_candidate_conflicting_server_confirmation_is_quarantined_before_send(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,_=self.open_candidate();q=self.state.star_ark['question']
        different=next(i for i in q['options'] if i!=answer)
        QuestionStore(self.question_db).confirm((True,'a'*64),1,q,different)
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertIn('衝突',self.state.star_ark['question_store_status'])

    def test_manual_candidate_send_persists_pending_without_confirmation(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,position=self.open_candidate();q=self.state.star_ark['question']
        self.assertEqual(ark.command(self.state,dict(action='answer',index=position),True,2),
                         [Packet(191,7,bytes([position]))])
        self.assertTrue(q['selected_candidate'])
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,q),(None,'unknown'))
        ark._remember_question(self.state,self.state.star_ark['pending'],q)
        self.assertIsNone(q['known_answer'])
        self.assertIn('結果未確認',self.state.star_ark['question_store_status'])
        self.feed(Packet(191,12,bytes([0,position])))
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,q),(None,'conflict'))

    def test_manual_candidate_missing_record_still_prevents_auto_retry(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,position=self.open_candidate();q=self.state.star_ark['question']
        store=QuestionStore(self.question_db)
        with store._connection() as db:db.execute('DELETE FROM candidates')
        self.assertEqual(ark.command(self.state,dict(action='answer',index=position),True,2),
                         [Packet(191,7,bytes([position]))])
        ark._remember_question(self.state,self.state.star_ark['pending'],q)
        self.assertIsNone(q['known_answer'])
        self.assertIn('結果未確認',self.state.star_ark['question_store_status'])

    def test_user_reviewed_candidate_remains_unconfirmed(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,position=self.open_candidate(104300);q=self.state.star_ark['question']
        self.assertEqual(q['candidate_source'],'user_reviewed')
        self.assertIn('使用者覆核候選',q['answer_source'])
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[Packet(191,7,bytes([position]))])
        self.assertEqual(QuestionStore(self.question_db).observe((True,'a'*64),1,q),(None,'unknown'))

    def test_candidate_pending_elsewhere_and_reconnect_never_retry(self):
        from wlre.storage.ark_questions import QuestionStore
        answer,_=self.open_candidate();q=self.state.star_ark['question']
        self.assertTrue(QuestionStore(self.question_db).claim_candidate((True,'a'*64),1,q,answer))
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertIn('結果未確認',self.state.star_ark['question_store_status'])
        ark._remember_question(self.state,self.state.star_ark['pending'],q)
        self.assertIsNone(q['known_answer'])

    def test_candidate_live_text_change_or_version_change_blocks_before_send(self):
        answer,_=self.open_candidate();self.catalog['texts'][answer]='更動'
        self.state.star_ark['enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertIn('資料不符',self.state.star_ark['question_store_status'])
        self.catalog['texts'][answer]='離線甲'
        self.runtime.catalog_identity.packages[0].full_version='1297_changed'
        ark._remember_question(self.state,self.state.star_ark['pending'],self.state.star_ark['question'])
        self.assertIsNone(self.state.star_ark['question']['known_answer'])
        self.assertIn('版本不符',self.state.star_ark['question_store_status'])

    def test_candidate_timeout_preserves_unresolved_claim(self):
        from wlre.storage.ark_questions import QuestionStore
        from wlre.services import ark_candidate_data as data
        answer,_=self.open_candidate();q=self.state.star_ark['question']
        self.state.star_ark['enabled']=True;ark.tick(self.state,True,2)
        self.assertEqual(ark.tick(self.state,True,30),[])
        self.assertTrue(self.state.star_ark['uncertain'])
        status=QuestionStore(self.question_db).record_candidate((True,'a'*64),1,q,answer,
                                                                'reviewed_import',data.REVIEW_REVISION)
        self.assertEqual(status,'pending')

    def test_scheduler_requests_question_then_sends_known_answer_without_manual_commands(self):
        from wlre.network.service_scheduler import advance_services
        self.confirm_question();self.feed(events(3,3))
        self.state.star_ark.update(enabled=True,dispatch_enabled=False,fights_enabled=False)
        self.state.daily_tasks['enabled']=False
        sent=[]
        def advance():
            with patch('wlre.services.daily_tasks.tick',return_value=[]):
                advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        advance();advance()
        self.assertEqual(sent,[Packet(191,6,b'\x01\x03\x00')])
        self.feed(Packet(191,11,struct.pack('<IBII4I',20,6,8,10,24,23,21,22)))
        advance();advance()
        self.assertEqual(sent,[Packet(191,6,b'\x01\x03\x00'),Packet(191,7,b'\x04')])
        self.feed(Packet(191,12,b'\x01\x04'));advance()
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.feed(Packet(191,10,b'\x01\x03\x00'));advance()
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.progress(1,2);advance();advance()
        self.assertIsNone(self.state.star_ark['pending'])
        self.assertEqual(len(sent),2)

    def test_automatic_unknown_question_requests_once_then_waits_for_manual_answer(self):
        self.feed(events(3,2))
        self.state.star_ark.update(enabled=True,dispatch_enabled=False,fights_enabled=False)
        self.assertEqual(ark.tick(self.state,True,1),[Packet(191,6,b'\x01\x02\x00')])
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.feed(Packet(191,11,struct.pack('<IBII4I',20,6,8,10,21,22,23,24)))
        self.assertEqual(ark.tick(self.state,True,10000),[])
        self.assertIsNone(self.state.star_ark['pending']['due'])
        self.assertIsNone(self.state.star_ark['question']['selected'])

    def test_automatic_question_respects_toggles_pause_and_daily_goal(self):
        for mode in ('questions','global','local','goal'):
            with self.subTest(mode=mode):
                self.setUp();self.feed(events(3,2))
                self.state.star_ark.update(enabled=True,dispatch_enabled=False,fights_enabled=False)
                if mode=='questions':self.state.star_ark['questions_enabled']=False
                elif mode=='global':self.state.automation['enabled']=False
                elif mode=='local':self.state.star_ark['enabled']=False
                else:self.progress(1,3)
                self.assertEqual(ark.tick(self.state,True,1),[])
                self.assertIsNone(self.state.star_ark['pending'])

    def test_question_setting_is_independent_and_legacy_settings_preserve_it(self):
        value=dict(action='settings',enabled=True,dispatch_enabled=False,fights_enabled=True,hours=1,budget=120)
        ark.command(self.state,{**value,'questions_enabled':False},True)
        ark.command(self.state,value,True)
        self.assertFalse(self.state.star_ark['questions_enabled'])
        with self.assertRaises(ProtocolError):ark.command(self.state,{**value,'questions_enabled':1},True)

    def test_question_switch_blocks_known_answer_but_manual_answer_remains_available(self):
        self.confirm_question();self.open_question(event_id=3,now=4)
        self.state.star_ark.update(enabled=True,questions_enabled=False)
        self.assertEqual(ark.tick(self.state,True,5),[])
        self.assertEqual(ark.command(self.state,dict(action='answer',index=2),True,6),[Packet(191,7,b'\x02')])

    def test_main_items_shops_are_not_auto_executed_and_global_pause_preserves_intent(self):
        self.state.star_ark.update(enabled=True,dispatch_enabled=False)
        self.feed(events(2,2));self.assertEqual(ark.tick(self.state,True,1),[])
        self.assertIn('尚未自動',self.state.star_ark['rows'][0]['execution'])
        self.state.automation['enabled']=False;self.state.star_ark['dispatch_enabled']=True
        self.assertEqual(ark.tick(self.state,True,2),[])
        self.assertEqual(self.state.star_ark['reserved'],0)

    def test_reading_unknown_question_has_no_deadline_but_sent_answer_still_times_out(self):
        self.feed(events(3,2));ark.tick(self.state,True,0)
        ark.command(self.state,dict(action='question',index=1),True,1)
        self.feed(Packet(191,11,struct.pack('<IBII4I',20,6,8,10,21,22,23,24)))
        self.assertIsNone(self.state.star_ark['pending']['due'])
        self.assertEqual(ark.tick(self.state,True,10000),[])
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.assertFalse(self.state.star_ark['uncertain'])
        self.assertEqual(ark.command(self.state,dict(action='answer',index=3),True,10000),[Packet(191,7,b'\x03')])
        self.assertEqual(self.state.star_ark['pending']['due'],10020)
        ark.tick(self.state,True,10021)
        self.assertTrue(self.state.star_ark['uncertain'])

    def test_waiting_for_human_answer_still_invalidates_on_day_or_role_change(self):
        for change in ('role','day'):
            with self.subTest(change=change):
                self.setUp();self.feed(events(3,2));ark.tick(self.state,True,0)
                ark.command(self.state,dict(action='question',index=1),True,1)
                self.feed(Packet(191,11,struct.pack('<IBII4I',20,6,8,10,21,22,23,24)))
                if change=='role':self.state.player['role_id']=2
                else:self.state.daily_tasks['generation']+=1
                ark.tick(self.state,True,2)
                self.assertTrue(self.state.star_ark['uncertain'])
                with self.assertRaises(ProtocolError):ark.command(self.state,dict(action='answer',index=3),True,3)

    def test_real_session_and_scheduler_send_once_and_never_start_dungeons(self):
        from wlre.network.service_scheduler import advance_services
        self.logic.command(dict(type='star_ark',action='settings',enabled=True,dispatch_enabled=True,
                                fights_enabled=False,hours=1,budget=120),self.state)
        # Keep unrelated daily reward interpretation out of this scenario.
        self.state.daily_tasks['enabled']=False
        sent=[]
        with patch('wlre.services.daily_tasks.tick',return_value=[]):
            for _ in range(3):advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        self.assertEqual(sent,[Packet(191,1,b'\x01\x01\x01\x00')])

    def test_real_s124_snapshot_progress_and_scheduler_confirm_dispatch_together(self):
        from test_daily_task_runtime import catalog as daily_catalog,snapshot as daily_snapshot
        from wlre.network.service_scheduler import advance_services
        from wlre.services.daily_tasks import defaults as daily_defaults
        base=daily_catalog()['tasks'][0]
        self.runtime.daily_tasks=dict(tasks=[
            {**base,'condition_kind':9,'condition_params':[1,3,0],'goal':3},
            {**base,'id':2,'index':201,'condition_kind':9,'condition_params':[2,1,0],'goal':1}],rewards=[])
        self.state.daily_tasks=daily_defaults();self.state.daily_tasks.update(role_id=1,enabled=False)
        self.feed(daily_snapshot(progress=0));self.feed(Packet(124,2,b'\x01\x02'))
        self.state.star_ark.update(enabled=True,fights_enabled=False)
        sent=[]
        def advance():advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        advance();self.assertEqual(sent,[Packet(191,1,b'\x01\x01\x01\x00')])
        self.dispatched();self.coin(880,120,False);advance()
        self.assertIsNotNone(self.state.star_ark['pending'])
        self.feed(Packet(124,3,b'\x02\x01\x02\x01'));advance();advance()
        self.assertIsNone(self.state.star_ark['pending'])
        self.assertEqual(self.state.star_ark['confirmed'],120)
        self.assertEqual(sent,[Packet(191,1,b'\x01\x01\x01\x00')])

    def test_other_bag_updates_cannot_confirm_fight_item_rewards(self):
        self.catalog['fights'][1]['awards'][0]=dict(kind=10,id=200,value=1)
        self.start_fight()
        self.feed(Packet(191,15,b'\x01\x01\x00\x01'+struct.pack('<BII',10,200,1)))
        self.feed(Packet(191,10,b'\x01\x01\x00'));self.progress(1,1)
        self.state.inventory.update(revision=2,items={'1':dict(item_id=201,count=1)})
        ark.tick(self.state,True,3);self.assertIsNotNone(self.state.star_ark['pending'])
        self.state.inventory.update(revision=3,items={'1':dict(item_id=201,count=1),'2':dict(item_id=200,count=1)})
        ark.tick(self.state,True,4);self.assertIsNone(self.state.star_ark['pending'])

    def test_other_battle_type_or_event_refresh_cannot_keep_automation_running(self):
        self.start_fight();self.state.battle.update(active=True,war_style=16)
        ark.tick(self.state,True,2)
        self.assertTrue(self.state.star_ark['uncertain'])
        self.setUp();self.start_fight();self.feed(events())
        self.assertTrue(self.state.star_ark['uncertain'])

    def test_wire_and_settings_reject_truncated_trailing_duplicate_and_invalid_values(self):
        packets=[snapshot(),events(),Packet(75,24,struct.pack('<IIBB',1000,0,1,0)),
                 Packet(191,3,b'\x01\x01\x01\x00\x10\x0e'),Packet(191,10,b'\x01\x01\x00')]
        for packet in packets:
            with self.assertRaises(ProtocolError):decode(Packet(packet.main,packet.sub,packet.payload[:-1]))
            with self.assertRaises(ProtocolError):decode(Packet(packet.main,packet.sub,packet.payload+b'\0'))
        for bad in [dict(budget=True),dict(hours=7),dict(enabled=1)]:
            value=dict(action='settings',enabled=True,dispatch_enabled=True,fights_enabled=True,hours=1,budget=120)
            value.update(bad)
            with self.assertRaises(ProtocolError):ark.command(self.state,value,True)


class ArkCatalogTests(unittest.TestCase):
    def test_exact_supported_fight_layouts_and_malformed_records(self):
        for tail in (False,True):
            raw=raw_catalogs(tail)
            self.assertEqual(schema.parse_fights(raw['ArkFightData_C'])[1]['fight'],1)
            for name,parse in [('ArkStarData_C',schema.parse_stars),('ArkAgentData_C',schema.parse_agents),('ArkFightData_C',schema.parse_fights)]:
                with self.assertRaises(ValueError):parse(raw[name]+b'!')
                with self.assertRaises(ValueError):parse(raw[name][:-2])


class ArkGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:self.root=tk.Tk();self.root.withdraw()
        except tk.TclError:self.skipTest('需要原生 Tk 顯示環境')
        self.addCleanup(self.root.destroy)

    def test_settings_pause_and_non_fight_items_do_not_emit_actions(self):
        from wlre.ui.star_ark_ui import StarArkPanel
        app=SimpleNamespace(live_active=True,send=Mock())
        panel=StarArkPanel(self.root,app);d=ark.defaults()
        panel.render(dict(phase='world_ready',star_ark=d))
        panel.budget.set('240');panel.questions.set(False);panel.settings()
        self.assertEqual(app.send.call_args.args[0]['budget'],240)
        self.assertFalse(app.send.call_args.args[0]['questions_enabled'])
        d['status']='收到新狀態';panel.render(dict(phase='world_ready',star_ark=d))
        self.assertEqual(panel.budget.get(),'240')
        panel.pause.invoke();self.assertEqual(app.send.call_args.args[0]['action'],'pause')

    def test_long_question_scrolls_while_all_answers_and_status_stay_visible(self):
        from wlre.ui.star_ark_ui import StarArkPanel
        from wlre.ui.theme_styles import apply_styles
        from tkinter import ttk
        apply_styles(ttk.Style(self.root),self.root,'TkDefaultFont',bg='#102638',panel='#16364b',
                     ink='#eff7ff',muted='#a8c2d1',cyan='#62c9e0')
        app=SimpleNamespace(live_active=True,send=Mock());panel=StarArkPanel(self.root,app)
        panel.pack(fill='both',expand=True);self.root.deiconify()
        d=ark.defaults();d.update(pending=dict(kind='question'),
            question=dict(text='長題目測試。'*500,labels=['答案甲','答案乙','答案丙','答案丁'],selected=None),
            status='等待選擇問答答案；沒有已確認答案時不猜題')
        panel.render(dict(phase='world_ready',star_ark=d))
        for size in ('860x560','1024x600','1080x650'):
            with self.subTest(size=size):
                self.root.geometry(size);self.root.update()
                bottom=panel.winfo_rooty()+panel.winfo_height()
                for widget in (*panel.answers,panel.status_label):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)
                self.assertLess(panel.question_text.yview()[1],1)
                self.assertEqual(str(panel.question_text['state']),'disabled')
                self.assertIn('請選下方答案',panel.event_button['text'])
        app.send.assert_not_called()
        panel.answers[2].invoke()
        app.send.assert_called_once_with(dict(type='star_ark',action='answer',index=3))
