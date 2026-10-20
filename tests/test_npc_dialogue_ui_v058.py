"""NPC UI: explicit confirmation, disabled unverified NPCs, manual next."""
import os
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from wlre.ui.home_map import HomeMap


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt',
                     'Requires Tk display')
class NPCDialogueUITests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.root.geometry('640x520')
        self.send=Mock()
        self.map=HomeMap(self.root,Mock(),Mock(),on_npc=self.send,
                         on_npc_next=self.send,compact=True)
        self.map.pack(fill='both',expand=True)
        self.map.show_map(12903)
        self.npc={'name':'已驗證 NPC','scene':12903,'x':120,'y':80,
                  'npc_id':900,'npc_index':7,'event_count':1,'verified':True}
        self.map.npc_rows=[self.npc]
        self.map.npc_list.delete(0,'end')
        self.map.npc_list.insert('end',self.npc['name'])
        self.ready_state={
            'phase':'world_ready',
            'player':{'scene':12903,'role_id':33,'x':120,'y':80},
            'location':{'confirmed_is_current':True,'confirmed':{'scene':12903,'x':120,'y':80}},
            'event_flow':{'blocked':False},
            'battle':{},'npc_dialogue':{},
        }
        self.map.set_state(self.ready_state)
        self.map.select_npc(self.npc)
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after','info'):
            self.root.tk.call('after','cancel',job)
        self.root.destroy()

    def test_known_text_is_only_displayed_with_valid_catalog(self):
        self.map.npc_talks={456:'這是測試對話，不是正式遊戲文字。'}
        state={**self.ready_state,
               'event_flow':{'blocked':True},
               'npc_dialogue':{'active':True,'phase':'talk',
                               'scene':12903,'text_id':456}}
        self.map.set_state(state)
        self.assertIn('這是測試對話',self.map.npc_message.get())
        self.assertEqual(str(self.map.npc_text_button.cget('state')),'normal')
        with patch('wlre.ui.home_map.messagebox.showinfo') as popup:
            self.map.view_npc_text()
        self.assertEqual(popup.call_count,1)
        self.assertIn('這是測試對話',popup.call_args.args[1])

    def test_close_choice_requires_confirmation(self):
        state={**self.ready_state,
               'event_flow':{'blocked':True},
               'npc_dialogue':{'active':True,'phase':'choice_unavailable',
                               'scene':12903,'effect_type':6,'option_index':15}}
        self.map.set_state(state)
        self.assertEqual(str(self.map.npc_close_button.cget('state')),'normal')
        with patch('wlre.ui.home_map.messagebox.askyesno',return_value=False):
            self.map.close_npc_option()
        self.send.assert_not_called()
        with patch('wlre.ui.home_map.messagebox.askyesno',return_value=True):
            self.map.close_npc_option()
        self.send.assert_called_once_with({'type':'npc_close_choice','confirmed':True})

    def test_unverified_npc_never_enables_packet(self):
        self.npc['verified']=False
        self.map.update_npc_buttons()
        self.assertEqual(str(self.map.npc_talk_button.cget('state')),'disabled')
        self.map.interact_npc()
        self.send.assert_not_called()

    def test_verified_npc_requires_confirmation_and_one_manual_next(self):
        self.assertEqual(str(self.map.npc_talk_button.cget('state')),'normal')
        with patch('wlre.ui.home_map.messagebox.askyesno',return_value=False):
            self.map.interact_npc()
        self.send.assert_not_called()
        with patch('wlre.ui.home_map.messagebox.askyesno',return_value=True):
            self.map.interact_npc()
        self.send.assert_called_once_with({
            'type':'npc_start','confirmed':True,'scene':12903,
            'npc_index':7,'npc_id':900,'x':120,'y':80,
        })
        self.send.reset_mock()
        talking={**self.ready_state,'event_flow':{'blocked':True},
                 'npc_dialogue':{'active':True,'phase':'talk',
                                 'scene':12903,'text_id':456}}
        self.map.set_state(talking)
        self.assertEqual(str(self.map.npc_talk_button.cget('state')),'disabled')
        self.assertEqual(str(self.map.npc_next_button.cget('state')),'normal')
        self.assertIn('456',self.map.npc_message.get())
        self.map.next_npc()
        self.send.assert_called_once_with({'type':'npc_next'})
