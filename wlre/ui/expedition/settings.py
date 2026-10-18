"""Expedition preference validation and account-safe delayed persistence."""
import tkinter as tk
from tkinter import messagebox
from wlre.services.expedition import preferences, validate, faith_gain, recovery_stock
from wlre.services.items.combat_resources import item_name
from wlre.storage import expedition_settings


class ExpeditionSettingsMixin:
    def config(self):
        return validate({'min_hours': float(self.hours.get()), 'faith_min': int(self.faith.get()),
                         'min_success': float(self.min_success.get()),
                         'item_id': self.items.get(self.item.get(), self.selected_item_id), 'auto_claim': self.auto_claim.get()})

    def update_filter(self, *args):
        if not self.loading_settings:
            self.render(self.app.snapshot)

    def settings_path(self):
        key = self.app.settings_identity()
        if not key: raise ValueError('請先選擇帳號再儲存遠征設定')
        return expedition_settings.settings_file(key)

    def load_settings(self, key):
        if not self.flush_preferences():raise OSError('前一帳號的遠征設定尚未儲存，未切換帳號')
        value = preferences()
        if key:
            try:
                value = expedition_settings.load(key)
            except (OSError, ValueError) as exc:
                self.status.set('遠征設定讀取失敗：' + str(exc))
                raise
        self.key = key
        self.loading_settings = True
        try:
            self.hours.set(str(value['min_hours'])); self.faith.set(str(value['faith_min']))
            self.min_success.set(str(value['min_success']))
            self.auto_claim.set(value['auto_claim'])
            self.selected_item_id = value['item_id']
            self.item.set('')
            self.update_inventory(self.app.snapshot.get('inventory', {}))
        finally:
            self.loading_settings = False

    def save(self):
        try:
            if not self.flush_preferences():raise OSError('先前遠征設定尚未儲存')
            self.settings_path()
            expedition_settings.save(self.app.settings_identity(), self.config())
            self.status.set('已儲存遠征設定；登入後不會自動啟動。')
        except (OSError, ValueError) as exc:
            messagebox.showerror('遠征設定', str(exc), parent=self.app.root)

    def preferences_changed(self, *args):
        if self.loading_settings: return
        try: value = self.config()
        except ValueError: return  # allow partially typed numbers
        if self.key:
            self.pending_preferences = (self.key, value)
            if self.save_job is not None:
                self.after_cancel(self.save_job)
            self.save_job = self.after(750, self.flush_preferences)
        self.update_filter()

    def flush_preferences(self):
        if self.save_job is not None:
            try: self.after_cancel(self.save_job)
            except tk.TclError: pass
            self.save_job = None
        if self.pending_preferences is None: return True
        key, value = self.pending_preferences
        try:
            expedition_settings.save(key, value)
            self.pending_preferences = None
            return True
        except (OSError, ValueError) as exc:
            self.status.set('遠征設定自動儲存失敗：' + str(exc))
            return False

    def start(self):
        try:
            settings = self.config()
            self.save()
        except ValueError as exc:
            messagebox.showerror('遠征設定', str(exc), parent=self.app.root)
            return
        if self.app.send({'type': 'start_expedition', 'settings': settings}) is False:
            self.status.set('連線已結束，請重新登入後再啟動遠征。')

    def update_inventory(self, inventory):
        selected = self.items.get(self.item.get(), self.selected_item_id)
        self.selected_item_id = selected
        self.items = {'自動從背包選擇': 0}
        for sid, count in sorted(recovery_stock(inventory).items()):
            self.items[f'{item_name(sid)}（+{faith_gain(sid)}，可用 {count}）'] = sid
        if selected and selected not in self.items.values():
            self.items[f'{item_name(selected)}（目前無可用庫存）'] = selected
        self.item_combo.configure(values=list(self.items))
        loading = self.loading_settings
        self.loading_settings = True
        try: self.item.set(next(label for label, sid in self.items.items() if sid == selected))
        finally: self.loading_settings = loading

