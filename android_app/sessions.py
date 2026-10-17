"""Independent in-memory foreground sessions; no credential/packet persistence."""
from dataclasses import dataclass, field
import queue
import threading
import uuid


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
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


class SessionManager:
    def __init__(self):
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
            self.sessions[session_id] = session
            self.events.put((session_id, "status", "準備驗證帳號"))

            def emit(event):
                kind = event.get("type")
                with session.lock:
                    if session.stop_event.is_set():
                        return
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
                    elif kind == "command_rejected" and event.get("command_type") == "select_role":
                        session.selection_pending = False
                        self.events.put((session_id, "status", "角色選擇未成功，請重新選擇"))
                        self.events.put((session_id, "roles", session.roles))

            def on_state(state):
                from wlre.services.world.display_position import current_position
                with session.lock:
                    if session.stop_event.is_set():
                        return
                    player = state.get("player") or {}
                    stats = (state.get("knowledge") or {}).get("player", {}).get("stats", {})
                    session.phase = state.get("phase", "未知")
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
