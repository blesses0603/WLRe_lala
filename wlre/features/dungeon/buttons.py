"""Manual start/entry of normal dungeons, without a second prompt or retry."""
from tkinter import ttk


class DungeonActionsMixin:
    def request_start(self):
        if (self.cooperative or not self._start_ready or
                self.app is None or not self.app.live_active):
            return
        current = self._room_data.get('room') or {}
        room_id = current.get('room_id')
        if not room_id:
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
        self._enter_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_enter', 'mode': 'main'})


def build_dungeon_start_button(page, controls):
    """Keep the original normal-only start button in the shared control row."""
    page.start_button = ttk.Button(
        controls, text='房主開始挑戰',
        command=page.request_start, state='disabled')
    page.start_button.pack(side='left', padx=(8, 0))
