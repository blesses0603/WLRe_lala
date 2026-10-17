"""In-memory, independent game sessions for the first Android test build.

No credentials or packets are written to disk or emitted as UI events.
Android background service and secure saved passwords are NOT implemented yet.
"""
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


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.events = queue.Queue()

    def start(self, *, label, host, port, account, password):
        if not account or not password:
            raise ValueError("請輸入帳號和密碼")
        if not host or not 0 < port < 65536:
            raise ValueError("伺服器位址或連接埠不正確")
        session_id = uuid.uuid4().hex
        session = Session(session_id, label, account, host, port)
        self.sessions[session_id] = session
        self.events.put((session_id, "status", "準備驗證帳號"))

        def emit(event):
            kind = event.get("type")
            if kind in ("connected", "verifying_account", "connection_closed"):
                labels = {"connected": "伺服器已連接，等待登入",
                          "verifying_account": "正在驗證帳號",
                          "connection_closed": "連線已結束"}
                self.events.put((session_id, "status", labels[kind]))
            elif kind == "verification_result":
                self.events.put((session_id, "status", "帳號驗證回應已收到"))
            elif kind == "login_result":
                self.events.put((session_id, "status",
                                 "登入成功" if event.get("result") == 0 else "登入失敗"))
            elif kind == "role_list_available":
                roles = [
                    {"index": r.get("index"), "name": str(r.get("name", "")),
                     "level": r.get("level", "?")}
                    for r in event.get("roles", []) if isinstance(r, dict)
                ]
                self.events.put((session_id, "roles", roles))

        def on_state(state):
            player = state.player or {}
            self.events.put((session_id, "snapshot", {
                "phase": state.phase,
                "character": str(player.get("name") or ""),
                "level": player.get("level", ""),
            }))

        def work():
            try:
                from wlre.network.client import run_client
                from wlre.storage.defaults import load_default_profile
                run_client(
                    session.host, session.port, load_default_profile(), emit,
                    account=account, password=password, verify_first=True,
                    duration=None, stop_event=session.stop_event,
                    commands=session.commands, on_state=on_state,
                    snapshot_interval=0.5,
                )
            except Exception as exc:
                # Never show an exception containing the account or password.
                message = str(exc).replace(account, "[帳號]").replace(password, "[密碼]")
                self.events.put((session_id, "status",
                                 "連線錯誤：" + type(exc).__name__ + ": " + message[:180]))
            finally:
                self.events.put((session_id, "finished", "連線已停止"))

        session.worker = threading.Thread(target=work, name="lala-" + session_id[:8], daemon=True)
        session.worker.start()
        return session

    def select_role(self, session_id, index):
        session = self.sessions.get(session_id)
        if session and session.worker and session.worker.is_alive() and index in (1, 2):
            session.commands.put({"type": "select_role", "index": index})

    def stop(self, session_id):
        session = self.sessions.get(session_id)
        if session:
            session.stop_event.set()
            self.events.put((session_id, "status", "正在停止連線"))

    def stop_all(self):
        for session_id in list(self.sessions):
            self.stop(session_id)
