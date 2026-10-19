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
        ttk.Label(self, text="1262 官方副本清單（靜態資料，非房間即時狀態）",
                  style='Muted.TLabel').pack(anchor='w', pady=(0, 3))
        self.catalog_columns = ('id', 'name', 'level', 'players', 'time')
        catalog_host = ttk.Frame(self)
        catalog_host.pack(fill='x', pady=(0, 4))
        self.catalog_table = ttk.Treeview(
            catalog_host, columns=self.catalog_columns,
            show='headings', selectmode='browse', height=7)
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
            self, columns=self.columns, show='headings', selectmode='browse', height=5
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
        controls.pack(fill='x')
        self.refresh_button = ttk.Button(
            controls, text='更新房間清單', command=self.refresh_rooms, state='disabled')
        self.refresh_button.pack(side='left')
        self.create_button = ttk.Button(
            controls, text='建立公開／私人房間', command=self.open_create_dialog,
            state='disabled')
        self.create_button.pack(side='left', padx=(10, 0))
        self._creation_ready = False
        self._standby_ready = False
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
                      style='Muted.TLabel').pack(anchor='w')
        self.enter_button = ttk.Button(controls, text='進入副本', state='disabled')
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

    def refresh_rooms(self):
        if self.app is not None and self.app.live_active:
            self.app.send({'type': 'instance_refresh', 'mode': self.mode})

    def render(self, data, *, live=False, other=None,
               local_role_id=None, active_npc_id=None):
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
                           ('create_pending','join_pending','leave_pending','standby_pending'))
                    or any(part.get(k) for k in
                           ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain')))
        active = bool(live) and not blocked(data) and not blocked(other)
        updated = data.get('list_updated_at')
        fresh = (updated is not None and
                 0 <= time.monotonic() - updated <= 120)
        self._join_ready = active and data.get('ready') and fresh
        self._leave_ready = (
            bool(live) and data.get('room') is not None
            and not any(data.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending'))
            and not any(data.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain'))
            and not any(other.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending'))
            and not any(other.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain'))
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
                        ('create_pending','join_pending','leave_pending','standby_pending'))
            and not any(data.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain'))
            and not any(other.get(k) is not None for k in
                        ('create_pending','join_pending','leave_pending','standby_pending'))
            and not any(other.get(k) for k in
                        ('create_uncertain','join_uncertain','leave_uncertain','standby_uncertain')))
        self._creation_ready = (
            bool(live) and not data.get('create_pending')
            and not data.get('create_uncertain') and not data.get('room')
            and not other.get('create_pending')
            and not other.get('create_uncertain') and not other.get('room')
            and not any(data.get(k) for k in ('join_pending','leave_pending','join_uncertain','leave_uncertain','standby_pending','standby_uncertain'))
            and not any(other.get(k) for k in ('join_pending','leave_pending','join_uncertain','leave_uncertain','standby_pending','standby_uncertain')))
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
            self.details.set('%s；已知成員 %s 人，階段：%s' % (
                status, count, data.get('phase', '待確認')))
        elif self.cooperative and data.get('reward'):
            reward = data['reward']
            self.details.set('協力獎勵旗標 %s，已完成階段 %s；領獎功能未開放' % (
                reward['reward_mark'], reward['win_stage']))
        else:
            self.details.set('未加入房間；進入、準備、領獎功能仍待正式伺服器驗證。')
        # Under no circumstances does a snapshot alone enable mutation.
        self.enter_button.state(['disabled'])


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
        self.main_page.render(instances.get('main', {}), live=live,
                              other=instances.get('coop', {}),
                              local_role_id=local_role, active_npc_id=active_npc)
        self.coop_page.render(instances.get('coop', {}), live=live,
                              other=instances.get('main', {}),
                              local_role_id=local_role, active_npc_id=active_npc)
