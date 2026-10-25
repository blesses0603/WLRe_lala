"""DungeonActions user actions; server authorization remains shared."""
from tkinter import ttk, messagebox


class DungeonActions:
    def request_start(self):
        if (self.cooperative or not self._start_ready or
                self.app is None or not self.app.live_active):
            return
        current = self._room_data.get('room') or {}
        room_id = current.get('room_id')
        if not room_id:
            return
        if not messagebox.askyesno(
                '確認開始副本',
                '房間 #%s：確定由房主開始挑戰嗎？\\n'
                '將沿用角色目前正常出戰的夥伴。\\n'
                '送出後只等待伺服器確認，不會自動重送。' % room_id,
                parent=self.winfo_toplevel()):
            return
        self._start_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_start', 'mode': 'main'})


    def request_enter(self):
        if (self.cooperative or not self._enter_ready or
                self.app is None or not self.app.live_active):
            return
        room_id = (self._room_data.get('room') or {}).get('room_id')
        if not room_id:
            return
        if not messagebox.askyesno(
                '確認進入一般副本',
                '房間 #%s 已經由伺服器開始。\n'
                '確定手動要求進入副本場景？\n'
                '不切換正常出戰夥伴、不自動重送。請以伺服器場景確認為準。' % room_id,
                parent=self.winfo_toplevel()):
            return
        self._enter_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_enter', 'mode': 'main'})
