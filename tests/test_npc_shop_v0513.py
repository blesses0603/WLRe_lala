"""1262 NPC stores: genuine Eve items, read-only UI, and fail-closed packets."""
import os
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.wire import Packet, ProtocolError
from wlre.network.protocol import decode
from wlre.network.npc_dialogue import close_npc_choice, close_npc_shop
from wlre.network.commands import dispatch
from wlre.services.world.npc_interact import NPCInteractIndex
from wlre.services.world.npc_shop import (
    shop_catalog, purchase_wire_layout, sell_wire_layout, draft_purchase,
)


class NPCShopCatalogueTests(unittest.TestCase):
    def test_real_eve_65_shops_are_readonly_and_accurate(self):
        idx=NPCInteractIndex()
        shops=[]
        for scene,rows in idx.scenes.items():
            for index,row in rows.items():
                if row['form_kind'] in (2,3):
                    cat=shop_catalog(scene,index,index=idx)
                    self.assertIsNotNone(cat,(scene,index))
                    self.assertFalse(cat['verified_prices'])
                    self.assertEqual(cat['form_kind'],row['form_kind'])
                    self.assertTrue(cat['products'])
                    self.assertTrue(all(p['price_gold'] is None and
                                        p['buy_enabled'] is False
                                        for p in cat['products']))
                    self.assertEqual(
                        [(p['offer_index'],p['item_id']) for p in cat['products']],
                        [(p['id'],p['text_id']) for p in row['items'] if p['kind']==3])
                    shops.append(cat)
        self.assertEqual(len(shops),65)
        self.assertEqual(sum(c['form_kind']==2 for c in shops),19)
        self.assertEqual(sum(c['form_kind']==3 for c in shops),46)
        self.assertEqual(shop_catalog(10080,6,index=idx)['products'][0]['item_id'],32297)
        self.assertIsNone(shop_catalog(10000,1,index=idx))

    def test_purchase_preview_is_not_a_payment(self):
        shop=shop_catalog(10080,6)
        draft=draft_purchase(shop,1,2)
        self.assertEqual(draft['item_id'],32297)
        self.assertEqual(draft['count'],2)
        self.assertIsNone(draft['total_gold'])
        self.assertFalse(draft['enabled'])
        for wrong_count in (True,-1,0,10000,1.4):
            with self.subTest(value=wrong_count),self.assertRaises(ProtocolError):
                draft_purchase(shop,1,wrong_count)
        with self.assertRaises(ProtocolError):draft_purchase(shop,254,1)

    def test_lua_purchase_and_sell_wire_layouts_are_only_references(self):
        self.assertEqual(purchase_wire_layout(1,10),Packet(27,1,b'\x01\x0a\x00\x00\x00'))
        self.assertEqual(sell_wire_layout(7,3),Packet(27,3,b'\x07\x03'))
        for index,count in ((True,1),(-1,1),(256,1),(1,0),(1,2**32)):
            with self.subTest(index=index,count=count),self.assertRaises(ProtocolError):
                purchase_wire_layout(index,count)
        for index,count in ((True,1),(-1,1),(256,1),(1,0),(1,256)):
            with self.subTest(index=index,count=count),self.assertRaises(ProtocolError):
                sell_wire_layout(index,count)

    def test_transaction_commands_unregistered_for_live_sending(self):
        logic=Mock()
        logic.world_acknowledged=True
        logic.maintenance.pending=None
        logic.maintenance.uncertain=False
        state=State()
        for kind in ('npc_shop_buy','npc_shop_sell'):
            with self.subTest(kind=kind),self.assertRaises(ProtocolError):
                dispatch(logic,{'type':kind,'confirmed':True,
                                'scene':10080,'offer_index':1,'quantity':1},state)


class ShopServerRepliesTests(unittest.TestCase):
    def test_purchase_result_codes_without_invented_inventory_sync(self):
        for code in range(5):
            event=decode(Packet(27,1,bytes((code,))))
            self.assertEqual(event['type'],'shop_purchase_result')
            self.assertEqual(event['result'],code)
        for bad in (b'',b'\0\0'):
            with self.subTest(bad=bad),self.assertRaises(ProtocolError):
                decode(Packet(27,1,bad))
        self.assertEqual(decode(Packet(27,8,b'\x01'))['type'],'sale_notice')

    def test_shop_close_is_empty_and_never_a_purchase(self):
        state=State()
        state.player={'scene':10080}
        state.npc_dialogue={'active':True,'phase':'choice_unavailable',
                            'scene':10080,'effect_type':6,'option_index':6}
        with self.assertRaises(ProtocolError):
            close_npc_choice(state,{'confirmed':True})
        with self.assertRaises(ProtocolError):
            close_npc_shop(state,{'confirmed':False})
        self.assertEqual(close_npc_shop(state,{'confirmed':True}),[Packet(20,9,b'')])
        self.assertEqual(state.npc_dialogue['phase'],'closing_shop')
        with self.assertRaises(ProtocolError):
            close_npc_shop(state,{'confirmed':True})
        self.assertTrue(state.event_flow['blocked'])
        state.apply(decode(Packet(20,8,b'')))
        self.assertEqual(state.npc_dialogue['phase'],'ended')
        self.assertFalse(state.event_flow['blocked'])

    def test_wrong_scene_and_nonshop_must_not_close(self):
        state=State()
        state.player={'scene':10081}
        state.npc_dialogue={'active':True,'phase':'choice_unavailable',
                            'scene':10080,'effect_type':6,'option_index':6}
        with self.assertRaises(ProtocolError):
            close_npc_shop(state,{'confirmed':True})
        state.player={'scene':10080}
        state.npc_dialogue['option_index']=65535
        with self.assertRaises(ProtocolError):
            close_npc_shop(state,{'confirmed':True})


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk display')
class NPCShopUITests(unittest.TestCase):
    def test_shop_preview_and_safe_close_dialog(self):
        import tkinter as tk
        from wlre.ui.home_map import HomeMap
        root=tk.Tk()
        send=Mock()
        try:
            view=HomeMap(root,Mock(),Mock(),on_npc=send,on_npc_next=send,compact=True)
            view.pack(fill='both',expand=True)
            view.show_map(10080)
            ready={
                'phase':'world_ready','player':{'scene':10080,'role_id':1234},
                'location':{'confirmed_is_current':True,'confirmed':{'scene':10080}},
                'battle':{},'event_flow':{'blocked':True},
                'inventory':{'ready':False,'reliable':False,'items':{}},
                'npc_dialogue':{'active':True,'phase':'choice_unavailable',
                                'effect_type':6,'option_index':6,'scene':10080},
            }
            view.set_state(ready)
            self.assertEqual(str(view.npc_shop_button.cget('state')),'normal')
            self.assertEqual(str(view.npc_close_button.cget('state')),'disabled')
            view.show_npc_shop()
            self.assertTrue(view.npc_shop_window.winfo_exists())
            send.assert_not_called()
            with patch('wlre.ui.home_map.messagebox.askyesno',return_value=True):
                view.close_npc_shop_dialog(shop_catalog(10080,6))
            send.assert_called_once_with({'type':'npc_close_shop','confirmed':True})
        finally:
            for job in root.tk.call('after','info'):
                root.tk.call('after','cancel',job)
            root.destroy()
