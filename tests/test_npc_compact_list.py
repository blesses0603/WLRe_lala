"""The dashboard NPC list must retain space below tabs, even with long status text."""
import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.ui.home_map import HomeMap


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires Tk display')
class CompactNPCListTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.root.geometry('340x280')
        self.send=Mock()
        catalog=SimpleNamespace(data={'source_revision':1286,'source_ready':True},for_scene=lambda _:[])
        with patch('wlre.ui.home_map.Portals',return_value=catalog), \
             patch('wlre.ui.home_map.NPCIndex',return_value=SimpleNamespace(for_scene=lambda _:[])), \
             patch('wlre.ui.home_map.load_npc_talks',return_value={}), \
             patch('wlre.ui.home_map.NPCInteractIndex',return_value=SimpleNamespace(get=lambda *a:None,choices=lambda *a:None)):
            self.page=HomeMap(self.root,Mock(),Mock(),on_npc=self.send,on_npc_next=self.send,
                              compact=True,show_status=False)
        self.page.pack(fill='both',expand=True)
        self.page.npc_tab.master.select(self.page.npc_tab)
        self.npcs=[dict(name=f'開羅測試居民 {i}',scene=12500,npc_index=i,npc_id=900+i,
                       x=100+i,y=200,event_count=1,verified=True) for i in range(1,26)]
        self.page.npc_rows=self.npcs
        for npc in self.npcs:self.page.npc_list.insert('end',npc['name'])
        self.page.selected_id=12500
        self.page.state={'phase':'world_ready','player':{'scene':12500,'role_id':33},
                         'location':{'confirmed_is_current':True,'confirmed':{'scene':12500}},
                         'npc_dialogue':{},'battle':{},'event_flow':{}}
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_small_dashboard_keeps_at_least_three_rows_visible_and_scrollable(self):
        box=self.page.npc_list
        self.assertTrue(box.winfo_ismapped())
        self.assertGreaterEqual(box.winfo_height(),48)
        self.assertIsNotNone(box.bbox(0))
        box.see(24);self.root.update()
        self.assertGreater(box.yview()[0],0)
        self.assertEqual(box.size(),25)
        small=box.winfo_height();self.root.geometry('640x500');self.root.update()
        self.assertGreater(box.winfo_height(),small)
        self.send.assert_not_called()

    def test_long_npc_details_do_not_consume_the_list(self):
        self.page.npc_message.set(('很長的 NPC 說明與伺服器狀態。\n')*30)
        self.root.update()
        self.assertTrue(self.page.npc_list.winfo_ismapped())
        self.assertGreaterEqual(self.page.npc_list.winfo_height(),48)
        self.assertIsNotNone(self.page.npc_list.bbox(0))

    def test_selecting_npc_does_not_send_and_keeps_primary_actions_visible(self):
        self.page.select_npc(self.npcs[0]);self.root.update()
        self.assertEqual(str(self.page.npc_talk_button.cget('state')),'normal')
        self.assertTrue(self.page.npc_talk_button.winfo_viewable())
        self.assertGreaterEqual(self.page.npc_list.winfo_height(),48)
        self.send.assert_not_called()

    def test_more_menu_preserves_disabled_guards_and_original_text_action(self):
        self.page.sync_npc_action_menu()
        for number in range(5):
            self.assertEqual(self.page.npc_action_menu.entrycget(number,'state'),'disabled')
            self.page.npc_action_menu.invoke(number)
        self.send.assert_not_called()
        self.page.npc_talks={123:'測試用對話全文'}
        self.page.state['npc_dialogue']={'active':True,'phase':'talk','scene':12500,'text_id':123}
        self.page.update_npc_buttons();self.page.sync_npc_action_menu()
        entry=next(i for i,(label,_) in enumerate(self.page._npc_menu_buttons) if label=='查看對話全文')
        self.assertEqual(self.page.npc_action_menu.entrycget(entry,'state'),'normal')
        with patch('wlre.features.npc.panel.messagebox.showinfo') as popup:
            self.page.npc_action_menu.invoke(entry)
        self.assertIn('測試用對話全文',popup.call_args.args[1])
        self.send.assert_not_called()

    def test_complete_npc_information_is_read_only_and_not_lost(self):
        text=('完整 NPC 說明。\n')*60
        self.page.npc_message.set(text)
        self.page.show_npc_details();self.root.update()
        content=next(c for c in self.page.npc_detail_window.winfo_children()[0].winfo_children()
                     if isinstance(c,tk.Text))
        self.assertEqual(content.get('1.0','end-1c'),text)
        self.assertEqual(str(content.cget('state')),'disabled')
        self.assertGreaterEqual(self.page.npc_list.winfo_height(),48)
        self.send.assert_not_called()
