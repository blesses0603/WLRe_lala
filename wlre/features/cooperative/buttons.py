"""UI-only cooperative actions; server confirmation remains authoritative."""


class CooperativeActionsMixin:
    """Keep cooperative UI actions separate from normal dungeon controls."""

    def request_standby(self):
        if (not self.cooperative or not self._standby_ready or
                self.app is None or not self.app.live_active):
            return
        room = self._room_data.get('room') or {}
        target = not room.get('standby', False)
        self._standby_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_coop_standby', 'mode': 'coop',
                       'standby': target})

    def request_reward_claim(self):
        if (not self.cooperative or not self._claim_ready or self.app is None
                or not self.app.live_active):
            return
        self._claim_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_reward_claim', 'mode': 'coop',
                       'action': 'free'})

    def request_reward_cancel(self):
        if (not self.cooperative or not self._cancel_ready or self.app is None
                or not self.app.live_active):
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
        self._auto_toggle_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_auto_reward', 'mode': 'coop',
                       'enabled': enabled})

