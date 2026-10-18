"""Independent in-memory foreground sessions; no credential/packet persistence."""
from dataclasses import dataclass, field
import queue
import threading
import uuid
import copy
import time
from collections import deque
from android_app import features, preferences
from wlre.services.social.chat_names import NameBook
from wlre.services.battle.auto_battle import defaults, validate
from wlre.storage import account_settings


@dataclass
class Session:
    session_id: str
    label: str
    account: str
    host: str
    port: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    commands: queue.Queue = field(default_factory=queue.Queue)
    worker: threading.Thread | None = None
    active: bool = True
    phase: str = "connecting"
    roles: list = field(default_factory=list)
    selection_pending: bool = False
    ai_settings: dict = field(default_factory=defaults)
    automation: dict = field(default_factory=dict)
    automation_pending: set = field(default_factory=set)
    game_state: dict = field(default_factory=dict)
    chat_history: deque = field(default_factory=lambda: deque(maxlen=200))
    log_history: deque = field(default_factory=lambda: deque(maxlen=200))
    names: NameBook = field(default_factory=NameBook)
    preferences: dict = field(default_factory=preferences.defaults)
    detail_revision: int = 0
    chat_sequence: int = 0
    chat_requests: deque = field(default_factory=deque)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class SessionManager:
    def __init__(self, settings_base=None):
        self.settings_base = settings_base
        self.sessions: dict[str, Session] = {}
        self.events = queue.Queue()
        self.lock = threading.RLock()

    def start(self, *, label, host, port, account, password):
        if not isinstance(account, str) or not account.strip() or not isinstance(password, str) or not password:
            raise ValueError("請輸入帳號和密碼")
        account = account.strip()
        if not isinstance(host, str) or not host or type(port) is not int or not 0 < port < 65536:
            raise ValueError("伺服器位址或連接埠不正確")
        with self.lock:
            if any(s.active and (s.host, s.port, s.account) == (host, port, account)
                   for s in self.sessions.values()):
                raise ValueError("這個帳號在此分流的連線尚未結束")
            session_id = uuid.uuid4().hex
            session = Session(session_id, label, account, host, port)
            if self.settings_base is not None:
                key = account_settings.identity(host, port, account)
                if account_settings.settings_file(key, self.settings_base).exists():
                    session.ai_settings = account_settings.load(key, self.settings_base)
                session.preferences = preferences.load(self.settings_base, key)
            self.sessions[session_id] = session
            self.events.put((session_id, "status", "準備驗證帳號"))

            def emit(event):
                kind = event.get("type")
                with session.lock:
                    if session.stop_event.is_set():
                        return
                    if kind == 'chat_message':
                        session.names.update(session.game_state, event)
                        session.chat_history.append({k: copy.deepcopy(event[k]) for k in (
                            'channel', 'role_id', 'text', 'server_id', 'reply_id', 'reply_text',
                            'reply_items', 'reply_at', 'items', 'target_id') if k in event})
                        session.detail_revision += 1
                    elif kind in ('chat_sent', 'chat_result', 'chat_notice'):
                        text = '已送出，等待伺服器轉送；不代表對方已讀' if kind == 'chat_sent' else str(event.get('text', '發話回覆已收到'))
                        self.events.put((session_id, 'notice', text[:500]))
                        if kind == 'chat_sent':
                            session.chat_sequence += 1
                            self.events.put((session_id, 'chat_ack', dict(sequence=session.chat_sequence, request_id=session.chat_requests.popleft() if session.chat_requests else None, status='sent', text=event.get('text',''))))
                    elif kind == 'chat_profile':
                        session.names.update(session.game_state, event)
                    if kind == 'command_rejected':
                        if event.get('command_type') == 'chat':
                            session.chat_sequence += 1
                            self.events.put((session_id, 'chat_ack', dict(sequence=session.chat_sequence,request_id=session.chat_requests.popleft() if session.chat_requests else None,status='rejected')))
                        from wlre.core.event_log import chinese
                        text = '操作未送出：' + chinese(event.get('error', '操作條件不符'))[:500]
                        # Errors originate from supported game commands, never login exceptions.
                        if event.get('command_type') in features.GAME_COMMANDS:
                            self.events.put((session_id, 'notice', text))
                    if kind not in ('command_rejected', 'sent', 'connected', 'verifying_account'):
                        from wlre.core.event_log import lines
                        try:
                            for text in lines(event, session.game_state):
                                session.log_history.append(time.strftime('%H:%M:%S')+' '+str(text)[:1000])
                                session.detail_revision += 1
                        except (KeyError, TypeError, ValueError): pass
                    if kind in ("connected", "verifying_account", "connection_closed"):
                        labels = {"connected": "伺服器已連接，等待登入",
                                  "verifying_account": "正在驗證帳號", "connection_closed": "連線已結束"}
                        self.events.put((session_id, "status", labels[kind]))
                    elif kind == "verification_result":
                        self.events.put((session_id, "status", "帳號驗證回應已收到"))
                    elif kind == "login_result":
                        self.events.put((session_id, "status", "登入成功" if event.get("result") == 0 else "登入失敗"))
                    elif kind == "role_list_available":
                        session.roles = [{"index": r.get("index"), "name": str(r.get("name", "")),
                                          "level": r.get("level"), "locked": bool(r.get("locked"))}
                                         for r in event.get("roles", []) if isinstance(r, dict)]
                        session.phase = "role_selection"
                        self.events.put((session_id, "roles", session.roles))
                    elif kind in ('auto_battle_status', 'roaming_status'):
                        feature = 'battle' if kind == 'auto_battle_status' else 'roaming'
                        session.automation[feature] = {k: copy.deepcopy(v) for k, v in event.items() if k != 'type'}
                        session.automation_pending.discard(feature)
                        self.events.put((session_id, 'automation', copy.deepcopy(session.automation)))
                    elif kind == 'command_rejected' and event.get('command_type') in (
                            'start_auto_battle', 'stop_auto_battle', 'start_roaming', 'stop_roaming'):
                        feature = 'battle' if 'auto_battle' in event['command_type'] else 'roaming'
                        session.automation_pending.discard(feature)
                        self.events.put((session_id, 'notice', '操作未成功：請確認角色已入場、補給結果及隊長狀態後重試'))
                    elif kind == "command_rejected" and event.get("command_type") == "select_role":
                        session.selection_pending = False
                        self.events.put((session_id, "status", "角色選擇未成功，請重新選擇"))
                        self.events.put((session_id, "roles", session.roles))

            def on_state(state):
                from wlre.services.world.display_position import current_position
                with session.lock:
                    if session.stop_event.is_set():
                        return
                    session.game_state = features.project(state)
                    session.names.update(session.game_state)
                    session.detail_revision += 1
                    player = state.get("player") or {}
                    stats = dict((state.get("knowledge") or {}).get("player", {}).get("stats", {}))
                    if state.get('battle', {}).get('active'):
                        unit = next((u for u in state.get('battle_units', {}).values()
                            if player.get('role_id') is not None and u.get('pid') == player['role_id'] and not u.get('master_id')), {})
                        stats.update({k: unit[k] for k in ('hp','max_hp','sp','max_sp','level') if k in unit})
                    session.phase = state.get("phase", "未知")
                    session.automation = {'battle': copy.deepcopy(state.get('auto_battle') or {}),
                                          'roaming': copy.deepcopy(state.get('roaming') or {})}
                    self.events.put((session_id, 'automation', copy.deepcopy(session.automation)))
                    self.events.put((session_id, "snapshot", {
                        "phase": session.phase, "character": str(player.get("name") or ""),
                        "level": stats.get("level", player.get("level")), "scene": player.get("scene"),
                        "position": current_position(state),
                        **{k: stats.get(k) for k in ("hp", "max_hp", "sp", "max_sp")},
                    }))

            def work():
                finished = "連線已結束"
                try:
                    from wlre.network.client import run_client
                    from wlre.storage.defaults import load_default_profile
                    run_client(session.host, session.port, load_default_profile(), emit,
                               account=account, password=password, verify_first=True, duration=None,
                               stop_event=session.stop_event, commands=session.commands,
                               on_state=on_state, snapshot_interval=0.5, tcp_keepalive=True)
                except Exception as exc:
                    # Exception text may contain escaped/encoded credentials, so
                    # replacing literal strings is insufficient. Expose type only.
                    if type(exc).__name__ == "LoginRejected":
                        finished = "帳號驗證未通過，請確認帳號與密碼"
                    elif isinstance(exc, OSError):
                        finished = "網路連線失敗或逾時，請稍後重試"
                    elif isinstance(exc, UnicodeError):
                        finished = "登入資料包含無法處理的字元，請確認後重試"
                    else:
                        finished = "連線流程發生錯誤，請重新登入"
                finally:
                    with session.lock:
                        session.active = False
                        session.phase = "disconnected"
                        if session.stop_event.is_set(): finished = "連線已停止"
                        self.events.put((session_id, "finished", finished))

            session.worker = threading.Thread(target=work, name="lala-" + session_id[:8], daemon=True)
            session.worker.start()
            return session

    def select_role(self, session_id, index):
        with self.lock: session = self.sessions.get(session_id)
        if session is None: return False
        with session.lock:
            role = next((r for r in session.roles if r["index"] == index), None)
            if (not session.active or session.stop_event.is_set() or session.phase != "role_selection"
                    or session.selection_pending or role is None or role["locked"]):
                return False
            session.selection_pending = True
            session.commands.put({"type": "select_role", "index": index})
            return True

    def automation_command(self, session_id, feature, enabled):
        if feature not in ('battle', 'roaming') or type(enabled) is not bool: return False
        with self.lock: session = self.sessions.get(session_id)
        if session is None: return False
        with session.lock:
            if (not session.active or session.stop_event.is_set() or session.phase != 'world_ready'
                    or feature in session.automation_pending): return False
            command = {'type': ('start_' if enabled else 'stop_') +
                       ('auto_battle' if feature == 'battle' else 'roaming')}
            if enabled and feature == 'battle': command['settings'] = copy.deepcopy(session.ai_settings)
            session.automation_pending.add(feature)
            session.commands.put(command)
            return True

    def save_ai_settings(self, session_id, settings):
        checked = validate(settings)
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None: return False
            key = account_settings.identity(session.host, session.port, session.account)
            if self.settings_base is not None: account_settings.save(key, checked, self.settings_base)
            for other in self.sessions.values():
                if account_settings.identity(other.host, other.port, other.account) == key:
                    with other.lock: other.ai_settings = copy.deepcopy(checked)
            self.events.put((session_id, 'notice', 'AI 設定已保存，下次啟動自動戰鬥時套用'))
            return True

    def game_command(self, session_id, command):
        checked = features.checked_command(command)
        with self.lock: session = self.sessions.get(session_id)
        if session is None: return False
        with session.lock:
            if not session.active or session.stop_event.is_set() or session.phase != 'world_ready': return False
            if session.commands.qsize() >= 32: raise ValueError('操作佇列已滿，請等待回覆')
            if checked['type'] == 'chat' and checked.get('channel') == '密語':
                checked['target'] = session.names.resolve(checked.get('target'), session.game_state.get('player', {}).get('role_id'))
            if checked['type'] == 'chat': session.chat_requests.append(checked.get('request_id'))
            session.commands.put(checked)
            return True

    def session_detail(self, session_id):
        with self.lock: session = self.sessions.get(session_id)
        if session is None: raise ValueError('帳號連線不存在')
        with session.lock: return features.detail(session)

    def save_preferences(self, session_id, value):
        checked = preferences.validate(value)
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None: return False
            key = account_settings.identity(session.host, session.port, session.account)
            if self.settings_base is not None: preferences.save(self.settings_base, key, checked)
            for other in self.sessions.values():
                if account_settings.identity(other.host, other.port, other.account) == key:
                    with other.lock:
                        other.preferences = copy.deepcopy(checked)
                        other.detail_revision += 1
            return True

    def stop(self, session_id):
        with self.lock: session = self.sessions.get(session_id)
        if session:
            with session.lock:
                if not session.active: return False
                session.stop_event.set()
                self.events.put((session_id, "status", "正在停止連線"))
                return True
        return False

    def remove(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            if not session or session.active or (session.worker and session.worker.is_alive()): return False
            del self.sessions[session_id]
            return True

    def stop_all(self):
        with self.lock: ids = list(self.sessions)
        for session_id in ids: self.stop(session_id)
