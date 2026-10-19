"""Main/cooperative instance browser using only verified server snapshots."""
import time
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.services.instance_browser import entries_for


class InstanceModePage(ttk.Frame):
    """Room browser; mutations remain locked pending official live validation."""

    def __init__(self, parent, *, cooperative, app=None):
        super().__init__(parent, padding=12)
        self.cooperative = cooperative
        self.mode = 'coop' if cooperative else 'main'
        self.app = app
        title = '協力副本' if cooperative else '主要副本'
        ttk.Label(self, text=title, style='Heading.TLabel').pack(anchor='w', pady=(2, 6))
        self.note = tk.StringVar(value='尚未查詢房間。請登入後手動更新。')
        ttk.Label(self, textvariable=self.note, style='Muted.TLabel', anchor='w').pack(fill='x', pady=(0, 10))
        self.catalog_records = entries_for(self.mode)
        # Pin room actions above both listings: chat can clip the page bottom.
        self.catalog_heading = ttk.Label(
            self, text="1262 官方副本清單（靜態資料，非房間即時狀態）",
            style='Muted.TLabel')
        self.catalog_heading.pack(anchor='w', pady=(0, 3))
        self.catalog_columns = ('id', 'name', 'level', 'players', 'time')
        catalog_host = ttk.Frame(self)
        catalog_host.pack(fill='x', pady=(0, 4))
        self.catalog_table = ttk.Treeview(
            catalog_host, columns=self.catalog_columns,
            show='headings', selectmode='browse',
            height=4 if cooperative else 5)
        for field, title, width in (
            ('id', 'ID', 48), ('name', '官方中文名稱／版本', 210),
            ('level', '等級', 66), ('players', '人數', 76),
            ('time', '時間', 80)
        ):
            self.catalog_table.heading(field, text=title)
            self.catalog_table.column(field, width=width, anchor='w', stretch=True)
        scroll = ttk.Scrollbar(catalog_host, orient='vertical',
                               command=self.catalog_table.yview)
        self.catalog_table.configure(yscrollcommand=scroll.set)
        self.catalog_table.pack(side='left', fill='x', expand=True)
        scroll.pack(side='right', fill='y')
        for index, record in enumerate(self.catalog_records):
            variant = (' (版本 %s)' % record['variant']) if record['variant'] else ''
            members = ('%s～%s' % (record['min_members'], record['max_members'])
                       if record['max_members'] else '依活動')
            duration = ('%s 分' % record['time_minutes']
                        if record['time_minutes'] else '依活動')
            self.catalog_table.insert('', 'end', iid='catalog_%s' % index,
                values=(record['id'], record['name'] + variant,
                        record['min_level'] or '依活動', members, duration))
        self.catalog_detail = tk.StringVar(value='點選官方副本名稱可查看來源 ID 與獎勵資料筆數。')
        ttk.Label(self, textvariable=self.catalog_detail,
                  style='Muted.TLabel').pack(fill='x', pady=(0, 5))
        self.catalog_table.bind('<<TreeviewSelect>>', self.on_catalog_selected)
        ttk.Label(self, text='伺服器房間清單', style='Muted.TLabel').pack(
            anchor='w', pady=(0, 2))
        self.columns = ('name', 'requirement', 'status')
        self.entries = ttk.Treeview(
            self, columns=self.columns, show='headings', selectmode='browse', height=3
        )
        for key, heading, width in (
            ('name', '房間／副本', 240),
            ('requirement', '人數／條件', 220),
            ('status', '公開狀態', 150),
        ):
            self.entries.heading(key, text=heading)
            self.entries.column(key, width=width, stretch=True, anchor='w')
        self.entries.pack(fill='both', expand=True)
        self.entries.bind('<<TreeviewSelect>>', self.on_room_selected)
        self._room_rows = []
        self._join_ready = False
        self._leave_ready = False
        self._room_data = {}
        self._room_other = {}
        self.details = tk.StringVar(value='沒有已確認的副本房間；進入與領獎功能尚未開放。')
        ttk.Label(self, textvariable=self.details, style='Muted.TLabel',
                  anchor='w').pack(fill='x', pady=(10, 8))
        controls = ttk.Frame(self)
        # The buttons remain visible in a compact (720p) main window.
        controls.pack(fill='x', before=self.catalog_heading, pady=(0, 5))
        self.refresh_button = ttk.Button(
            controls, text='更新房間清單', command=self.refresh_rooms, state='disabled')
        self.refresh_button.pack(side='left')
        self.create_button = ttk.Button(
            controls, text='建立公開／私人房間', command=self.open_create_dialog,
            state='disabled')
        self.create_button.pack(side='left', padx=(10, 0))
        self._creation_ready = False
        self._standby_ready = False
        self._start_ready = False
        self._enter_ready = False
        self._claim_ready = False
        self._cancel_ready = False
        self._auto_toggle_ready = False
        self._auto_enabled = False
        self.join_button = ttk.Button(
            controls, text='加入房間', command=self.open_join_dialog, state='disabled')
        self.join_button.pack(side='left', padx=(10, 0))
        self.leave_button = ttk.Button(
            controls, text='離開房間', command=self.request_leave, state='disabled')
        self.leave_button.pack(side='left', padx=(6, 0))
        if self.cooperative:
            self.standby_button = ttk.Button(
                controls, text='準備／開始配對',
                command=self.request_standby, state='disabled')
            self.standby_button.pack(side='left', padx=(8, 0))
            self.companion_note = tk.StringVar(
                value='出戰夥伴：沿用一般戰鬥設定（尚未同步）')
            ttk.Label(self, textvariable=self.companion_note,
                      style='Muted.TLabel').pack(
                          anchor='w', before=self.catalog_heading)
            reward_controls = ttk.Frame(self)
            reward_controls.pack(
                fill='x', before=self.catalog_heading, pady=(3, 2))
            self.claim_button = ttk.Button(
                reward_controls, text='領取免費協力獎勵',
                command=self.request_reward_claim, state='disabled')
            self.claim_button.pack(side='left')
            self.cancel_reward_button = ttk.Button(
                reward_controls, text='放棄目前寶箱',
                command=self.request_reward_cancel, state='disabled')
            self.cancel_reward_button.pack(side='left', padx=(8, 0))
            self.auto_reward_button = ttk.Button(
                reward_controls, text='開啟免費獎勵自動領取',
                command=self.request_auto_reward, state='disabled')
            self.auto_reward_button.pack(side='left', padx=(8, 0))
            self.reward_note = tk.StringVar(value='獎勵：等待 S186-11 同步；不會自動購買付費寶箱')
            ttk.Label(self, textvariable=self.reward_note, style='Muted.TLabel',
                      anchor='w').pack(fill='x', before=self.catalog_heading)
        if not self.cooperative:
            self.start_button = ttk.Button(
                controls, text='房主開始挑戰',
                command=self.request_start, state='disabled')
            self.start_button.pack(side='left', padx=(8, 0))
        self.enter_button = ttk.Button(controls, text='進入副本',
                                       command=self.request_enter, state='disabled')
        self.enter_button.pack(side='right')

    def on_catalog_selected(self, _event=None):
        selection = self.catalog_table.selection()
        if not selection:
            return
        index = int(selection[0].removeprefix('catalog_'))
        record = self.catalog_records[index]
        self._update_create_button()
        self.catalog_detail.set(
            '副本 ID %s｜場景 %s｜獎勵資料 %s 筆；是否可進入仍以伺服器為準' %
            (record['id'], record['map_id'], len(record['awards'])))

    def _selected_catalog(self):
        selected = self.catalog_table.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].removeprefix('catalog_'))
            return self.catalog_records[index]
        except (ValueError, IndexError):
            return None

    def _update_create_button(self):
        record = self._selected_catalog()
        eligible = (self._creation_ready and record is not None
                    and record['kind'] in (1, 2))
        self.create_button.state(['!disabled'] if eligible else ['disabled'])

    def open_create_dialog(self):
        record = self._selected_catalog()
        if not self._creation_ready or record is None:
            return
        if record['kind'] not in (1, 2):
            messagebox.showinfo('副本', '此副本類型尚不支援創建房間。',
                                parent=self.winfo_toplevel())
            return
        root = self.winfo_toplevel()
        dialog = tk.Toplevel(root)
        dialog.title('建立副本房間')
        dialog.transient(root)
        dialog.resizable(False, False)
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
        count_var = tk.StringVar(value=str(record['min_members']))
        if self.cooperative:
            ttk.Label(form, text='協力房間人數').pack(anchor='w')
            ttk.Spinbox(form, from_=record['min_members'], to=record['max_members'],
                        textvariable=count_var, width=8).pack(anchor='w', pady=(0, 8))
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
                try:
                    count = int(count_var.get())
                except ValueError:
                    count = 0
                if count < record['min_members'] or count > record['max_members']:
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
                command.update(dungeon_id=record['id'], player_count=count,
                               confirm_cost=True)
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

    def selected_room(self):
        selected = self.entries.selection()
        if not selected:
            return None
        try:
            return self._room_rows[int(selected[0].removeprefix('room_'))]
        except (IndexError, ValueError, KeyError):
            return None

    def on_room_selected(self, _event=None):
        self._update_room_buttons()

    def _update_room_buttons(self):
        room = self.selected_room()
        joinable = (self._join_ready and room is not None
                    and (room.get('capacity') is None
                         or room.get('members', 0) < room['capacity']))
        self.join_button.state(['!disabled'] if joinable else ['disabled'])
        self.leave_button.state(['!disabled'] if self._leave_ready else ['disabled'])
        if not self.cooperative and hasattr(self, 'start_button'):
            self.start_button.state(
                ['!disabled'] if self._start_ready else ['disabled'])
        if self.cooperative and hasattr(self, 'standby_button'):
            self.standby_button.state(
                ['!disabled'] if self._standby_ready else ['disabled'])
        self.enter_button.state(['!disabled'] if self._enter_ready else ['disabled'])
        if self.cooperative and hasattr(self, 'claim_button'):
            self.claim_button.state(['!disabled'] if self._claim_ready else ['disabled'])
            self.cancel_reward_button.state(['!disabled'] if self._cancel_ready else ['disabled'])
            self.auto_reward_button.state(['!disabled'] if self._auto_toggle_ready else ['disabled'])

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
        dialog = tk.Toplevel(root)
        dialog.title('加入副本房間')
        dialog.transient(root)
        dialog.resizable(False, False)
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
                command['confirm_cost'] = True
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

    def refresh_rooms(self):
        if self.app is not None and self.app.live_active:
            self.app.send({'type': 'instance_refresh', 'mode': self.mode})

    def render(self, data, *, live=False, other=None,
               local_role_id=None, active_npc_id=None, local_scene=None,
               activity_blocked=False, inventory=None):
        other = other or {}
        self._room_data = dict(data)
        self._room_other = dict(other)
        if self.cooperative:
            companion = ('NPC ID %s' % active_npc_id
                         if isinstance(active_npc_id, int) and active_npc_id > 0
                         else '目前沒有確認出戰的夥伴')
            self.companion_note.set(
                '正常出戰夥伴：' + companion + '（協力不會切換或指定夥伴）')
        def blocked(part):
            return (part.get('room') is not None
                    or any(part.get(k) is not None for k in
                           ('create_pending','join_pending','leave_pending','standby_pending','start_pending', 'enter_pending',
                            'claim_pending', 'cancel_pending'))
                    or any(part.get(k) for k in
                           ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain','start_uncertain', 'enter_uncertain',
                            'reward_uncertain')))
        active = bool(live) and not blocked(data) and not blocked(other)
        updated = data.get('list_updated_at')
        fresh = (updated is not None and
                 0 <= time.monotonic() - updated <= 120)
        self._join_ready = active and data.get('ready') and fresh
        self._leave_ready = (
            bool(live) and data.get('room') is not None
            and not any(data.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending','start_pending', 'enter_pending'))
            and not any(data.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain','start_uncertain', 'enter_uncertain'))
            and not any(other.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending','start_pending', 'enter_pending'))
            and not any(other.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain','start_uncertain', 'enter_uncertain'))
            and (self.cooperative and not data.get('standby')
                 or not self.cooperative and data.get('phase') == 'waiting'))
        member_data = data.get('members') or []
        current_room = data.get('room') or {}
        room_capacity = current_room.get('capacity')
        full = (isinstance(room_capacity, int) and room_capacity > 0
                and len(member_data) == room_capacity)
        self._standby_ready = (
            self.cooperative and bool(live) and full
            and member_data[0].get('role_id') == local_role_id
            and data.get('phase') == 'waiting'
            and type(current_room.get('standby')) is bool
            and not any(data.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending','start_pending', 'enter_pending'))
            and not any(data.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain','start_uncertain', 'enter_uncertain'))
            and not any(other.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending','start_pending', 'enter_pending'))
            and not any(other.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain','start_uncertain', 'enter_uncertain')))
        inventory = inventory or {}
        reward = data.get('reward') or {}
        bag_capacity = inventory.get('capacity')
        bag_items = inventory.get('items')
        safe_bag = (
            inventory.get('ready') is True and inventory.get('reliable') is True
            and type(bag_capacity) is int and 1 <= bag_capacity <= 255
            and isinstance(bag_items, dict)
            and bag_capacity - len(bag_items) >= 4
            and not any(inventory.get(k) for k in (
                'holds', 'alchemy_slots', 'expedition_slots', 'maintenance_slots'))
            and not any((inventory.get('reserved') or {}).values())
            and not (inventory.get('field_supply') or {}).get('pending')
        )
        reward_busy = any(data.get(k) for k in (
            'claim_pending', 'cancel_pending', 'reward_uncertain'))
        reward_operation_busy = any(
            part.get(k) is not None for part in (data, other)
            for k in ('create_pending', 'join_pending', 'leave_pending',
                      'standby_pending', 'start_pending', 'enter_pending'))
        reward_operation_busy = reward_operation_busy or any(
            part.get(k) for part in (data, other)
            for k in ('create_uncertain', 'join_uncertain', 'leave_uncertain',
                      'standby_uncertain', 'start_uncertain', 'enter_uncertain'))
        can_reward = (self.cooperative and bool(live) and not activity_blocked
                      and not reward_busy and not reward_operation_busy
                      and not other.get('room'))
        reward_fp = (reward.get('reward_count'), reward.get('win_stage'),
                     reward.get('open_reward'), reward.get('reward_mark'),
                     reward.get('npc_id')) if reward else None
        self._auto_enabled = bool(data.get('auto_claim_enabled'))
        self._auto_toggle_ready = (
            self.cooperative and bool(live) and not data.get('reward_uncertain'))
        self._claim_ready = (
            can_reward and safe_bag and reward.get('open_reward') == 1
            and type(reward.get('reward_mark')) is int
            and reward['reward_mark'] & 1 != 0
            and data.get('reward_handled_fingerprint') != reward_fp)
        self._cancel_ready = (
            can_reward and reward.get('open_reward') in (1, 2)
            and data.get('reward_handled_fingerprint') != reward_fp)
        if self.cooperative:
            self.auto_reward_button.configure(
                text='關閉免費獎勵自動領取' if self._auto_enabled
                else '開啟免費獎勵自動領取')
            if reward.get('open_reward') == 2:
                reward_text = '付費寶箱待處理；不會自動購買或扣點'
            elif reward.get('open_reward') == 1:
                reward_text = '免費寶箱待領' if safe_bag else '免費寶箱待領；包包空位未確認'
            elif reward:
                reward_text = '獎勵已同步，目前沒有開啟的寶箱'
            else:
                reward_text = '尚未收到 S186-11 協力獎勵狀態'
            if data.get('claim_pending') or data.get('cancel_pending'):
                reward_text = '獎勵操作待伺服器確認，不可重送'
            elif data.get('reward_uncertain'):
                reward_text = '獎勵操作結果不明，請重新登入確認'
            self.reward_note.set('獎勵：%s；自動領取%s' %
                                 (reward_text, '開' if self._auto_enabled else '關'))
        # Normal-dungeon start is host only. S85-4 roster must agree with
        # the room count, and the official StageData minimum must be met.
        stage = next((record for record in self.catalog_records
                      if record['kind'] == 1 and
                      record['map_id'] == current_room.get('room_id')), None)
        valid_roster = (type(current_room.get('members')) is int
                        and current_room['members'] == len(member_data)
                        and any(member.get('role_id') == local_role_id
                                for member in member_data))
        min_reached = (stage is not None and valid_roster
                       and stage['min_members'] <= len(member_data)
                       <= stage['max_members'])
        self._start_ready = (
            not self.cooperative and bool(live) and min_reached
            and data.get('phase') == 'waiting'
            and current_room.get('host_id') == local_role_id
            and not any(part.get(k) is not None
                        for part in (data, other)
                        for k in ('create_pending', 'join_pending',
                                  'leave_pending', 'standby_pending', 'start_pending', 'enter_pending'))
            and not any(part.get(k)
                        for part in (data, other)
                        for k in ('create_uncertain', 'join_uncertain',
                                  'leave_uncertain', 'standby_uncertain', 'start_uncertain', 'enter_uncertain')))
        self._enter_ready = (
            not self.cooperative and bool(live) and not activity_blocked
            and data.get('phase') == 'started'
            and type(local_scene) is int and local_scene > 0
            and local_scene != current_room.get('room_id')
            and stage is not None
            and any(member.get('role_id') == local_role_id for member in member_data)
            and not other.get('room')
            and not any(part.get(k) is not None
                        for part in (data, other)
                        for k in ('create_pending', 'join_pending', 'leave_pending',
                                  'standby_pending', 'start_pending', 'enter_pending'))
            and not any(part.get(k)
                        for part in (data, other)
                        for k in ('create_uncertain', 'join_uncertain', 'leave_uncertain',
                                  'standby_uncertain', 'start_uncertain', 'enter_uncertain')))
        # Apply the same cross-mode pending/uncertain reward locks as the
        # network services. Disabled buttons must not imply a safe operation.
        all_modes = (data, other)
        reward_locked = any(
            part.get(k) for part in all_modes
            for k in ('claim_pending', 'cancel_pending', 'reward_uncertain'))
        if reward_locked or activity_blocked:
            self._leave_ready = False
            self._standby_ready = False
            self._start_ready = False
            self._enter_ready = False
        self._creation_ready = (
            bool(live) and not reward_locked and not activity_blocked
            and not data.get('create_pending')
            and not data.get('create_uncertain') and not data.get('room')
            and not other.get('create_pending')
            and not other.get('create_uncertain') and not other.get('room')
            and not any(data.get(k) for k in ('join_pending','leave_pending','join_uncertain','leave_uncertain','standby_pending','standby_uncertain','start_pending', 'enter_pending','start_uncertain', 'enter_uncertain'))
            and not any(other.get(k) for k in ('join_pending','leave_pending','join_uncertain','leave_uncertain','standby_pending','standby_uncertain','start_pending', 'enter_pending','start_uncertain', 'enter_uncertain')))
        self._update_create_button()
        self.refresh_button.state(['!disabled'] if live else ['disabled'])
        self.note.set(data.get('status', '尚未查詢房間') if live else '尚未連線，無法查詢副本房間')
        rooms = data.get('rooms', ())
        # Refresh a small, bounded list; never invent known dungeon names.
        previous = self.selected_room()
        key = (previous['room_id'], previous.get('sn')) if previous else None
        self.entries.delete(*self.entries.get_children())
        self._room_rows = list(rooms)
        matched = None
        for index, room in enumerate(rooms):
            room_id = room['room_id']
            capacity = room.get('capacity')
            count = room.get('members', 0)
            occupancy = '%s/%s 人' % (count, capacity) if capacity is not None else '%s 人' % count
            self.entries.insert('', 'end', iid='room_%s' % index, values=(
                '房間 #%s' % room_id,
                occupancy,
                '公開' if room.get('public') else '私人',
            ))
            if key == (room_id, room.get('sn')):
                matched = 'room_%s' % index
        if matched is not None:
            self.entries.selection_set(matched)
        self._update_room_buttons()
        if self.cooperative:
            self.standby_button.configure(
                text='取消準備' if current_room.get('standby') else '準備／開始配對')
            self.standby_button.state(
                ['!disabled'] if self._standby_ready else ['disabled'])
        current = data.get('room')
        if current is not None:
            count = len(data.get('members') or ())
            status = '目前房間 #%s' % current.get('room_id', '待確認')
            self.details.set('%s；已知成員 %s 人，階段：%s；%s%s' % (
                status, count, data.get('phase', '待確認'),
                data.get('status', '等待伺服器同步'),
                '；' + instance_details(data, self.cooperative, local_role_id)
                if instance_details(data, self.cooperative, local_role_id) else ''))
        elif self.cooperative and data.get('reward'):
            current_reward = data['reward']
            self.details.set('協力獎勵旗標 %s，已完成 %s／%s 場；%s' % (
                current_reward['reward_mark'], current_reward['win_stage'],
                current_reward['reward_count'],
                instance_details(data, True, local_role_id) or '以伺服器回覆為準'))
        else:
            self.details.set(
                instance_details(data, self.cooperative, local_role_id)
                or '未加入房間；進入、準備、領獎功能仍待正式伺服器驗證。')
        # Only a deliberate user click on a live, confirmed started room can enter.
        self.enter_button.state(['!disabled'] if self._enter_ready else ['disabled'])


def instance_details(data, cooperative=False, local_role_id=None):
    """Show only actual server notifications, without invented rewards."""
    parts = []
    if cooperative:
        remaining = data.get('fight_count')
        if type(remaining) is int:
            parts.append('剩餘場次 %s' % remaining)
        if data.get('completed'):
            parts.append('協力場次已由伺服器確認完成')
        awards = data.get('received_awards') or ()
        if awards:
            parts.append('伺服器獎品收據：' + '、'.join(
                '種類%s 物品%s ×%s' % (a['kind'], a['id'], a['value']) for a in awards))
            parts.append('背包實際入帳仍需同步核對')
        if data.get('claim_result') == 'server_closed_unverified_awards':
            parts.append('寶箱已關閉但尚未確認實際獎品，請檢查背包／信箱')
        if data.get('mail_notice'):
            parts.append('伺服器通知獎品寄送信箱')
    else:
        obj = data.get('objectives') or {}
        targets = obj.get('targets') or {}
        if targets:
            parts.append('擊殺目標：' + '、'.join(
                '#%s NPC%s %s/%s' % (idx, row.get('npc_id', '?'),
                                     row.get('kills', 0), row.get('required', '?'))
                for idx, row in sorted(targets.items())))
        boss = obj.get('boss') or {}
        if boss:
            parts.append('Boss NPC%s：%s' % (
                boss.get('npc_id', '?'), '已擊敗' if boss.get('defeated') else '未擊敗'))
        score = (obj.get('scores') or {}).get(str(local_role_id))
        if score:
            parts.append('個人積分：小怪 %s／Boss %s' %
                         (score.get('normal', 0), score.get('boss', 0)))
        if obj.get('records'):
            parts.append('新式副本結算紀錄：%s 人（依 S85-21-100）' %
                         len(obj['records']))
        if data.get('completed'):
            parts.append('副本完成：伺服器已確認')
    return '；'.join(parts)


class InstancePanel(ttk.Frame):
    """Main instance tab with two independent, read-only server snapshots."""

    def __init__(self, parent, app=None):
        super().__init__(parent, padding=6)
        self.tabs = RoundedNotebook(self, borderless=True)
        self.tabs.pack(fill='both', expand=True)
        self.main_page = InstanceModePage(self.tabs, cooperative=False, app=app)
        self.coop_page = InstanceModePage(self.tabs, cooperative=True, app=app)
        self.tabs.add(self.main_page, text='主要')
        self.tabs.add(self.coop_page, text='協力')

    def render(self, state, *, live=False):
        instances = state.get('instances') or {}
        active_npc = (state.get('knowledge') or {}).get('active_npc_id')
        local_role = (state.get('player') or {}).get('role_id')
        player = state.get('player') or {}
        activity_blocked = (
            bool((state.get('battle') or {}).get('active'))
            or bool((state.get('event_flow') or {}).get('blocked'))
            or bool((state.get('battle') or {}).get('post_event')
                    and (state.get('battle') or {})['post_event'].get('status') != 'completed')
            or any((state.get(k) or {}).get('pending') for k in
                   ('maintenance', 'expedition', 'alchemy', 'crafting'))
            or bool((state.get('maintenance') or {}).get('uncertain'))
            or any((state.get(k) or {}).get('enabled')
                   for k in ('auto_battle', 'roaming', 'alchemy', 'expedition'))
            or bool((state.get('crafting') or {}).get('auto_continue'))
        )
        self.main_page.render(instances.get('main', {}), live=live,
                              other=instances.get('coop', {}),
                              local_role_id=local_role, active_npc_id=active_npc,
                              local_scene=player.get('scene'), activity_blocked=activity_blocked)
        self.coop_page.render(instances.get('coop', {}), live=live,
                              other=instances.get('main', {}),
                              local_role_id=local_role, active_npc_id=active_npc,
                              local_scene=player.get('scene'), activity_blocked=activity_blocked,
                              inventory=state.get('inventory') or {})
