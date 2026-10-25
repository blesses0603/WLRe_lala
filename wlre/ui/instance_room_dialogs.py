"""Shared instance room dialogs for main and cooperative modes.

Both modes use the same widget lifecycle, confirmation prompts, and local
single-click locks. Mode-specific coop fields belong to its feature module.
Final authority remains the network-thread instance services.
"""
import time
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.ui.window_layout import configure_dialog
from wlre.features.cooperative.rooms import (
    cooperative_checked_count, cooperative_count_selector,
    cooperative_create_fields, cooperative_join_fields,
)


class InstanceRoomDialogMixin:
    """Preserve the existing InstanceModePage public room actions."""

    def open_create_dialog(self):
        record = self._selected_catalog()
        if not self._creation_ready or record is None:
            return
        if record['kind'] not in (1, 2):
            messagebox.showinfo('副本', '此副本類型尚不支援創建房間。',
                                parent=self.winfo_toplevel())
            return
        root = self.winfo_toplevel()
        dialog = tk.Toplevel(self.app.root if self.app is not None else root)
        dialog.title('建立副本房間')
        dialog.transient(root)
        configure_dialog(dialog,470,355 if self.cooperative else 315)
        form = ttk.Frame(dialog, padding=16)
        form.pack(fill='both', expand=True)
        ttk.Label(form, text=record['name'], style='Heading.TLabel').pack(
            anchor='w', pady=(0, 8))
        ttk.Label(form, text='創房以伺服器回覆為準，送出後不得重複點擊。',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        privacy = tk.StringVar(value='public')
        password = tk.StringVar(value='')
        def change_privacy():
            if privacy.get() == 'public':
                password.set('')
                password_field.state(['disabled'])
            else:
                password_field.state(['!disabled'])
        choices = ttk.Frame(form)
        choices.pack(anchor='w', pady=(0, 6))
        ttk.Radiobutton(choices, text='公開房間', value='public',
                        variable=privacy, command=change_privacy).pack(side='left')
        ttk.Radiobutton(choices, text='私人房間', value='private',
                        variable=privacy, command=change_privacy).pack(side='left', padx=(15, 0))
        ttk.Label(form, text='私人房間密碼（4 位數字）').pack(anchor='w')
        password_field = ttk.Entry(form, textvariable=password, show='*', width=16)
        password_field.pack(anchor='w', pady=(0, 8))
        password_field.state(['disabled'])
        count_var = cooperative_count_selector(form, record) if self.cooperative else None
        buttons = ttk.Frame(form)
        buttons.pack(fill='x')
        def submit():
            if not self._creation_ready or self.app is None or not self.app.live_active:
                messagebox.showwarning('房間狀態', '尚未連線或目前不可創房。', parent=dialog)
                return
            private = privacy.get() == 'private'
            secret = password.get() if private else ''
            if private and (len(secret) != 4 or not secret.isascii()
                            or not secret.isdecimal() or secret == '0000'):
                messagebox.showwarning('私人密碼', '請輸入四位數字且不得為 0000。',
                                       parent=dialog)
                return
            count = None
            if self.cooperative:
                count = cooperative_checked_count(count_var.get(), record)
                if count is None:
                    messagebox.showwarning('房間人數', '協力人數超出副本允許範圍。',
                                           parent=dialog)
                    return
            suffix = '此操作可能消耗門票或點數；沿用目前正常出戰夥伴。\\n' if self.cooperative else ''
            message = ('即將建立「%s」%s房間。\\n%s'
                       '送出後會等待伺服器確認；結果不明時請勿重試。確定嗎？'
                       % (record['name'], '私人' if private else '公開', suffix))
            if not messagebox.askyesno('確認建立副本房間', message, parent=dialog):
                return
            command = {
                'type': 'instance_create', 'mode': self.mode,
                'public': not private, 'password': secret,
            }
            if self.cooperative:
                command.update(cooperative_create_fields(record, count))
            else:
                command['map_id'] = record['map_id']
            # This is only a local click guard; network-thread pending state
            # is authoritative, even if the dialog is re-opened.
            self._creation_ready = False
            self._update_create_button()
            password.set('')
            dialog.destroy()
            self.app.send(command)
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='right')
        ttk.Button(buttons, text='確認建立', command=submit).pack(side='right',
                                                         padx=(0, 8))
        dialog.grab_set()
        dialog.focus_set()

    def open_join_dialog(self):
        room = self.selected_room()
        if not self._join_ready or room is None or self.app is None or not self.app.live_active:
            return
        updated = self._room_data.get('list_updated_at')
        if updated is None or not 0 <= time.monotonic() - updated <= 120:
            messagebox.showwarning('房間清單過期', '請重新更新伺服器房間清單。',
                                   parent=self.winfo_toplevel())
            return
        root = self.winfo_toplevel()
        dialog = tk.Toplevel(self.app.root if self.app is not None else root)
        dialog.title('加入副本房間')
        dialog.transient(root)
        configure_dialog(dialog,460,250 if self.cooperative else 210)
        form = ttk.Frame(dialog, padding=16)
        form.pack(fill='both', expand=True)
        ttk.Label(form, text='房間 #%s（%s）' %
                  (room['room_id'], '公開' if room['public'] else '私人'),
                  style='Heading.TLabel').pack(anchor='w', pady=(0, 8))
        if self.cooperative:
            ttk.Label(form, text='協力加入可能消耗點數／門票，請確認。',
                      style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        secret = tk.StringVar()
        if not room['public']:
            ttk.Label(form, text='私人房間密碼（4 位 ASCII 數字）').pack(anchor='w')
            ttk.Entry(form, textvariable=secret, show='*', width=18).pack(
                anchor='w', pady=(0, 8))
        buttons = ttk.Frame(form)
        buttons.pack(fill='x')

        def submit():
            if not self._join_ready or not self.app.live_active:
                messagebox.showwarning('房間狀態', '房間狀態已變更，請重新整理。',
                                       parent=dialog)
                return
            password = secret.get()
            if not room['public'] and (
                    len(password) != 4 or not password.isascii()
                    or not password.isdecimal() or password == '0000'):
                messagebox.showwarning('私人密碼', '請輸入四位 ASCII 數字，不能為 0000。',
                                       parent=dialog)
                return
            warning = ('協力加入可能消耗點數或門票。\\n'
                       if self.cooperative else '')
            if not messagebox.askyesno(
                    '確認加入', warning + '要加入房間 #%s 嗎？\\n'
                    '只會送出一次，結果不明時請重新登入同步。' % room['room_id'],
                    parent=dialog):
                return
            command = {'type': 'instance_join', 'mode': self.mode,
                       'room_id': room['room_id'], 'password': password}
            if self.cooperative:
                command.update(cooperative_join_fields())
            else:
                command['sn'] = room['sn']
            self._join_ready = False
            self._update_room_buttons()
            secret.set('')
            dialog.destroy()
            self.app.send(command)
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='right')
        ttk.Button(buttons, text='確認加入', command=submit).pack(
            side='right', padx=(0, 8))
        dialog.grab_set()
        dialog.focus_set()

    def request_leave(self):
        if not self._leave_ready or self.app is None or not self.app.live_active:
            return
        current = self._room_data.get('room') or {}
        if not current.get('room_id'):
            return
        if not messagebox.askyesno('確認離開副本房間',
                                   '確定離開房間 #%s？\\n需要伺服器回覆才算成功。'
                                   % current['room_id'],
                                   parent=self.winfo_toplevel()):
            return
        self._leave_ready = False
        self._update_room_buttons()
        self.app.send({'type': 'instance_leave', 'mode': self.mode})

