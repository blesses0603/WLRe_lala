"""CooperativeActions user actions; server authorization remains shared."""
from tkinter import ttk, messagebox


class CooperativeActions:
    def request_standby(self):
        if (not self.cooperative or not self._standby_ready or
                self.app is None or not self.app.live_active):
            return
        room = self._room_data.get('room') or {}
        target = not room.get('standby', False)
        label = '準備／開始配對' if target else '取消準備'
        warning = (
            '房主確認後可能立即開始協力配對／挑戰。\\n'
            '不會切換夥伴，會沿用角色原本出戰的夥伴。\\n'
            if target else '取消目前協力準備／配對，不更換夥伴。\\n'
        )
        if not messagebox.askyesno(
                '確認' + label,
                '房間 #%s：%s？\\n%s' % (room['room_id'], label, warning),
                parent=self.winfo_toplevel()):
            return
        self._standby_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_coop_standby', 'mode': 'coop',
                       'standby': target})


    def request_reward_claim(self):
        if (not self.cooperative or not self._claim_ready or self.app is None
                or not self.app.live_active):
            return
        if not messagebox.askyesno(
                '確認領取免費寶箱',
                '確定領取伺服器目前顯示的免費協力獎勵？\n'
                '包包已同步且預留四格；操作逾時或結果不明不會重送。',
                parent=self.winfo_toplevel()):
            return
        self._claim_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_reward_claim', 'mode': 'coop',
                       'action': 'free'})


    def request_reward_cancel(self):
        if (not self.cooperative or not self._cancel_ready or self.app is None
                or not self.app.live_active):
            return
        if not messagebox.askyesno(
                '確認放棄協力獎勵',
                '確定放棄目前的協力寶箱嗎？此操作可能無法復原。\n'
                '不會購買付費寶箱，取消要求只會送出一次。',
                parent=self.winfo_toplevel()):
            return
        self._cancel_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_reward_cancel', 'mode': 'coop',
                       'confirm_cancel': True})


    def request_auto_reward(self):
        if (not self.cooperative or not self._auto_toggle_ready or self.app is None
                or not self.app.live_active):
            return
        enabled = not self._auto_enabled
        if enabled and not messagebox.askyesno(
                '啟用自動免費領獎',
                '只在收到免費寶箱 S186-11、包包可靠同步且有至少四格空位'
                '時自動領取一次。\n不會購買付費寶箱、不會自動重送。'
                '\n本設定僅對本次登入有效，確定啟用？',
                parent=self.winfo_toplevel()):
            return
        self._auto_toggle_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_auto_reward', 'mode': 'coop',
                       'enabled': enabled})
