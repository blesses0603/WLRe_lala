"""Account-scoped preference activation and persistence on the Tk thread."""
from wlre.storage import account_settings

class AccountController:
    def settings_identity(self):
        if self.live_active and self._settings_key:return self._settings_key
        if not self.host.get().strip() or not self.account.get():return None
        return account_settings.identity(self.host.get(),self.port.get(),self.account.get(),self._selected_line_id)


    def persist_ai_settings(self,value):
        self.assert_ui_thread()
        key=self.settings_identity()
        if key is None:raise ValueError('請先選擇登入帳號，再儲存帳號設定')
        account_settings.save(key,value)


    def activate_account_settings(self,host,port,account):
        self.assert_ui_thread()
        key=account_settings.identity(host,port,account,self._selected_line_id)
        value=account_settings.load(key,legacy_keys=account_settings.legacy_identities(host,port,account,self._selected_line_id))
        self.expedition_panel.load_settings(key)
        self._settings_key=key;self.ai_settings=value
        self.party_guard_panel.set_config(value['party_guard'])
        self.party_guard_panel.update_state({})


