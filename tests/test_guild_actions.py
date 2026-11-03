"""Sequential guild operations, precise payment evidence and reset boundaries."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch,Mock
from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.client import SessionLogic
from wlre.network.wire import Packet,ProtocolError
from wlre.services.social import guild_actions as ga
from wlre.services.world.guild_catalog import quote,parse_sell,parse_formulas,parse_organization


def catalog():
    row=dict(id=8,sell_kind=0,save_index=0,base_count=0,base_kind=0,base_formula=0,
             second_kind=4,second_formula=10015,item_id=0,item_count=0,limit_kind=0,total_count=0,limit_flag=0)
    return dict(sell={8:row,9:{**row,'id':9,'second_kind':3},10:{**row,'id':10,'second_kind':3}},
                formulas={10015:dict(kind=2,params=[150]+[0]*11)},
                levels={1:dict(donate_limit=5)})


class GuildActionsTests(unittest.TestCase):
    def setUp(self):
        self.catalog=catalog();self.runtime=SimpleNamespace(guild_catalog=self.catalog,catalog_identity=SimpleNamespace(key='a'*64))
        for name,value in [('current_runtime',self.runtime),('current_catalog_token',(True,'a'*64))]:
            p=patch('wlre.services.world.dynamic_bundle_runtime.'+name,return_value=value)
            p.start();self.addCleanup(p.stop)
        self.state=State(phase='world_ready',initial_data_complete=True)
        self.state.player.update(role_id=1)
        self.state.apply(dict(type='guild_roster',name='測試組織',serial=9,level=1,members={'1':dict(role_id=1,name='甲')}))
        self.feed(Packet(26,4,(1000).to_bytes(4,'little')))
        self.feed(Packet(39,85,b'\x01'));self.feed(Packet(39,87,b'\x05\x01'))
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        self.state.guild_actions['sign_enabled']=False;self.state.guild_actions['donate_enabled']=False
        ga.tick(self.state,True,0)

    def feed(self,packet):self.state.apply(decode(packet))

    def sign_done(self):
        self.state.guild_actions['sign_enabled']=True
        self.assertEqual(ga.tick(self.state,True,1),[Packet(39,69)])
        self.feed(Packet(39,86,b'\x00'));self.feed(Packet(39,85,b'\x02'))
        self.assertEqual(ga.tick(self.state,True,2),[])
        self.assertIsNone(self.state.guild_actions['pending'])

    def pay(self,remaining):
        self.feed(Packet(26,2,(150).to_bytes(4,'little')+b'\x00'))
        self.feed(Packet(39,87,bytes([remaining,1])))

    def test_auto_sign_then_three_gold_donations_exact_packets_and_no_more(self):
        self.sign_done();self.state.guild_actions['donate_enabled']=True
        for n in range(3):
            self.assertEqual(ga.tick(self.state,True,3+n*2),[Packet(10,5,b'\x08\x00')])
            self.assertEqual(ga.tick(self.state,True,3.5+n*2),[])
            self.pay(4-n);self.assertEqual(ga.tick(self.state,True,4+n*2),[])
        self.assertEqual(ga.tick(self.state,True,12),[])
        self.assertEqual(self.state.guild_actions['confirmed'],450)
        self.assertEqual(self.state.gold['amount'],550)
        self.assertEqual(self.state.guild_actions['remaining'],2)

    def test_session_settings_and_real_scheduler_wait_for_each_server_ack(self):
        from wlre.network.service_scheduler import advance_services
        self.logic.command(dict(type='guild_actions',action='settings',sign_enabled=True,
                                donate_enabled=True,target=3,budget=450,sell_id=8),self.state)
        sent=[]
        def advance():
            advance_services(self.logic,self.state,sent.append,lambda p:None,lambda e:None,None)
        advance();advance()
        self.assertEqual(sent,[Packet(39,69)])
        self.feed(Packet(39,86,b'\x00'));advance()
        self.assertEqual(sent,[Packet(39,69)])
        self.feed(Packet(39,85,b'\x02'));advance();advance();advance()
        self.assertEqual(sent,[Packet(39,69),Packet(10,5,b'\x08\x00')])
        self.pay(4);advance();advance()
        self.assertEqual(sent,[Packet(39,69),Packet(10,5,b'\x08\x00'),Packet(10,5,b'\x08\x00')])

    def test_sign_requires_result_and_record_in_both_orders_and_rejects_new_member(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                self.setUp()
                self.assertEqual(ga.begin(self.state,'sign',True,1),[Packet(39,69)])
                events=[Packet(39,86,b'\x00'),Packet(39,85,b'\x02')]
                if reverse:events.reverse()
                self.feed(events[0]);ga.tick(self.state,True,2)
                self.assertIsNotNone(self.state.guild_actions['pending'])
                self.feed(events[1]);ga.tick(self.state,True,3)
                self.assertIsNone(self.state.guild_actions['pending'])
        self.state.guild_actions['sign_attempted']=False;self.feed(Packet(39,85,b'\x03'))
        with self.assertRaises(ProtocolError):ga.begin(self.state,'sign',True,4)

    def test_existing_daily_donations_are_counted_before_login(self):
        self.feed(Packet(39,87,b'\x03\x01'))  # Two of five already used.
        self.state.guild_actions['donate_enabled']=True
        self.assertEqual(ga.tick(self.state,True,1),[Packet(10,5,b'\x08\x00')])
        self.pay(2);ga.tick(self.state,True,2)
        self.assertEqual(ga.tick(self.state,True,3),[])
        self.assertEqual(self.state.guild_actions['confirmed'],150)

    def test_partial_gold_or_remaining_never_allows_next_payment(self):
        for first in ('gold','remaining'):
            with self.subTest(first=first):
                self.setUp();ga.begin(self.state,'donate',True,1)
                gold=Packet(26,2,(150).to_bytes(4,'little')+b'\x00');remaining=Packet(39,87,b'\x04\x01')
                self.feed(gold if first=='gold' else remaining)
                ga.tick(self.state,True,2)
                self.assertIsNotNone(self.state.guild_actions['pending'])
                self.feed(remaining if first=='gold' else gold);ga.tick(self.state,True,3)
                self.assertIsNone(self.state.guild_actions['pending'])

    def test_timeout_rejects_repeated_click_toggles_and_keeps_reserved_budget(self):
        ga.begin(self.state,'donate',True,1);ga.tick(self.state,True,21)
        self.assertTrue(self.state.guild_actions['uncertain'])
        self.assertEqual(self.state.guild_actions['reserved'],150)
        self.pay(4)
        self.logic.command(dict(type='guild_actions',action='settings',sign_enabled=True,donate_enabled=True,
                               target=3,budget=450,sell_id=8),self.state)
        with self.assertRaises(ProtocolError):ga.begin(self.state,'donate',True,100)
        self.assertEqual(ga.tick(self.state,True,100),[])

    def test_unrelated_or_duplicate_gold_and_remaining_regression_freeze(self):
        for variant in ('positive','wrong','duplicate','snapshot','remaining'):
            with self.subTest(variant=variant):
                self.setUp();ga.begin(self.state,'donate',True,1)
                if variant=='positive':self.feed(Packet(26,1,(20).to_bytes(4,'little')+b'\x00'))
                elif variant=='wrong':self.feed(Packet(26,2,(50).to_bytes(4,'little')+b'\x00'))
                elif variant=='snapshot':self.feed(Packet(26,4,(850).to_bytes(4,'little')))
                elif variant=='remaining':
                    self.feed(Packet(39,87,b'\x04\x01'));self.feed(Packet(39,87,b'\x05\x01'))
                else:
                    self.feed(Packet(26,2,(150).to_bytes(4,'little')+b'\x00'))
                    self.feed(Packet(26,2,(150).to_bytes(4,'little')+b'\x00'))
                self.assertTrue(self.state.guild_actions['uncertain'])
                self.assertIsNone(self.state.guild_actions['pending'])

    def test_insufficient_gold_caps_ineligible_and_diamonds_are_rejected(self):
        for key,value in [('budget',149),('remaining',2),('allow',False)]:
            old=self.state.guild_actions[key];self.state.guild_actions[key]=value
            with self.assertRaises(ProtocolError):ga.begin(self.state,'donate',True,1)
            self.state.guild_actions[key]=old
        self.state.gold['amount']=100
        with self.assertRaises(ProtocolError):ga.begin(self.state,'donate',True,1)
        self.state.gold['amount']=1000
        for sell in (9,10):
            self.state.guild_actions['sell_id']=sell
            with self.assertRaisesRegex(ProtocolError,'鑽石'):ga.begin(self.state,'donate',True,1)

    def test_current_price_formula_change_and_untrusted_runtime_cannot_authorize(self):
        self.catalog['formulas'][10015]['kind']=18
        with self.assertRaises(ProtocolError):ga.begin(self.state,'donate',True,1)
        self.catalog['formulas'][10015]['kind']=2;self.catalog['sell'][8]['sell_kind']=2
        with self.assertRaises(ProtocolError):ga.begin(self.state,'donate',True,1)
        self.runtime.catalog_identity=None
        with self.assertRaises(ProtocolError):ga.begin(self.state,'donate',True,1)

    def test_day_reset_requires_new_states_and_preserves_settings(self):
        self.state.guild_actions.update(reserved=450,confirmed=450,sign_state=2)
        self.feed(Packet(39,85,b'\x01'))
        self.assertEqual(self.state.guild_actions['reserved'],450)  # Sign transition does not reset money.
        self.feed(Packet(10,5,b'\x03'))
        self.assertEqual(self.state.guild_actions['reserved'],0)
        self.assertIsNone(self.state.guild_actions['remaining'])
        self.assertEqual(ga.tick(self.state,True,1),[])
        self.feed(Packet(39,85,b'\x02'));self.feed(Packet(39,87,b'\x05\x01'))
        self.state.guild_actions['donate_enabled']=True
        self.assertEqual(ga.tick(self.state,True,2),[Packet(10,5,b'\x08\x00')])

    def test_roster_change_leave_role_disconnect_and_global_pause(self):
        self.state.automation['enabled']=False;self.state.guild_actions['donate_enabled']=True
        self.assertEqual(ga.tick(self.state,True,1),[])
        self.state.automation['enabled']=True;ga.tick(self.state,True,2)
        self.state.apply(dict(type='guild_roster',name='另一組織',serial=10,level=1,members={'1':dict(role_id=1,name='甲')}))
        self.assertTrue(self.state.guild_actions['uncertain'])
        self.assertFalse(self.state.guild_actions['donate_enabled'])
        self.logic.disconnect(self.state)
        self.assertFalse(self.state.guild_actions['sign_enabled'])

    def test_missing_membership_and_unbound_early_state_never_guess(self):
        self.state.guild={};self.state.guild_actions=ga.defaults()
        self.feed(Packet(39,85,b'\x01'));self.feed(Packet(39,87,b'\x05\x01'))
        self.assertIsNone(self.state.guild_actions['sign_state'])
        self.assertIsNone(self.state.guild_actions['remaining'])
        with self.assertRaises(ProtocolError):ga.begin(self.state,'sign',True,1)

    def test_snapshot_counts_and_precise_conditional_wire_layout(self):
        self.feed(Packet(10,5,b'\x02\x02\x01\x03'))
        self.assertEqual(self.state.guild_actions['counts'],{'1':1,'2':3})
        row=self.catalog['sell'][8];row['save_index']=2
        self.assertEqual(ga.begin(self.state,'donate',True,1),[Packet(10,5,b'\x08\x00')])
        self.pay(4);ga.tick(self.state,True,2)
        self.assertIsNotNone(self.state.guild_actions['pending'])
        self.feed(Packet(10,5,b'\x01\x02\x04'));ga.tick(self.state,True,3)
        self.assertIsNone(self.state.guild_actions['pending'])

    def test_malformed_packets_and_invalid_settings_fail_before_send(self):
        for p in (Packet(39,85,b'\x04'),Packet(39,85,b'\x01\x00'),Packet(39,87,b'\x05\x02'),
                  Packet(10,5,b'\x02\x05'),Packet(10,5,b'\x04')):
            with self.subTest(packet=p),self.assertRaises(ProtocolError):decode(p)
        with self.assertRaises(ProtocolError):self.logic.command(dict(type='guild_actions',action='settings',
                sign_enabled=True,donate_enabled=True,target=True,budget=450,sell_id=8),self.state)

    def test_financial_interlocks_block_other_services_until_settled(self):
        from wlre.services.coordination import command_reason,reason
        ga.begin(self.state,'donate',True,1)
        self.assertIn('組織',command_reason(self.state,dict(type='craft')))
        self.assertIn('組織',reason(self.state,'daily_tasks'))
        from wlre.services.instance_rewards import _guard
        with self.assertRaises(ProtocolError):_guard(self.state)


def raw_catalogs():
    from wlre.network.wire import Writer
    w=Writer().i32(3) if hasattr(Writer,'i32') else Writer().raw((3).to_bytes(4,'little'))
    for sell,kind in ((8,4),(9,3),(10,3)):
        w.u16(sell).u8(0).u8(0).u8(0).u8(0).u16(0).u8(kind).u16(10015).u16(0).u8(0).u8(0).u8(0)
        for _ in range(6):w.u32(0)
        w.u8(0)
    f=Writer().raw((1).to_bytes(4,'little')).u16(10015).u8(2).u16(150)
    for _ in range(11):f.u16(0)
    o=Writer().raw((1).to_bytes(4,'little')).u8(1).u32(70000).u8(5)
    for _ in range(3):o.u16(50).u16(80).u16(100)
    for _ in range(12):o.u8(2)
    return {'UISellData_C':w.build(),'FormulaData_C':f.build(),'OrganizationFunctionData_C':o.build()}


class GuildCatalogTests(unittest.TestCase):
    def test_strict_schemas_and_current_gold_diamond_quotes(self):
        raw=raw_catalogs();c=dict(sell=parse_sell(raw['UISellData_C']),
            formulas=parse_formulas(raw['FormulaData_C']),levels=parse_organization(raw['OrganizationFunctionData_C']))
        self.assertEqual(quote(c,8,{},False)['price'],150)
        for i in (9,10):
            with self.assertRaisesRegex(ValueError,'鑽石'):quote(c,i,{},False)
        self.assertEqual(c['levels'][1]['donate_limit'],5)
        for key,parser in [('UISellData_C',parse_sell),('FormulaData_C',parse_formulas),('OrganizationFunctionData_C',parse_organization)]:
            for data in (raw[key][:-1],raw[key]+b'!'):
                with self.subTest(key=key),self.assertRaises(ValueError):parser(data)

    def test_database_bytes_must_match_the_independent_bundle_digest(self):
        import sqlite3,hashlib,tempfile
        from pathlib import Path
        from wlre.services.world.resource_database import record_inventory,read_catalog_tables
        raw=raw_catalogs()['FormulaData_C']
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'db.sqlite3';record_inventory(db,'a'*64,{'tables/FormulaData_C.bytes':raw})
            digest=hashlib.sha256(raw).hexdigest()
            self.assertEqual(read_catalog_tables(db,'a'*64,('guild_formulas',),
                expected_digests={'FormulaData_C.bytes':digest})['guild_formulas'][10015]['params'][0],150)
            changed=bytearray(raw);changed[7:9]=(1).to_bytes(2,'little');changed=bytes(changed)
            with sqlite3.connect(db) as con:
                con.execute('UPDATE resources SET data=?,sha256=? WHERE name=?',
                            (changed,hashlib.sha256(changed).hexdigest(),'FormulaData_C.bytes'))
            with self.assertRaisesRegex(ValueError,'verified Bundle'):
                read_catalog_tables(db,'a'*64,('guild_formulas',),expected_digests={'FormulaData_C.bytes':digest})


import os
import tkinter as tk


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk / Xvfb')
class GuildUITests(unittest.TestCase):
    def setUp(self):
        from wlre.ui.guild_actions_ui import GuildActionsPanel
        self.root=tk.Tk();self.addCleanup(self.root.destroy)
        self.app=SimpleNamespace(live_active=True,send=Mock())
        self.panel=GuildActionsPanel(self.root,self.app);self.panel.pack(fill='both',expand=True)
        self.root.geometry('860x620')
        self.state=State(phase='world_ready');self.state.guild_actions.update(sign_state=1,remaining=5,
            allow=True,catalog_ready=True,price=150,donated=0,role=1,guild=9)
        self.state.guild.update(name='測試組織')
        self.panel.render(self.state.snapshot());self.root.update()

    def test_explicit_settings_and_one_click_actions_without_extra_confirmation(self):
        self.app.send.assert_not_called()
        self.panel.apply.invoke()
        self.app.send.assert_called_once_with(dict(type='guild_actions',action='settings',
            sign_enabled=True,donate_enabled=True,target=3,budget=450,sell_id=8))
        self.app.send.reset_mock();self.panel.sign_button.invoke()
        self.app.send.assert_called_once_with(dict(type='guild_actions',action='sign'))
        self.app.send.reset_mock();self.panel.donate_button.invoke()
        self.app.send.assert_called_once_with(dict(type='guild_actions',action='donate'))

    def test_pending_locks_actions_pause_ack_updates_checkboxes_and_does_not_unlock_uncertainty(self):
        self.state.guild_actions.update(pending={'kind':'donate'})
        self.panel.render(self.state.snapshot())
        self.assertEqual(str(self.panel.apply['state']),'disabled')
        self.assertEqual(str(self.panel.donate_button['state']),'disabled')
        self.panel.pause.invoke();self.app.send.assert_called_once_with(dict(type='guild_actions',action='pause'))
        self.state.guild_actions.update(sign_enabled=False,donate_enabled=False,settings_revision=1,
                                       pending=None,uncertain=True)
        self.panel.render(self.state.snapshot())
        self.assertFalse(self.panel.donate.get());self.assertFalse(self.panel.sign.get())
        self.assertEqual(str(self.panel.donate_button['state']),'disabled')
