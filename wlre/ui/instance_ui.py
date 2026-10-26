"""Main/cooperative instance browser using only verified server snapshots."""
import time
import tkinter as tk
from tkinter import ttk, messagebox

from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.ui.instance_menu_icons import menu_icon_photo
from wlre.ui.instance_room_dialogs import InstanceRoomDialogMixin
from wlre.services.instance_browser import entries_for
from wlre.services.battle.party import own_team
from wlre.services.instance_room_flow import coop_completed_no_chest
from wlre.services.instance_activity import instance_background_blockers
from wlre.features.cooperative.buttons import CooperativeActionsMixin
from wlre.features.cooperative.rooms import cooperative_headcount_status, CooperativeRoomStatusMixin
from wlre.features.cooperative.rewards import CooperativeRewardViewMixin
from wlre.features.cooperative.widgets import build_cooperative_widgets
from wlre.ui.instance_room_list import InstanceRoomListMixin
from wlre.ui.instance_catalog_ui import InstanceCatalogMixin, build_instance_catalog
from wlre.features.dungeon.buttons import DungeonActionsMixin, build_dungeon_start_button
from wlre.features.dungeon.rooms import dungeon_headcount_status
from wlre.features.dungeon.readiness import DungeonRoomReadinessMixin
from wlre.features.dungeon.details import dungeon_details


def creation_block_reasons(state, mode, live):
    """Only describe existing safety locks; never relax room-create guards."""
    if not live:
        return ('未連線，請先登入',)
    reasons = []
    player = state.get('player') or {}
    if (state.get('phase') != 'world_ready' or
            state.get('initial_data_complete') is not True or
            not player.get('role_id')):
        reasons.append('角色或世界資料尚未完成同步')
    instances = state.get('instances') or {}
    operations = {
        'create': '創房', 'join': '加入房間', 'leave': '離開房間',
        'standby': '協力準備', 'start': '開始挑戰',
        'enter': '入場', 'claim': '領獎', 'cancel': '取消寶箱'
    }
    for name, label in (('main', '主要'), ('coop', '協力')):
        info = instances.get(name) or {}
        if info.get('room') is not None:
            reasons.append('仍在%s副本房間，請先離開' % label)
            if (name == 'coop' and info.get('phase') == 'matched'
                    and info.get('reward') is None):
                reasons.append('協力戰後尚未同步 S186-11 獎勵狀態')
        for op, text in operations.items():
            if info.get(op + '_pending') is not None:
                reasons.append('%s%s仍待伺服器確認' % (label, text))
            if (info.get(op + '_uncertain') or
                    op in ('claim', 'cancel') and info.get('reward_uncertain')):
                reasons.append('%s%s結果不明，請重新登入同步' % (label, text))
    battle = state.get('battle') or {}
    if battle.get('active'):
        reasons.append('正在戰鬥中')
    if (state.get('event_flow') or {}).get('blocked'):
        reasons.append('伺服器事件尚未結束')
    post = battle.get('post_event') or {}
    if post and post.get('status') != 'completed':
        reasons.append('戰後事件尚未完成')
    reasons.extend(instance_background_blockers(state))
    if mode == 'coop':
        if own_team(state):
            reasons.append('協力創房前請先退出一般隊伍')
        if ((instances.get('coop') or {}).get('reward') or {}).get('open_reward'):
            reasons.append('協力寶箱尚未處理')
    return tuple(dict.fromkeys(reasons))


def room_headcount_status(mode, data, local_role_id=None, *, can_begin=False):
    """Summarize a server-confirmed room's numbers, never infer readiness.

    Normal dungeons use the official StageData minimum, not room capacity.
    Co-op requires every S186-3 slot occupied. This is UI-only; the command
    service remains the final source of start/standby authorization.
    """
    title = '協力副本' if mode == 'coop' else '一般副本'
    room = data.get('room')
    if not isinstance(room, dict) or not room:
        return title + '：尚未加入房間，等待伺服器房間及成員資訊'

    members = data.get('members')
    count = len(members) if isinstance(members, (list, tuple)) else 0
    if mode == 'coop':
        return cooperative_headcount_status(room, members, count,
                                            can_begin=can_begin)

    return dungeon_headcount_status(room, members, count, local_role_id,
                                    can_begin=can_begin)


class InstanceModePage(CooperativeActionsMixin, CooperativeRewardViewMixin,
                       CooperativeRoomStatusMixin, DungeonActionsMixin,
                       DungeonRoomReadinessMixin, InstanceRoomListMixin,
                       InstanceCatalogMixin, InstanceRoomDialogMixin, ttk.Frame):
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
        # Static 3:2 grid: both lists stay visible but users cannot drag
        # a separator or change their sizes independently.
        self.body=ttk.Frame(self)
        self.body.pack(fill='both',expand=True,pady=(4,0))
        self.body.columnconfigure(0,weight=3,uniform='instance-columns')
        self.body.columnconfigure(1,weight=2,uniform='instance-columns')
        self.body.rowconfigure(0,weight=1)
        self.catalog_column=ttk.Frame(self.body,padding=(0,0,6,0))
        self.room_column=ttk.Frame(self.body,padding=(6,0,0,0))
        self.catalog_column.grid(row=0,column=0,sticky='nsew')
        self.room_column.grid(row=0,column=1,sticky='nsew')
        build_instance_catalog(self, cooperative)
        ttk.Label(self.room_column, text='伺服器房間清單（選取後加入）',
                  style='Muted.TLabel').pack(anchor='w',pady=(0,2))
        self.room_list_note=tk.StringVar(value='尚未同步伺服器房間清單')
        ttk.Label(self.room_column,textvariable=self.room_list_note,
                  style='Muted.TLabel',wraplength=380).pack(
                      anchor='w',fill='x',pady=(0,3))
        self.columns = ('name', 'requirement', 'status')
        room_host=ttk.Frame(self.room_column)
        room_host.pack(fill='both',expand=True)
        self.entries = ttk.Treeview(
            room_host, columns=self.columns, show='headings',
            selectmode='browse', height=5)
        for key, heading, width in (
            ('name', '房間／副本', 165),
            ('requirement', '人數／條件', 110),
            ('status', '公開狀態', 90),
        ):
            self.entries.heading(key, text=heading)
            self.entries.column(key, width=width, stretch=True, anchor='w')
        room_scroll=ttk.Scrollbar(room_host,orient='vertical',
                                   command=self.entries.yview)
        self.entries.configure(yscrollcommand=room_scroll.set)
        room_scroll.pack(side='right',fill='y')
        self.entries.pack(side='left',fill='both',expand=True)
        self.entries.bind('<<TreeviewSelect>>', self.on_room_selected)
        self._room_rows = []
        self._join_ready = False
        self._leave_ready = False
        self._room_data = {}
        self._room_other = {}
        self.details = tk.StringVar(value='沒有已確認的副本房間；進入與領獎功能尚未開放。')
        ttk.Label(self.room_column, textvariable=self.details,
                  style='Muted.TLabel',wraplength=380,
                  anchor='w').pack(fill='x', pady=(8, 2))
        controls = ttk.Frame(self)
        # Buttons stay visible above the two non-adjustable columns.
        controls.pack(fill='x', before=self.body, pady=(0, 5))
        self.refresh_button = ttk.Button(
            controls, text='更新房間清單', command=self.refresh_rooms, state='disabled')
        self.refresh_button.pack(side='left')
        self.create_button = ttk.Button(
            controls, text='建立公開／私人房間', command=self.open_create_dialog,
            state='disabled')
        self.create_button.pack(side='left', padx=(10, 0))
        self.creation_hint = tk.StringVar(value='建立房間：請先選擇官方副本')
        self._creation_block_reasons = ()
        self.creation_hint_label = ttk.Label(
            self, textvariable=self.creation_hint, style='Muted.TLabel', anchor='w')
        self.creation_hint_label.pack(fill='x', after=controls, pady=(0, 3))
        self.headcount_note = tk.StringVar(value='房間人數：等待伺服器同步')
        self.headcount_label = ttk.Label(
            self, textvariable=self.headcount_note,
            style='Muted.TLabel', anchor='w')
        self.headcount_label.pack(
            fill='x', after=self.creation_hint_label, pady=(0, 4))
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
            build_cooperative_widgets(self, controls)
        if not self.cooperative:
            build_dungeon_start_button(self, controls)
        self.enter_button = ttk.Button(controls, text='進入副本',
                                       command=self.request_enter, state='disabled')
        self.enter_button.pack(side='right')

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

    def refresh_rooms(self):
        if self.app is not None and self.app.live_active:
            self.app.send({'type': 'instance_refresh', 'mode': self.mode})

    def render(self, data, *, live=False, other=None,
               local_role_id=None, active_npc_id=None, local_scene=None,
               activity_blocked=False, inventory=None,
               creation_reasons=()):
        other = other or {}
        self._room_data = dict(data)
        self._room_other = dict(other)
        self._creation_block_reasons = tuple(creation_reasons)
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
            and (self.cooperative and
                 (not data.get('standby') or coop_completed_no_chest(data))
                 or not self.cooperative and data.get('phase') == 'waiting'))
        member_data = data.get('members') or []
        current_room = data.get('room') or {}
        room_capacity = current_room.get('capacity')
        full = (isinstance(room_capacity, int) and room_capacity > 0
                and len(member_data) == room_capacity)
        host_id = (current_room['host_id'] if 'host_id' in current_room
                   else member_data[0].get('role_id') if member_data else None)
        self._standby_ready = (
            self.cooperative and bool(live) and full
            and host_id == local_role_id
            and member_data[0].get('role_id') == host_id
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
        self.render_cooperative_rewards(data, other, live, activity_blocked, inventory)
        self.render_dungeon_readiness(
            data, other, live, member_data, current_room,
            local_role_id, local_scene, activity_blocked)
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
        self.headcount_note.set(room_headcount_status(
            self.mode, data, local_role_id,
            can_begin=self._standby_ready if self.cooperative else self._start_ready))
        self.render_cooperative_standby(
            live, data, current_room, member_data, host_id, local_role_id,
            room_capacity, reward_locked, activity_blocked)
        self.refresh_button.state(['!disabled'] if live else ['disabled'])
        self.note.set(data.get('status', '尚未查詢房間') if live else '尚未連線，無法查詢副本房間')
        self.render_room_list(data, live, local_role_id, instance_details)
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
        return dungeon_details(data, local_role_id)
    return '；'.join(parts)


class InstancePanel(ttk.Frame):
    """Main instance tab with two independent, read-only server snapshots."""

    def __init__(self, parent, app=None):
        super().__init__(parent, padding=6)
        self.tabs = RoundedNotebook(self, borderless=True,
                                    image_loader=menu_icon_photo)
        self.tabs.pack(fill='both', expand=True)
        from wlre.features.dungeon.panel import DungeonModePage
        self.main_page = DungeonModePage(self.tabs, app=app)
        from wlre.features.cooperative.panel import CooperativeModePage
        self.coop_page = CooperativeModePage(self.tabs, app=app)
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
            or bool(instance_background_blockers(state))
        )
        self.main_page.render(instances.get('main', {}), live=live,
                              other=instances.get('coop', {}),
                              local_role_id=local_role, active_npc_id=active_npc,
                              local_scene=player.get('scene'), activity_blocked=activity_blocked,
                              creation_reasons=creation_block_reasons(state, 'main', live))
        self.coop_page.render(instances.get('coop', {}), live=live,
                              other=instances.get('main', {}),
                              local_role_id=local_role, active_npc_id=active_npc,
                              local_scene=player.get('scene'), activity_blocked=activity_blocked,
                              inventory=state.get('inventory') or {},
                              creation_reasons=creation_block_reasons(state, 'coop', live))
