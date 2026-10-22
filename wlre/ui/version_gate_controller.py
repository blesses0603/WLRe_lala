"""Desktop pre-login version verification window.

Every network/file scan runs on a background thread; Tk operations remain on
the application thread. A confirmed 1262 resource mismatch always blocks login.
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from wlre.services.game_version_gate import (
    find_yoo_root, run_prelogin_check, scan_local_manifests,
)
from wlre.storage.paths import data_root
from wlre.ui.window_layout import configure_dialog


class VersionGateController:
    def initialize_version_gate(self):
        self.version_gate_state = "checking"
        self.version_gate_text = tk.StringVar(value="正在準備 1262 官方資源版本檢測…")
        self._version_gate_result = None
        self._version_gate_checked = 0.0
        self._version_gate_generation = 0
        self._version_gate_messages = queue.SimpleQueue()
        self.version_gate_root = self._load_game_root()
        self.version_window = None
        self._version_heading = tk.StringVar(value="正在檢查版本…")
        self._version_main = tk.StringVar(value="等待檢測")
        self._version_data = tk.StringVar(value="等待檢測")
        self._version_remote = tk.StringVar(value="尚未驗證")
        self._version_path = tk.StringVar(value="尚未找到遊戲資源目錄")

    @staticmethod
    def _load_game_root():
        path = data_root() / "official_game_yoo_root.txt"
        try:
            if not path.is_file() or path.stat().st_size > 4096:
                return None
            return path.read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeError):
            return None

    def show_version_check(self):
        """Show a dedicated startup window, before displaying account fields."""
        if self._closing:
            return
        if self.login_window is not None and self.login_window.winfo_exists():
            self.login_window.withdraw()
        window = self.version_window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            window.focus_set()
            self._render_version_window()
            return
        window = tk.Toplevel(self.root)
        self.version_window = window
        window.title("飄流Re:LaLa · 登入前版本檢測")
        configure_dialog(window, 730, 490)
        window.resizable(False, False)
        # Closing the only visible startup window must not leave an invisible app.
        window.protocol("WM_DELETE_WINDOW", self.close)

        body = ttk.Frame(window, padding=(26, 24))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="官方遊戲資源版本檢測",
                  font=("TkDefaultFont", 17, "bold")).pack(anchor="w")
        ttk.Label(body, text="登入前確認 MainPackage／DataPackage · LaLa 支援基準 1262",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 17))
        ttk.Label(body, textvariable=self._version_heading,
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(0, 7))
        ttk.Label(body, textvariable=self.version_gate_text,
                  justify="left", wraplength=660).pack(anchor="w", fill="x", pady=(0, 14))

        details = ttk.LabelFrame(body, text="版本資訊", padding=(13, 10))
        details.pack(fill="x")
        for label, var in (("MainPackage", self._version_main),
                           ("DataPackage", self._version_data),
                           ("官方線上版本", self._version_remote),
                           ("遊戲資源路徑", self._version_path)):
            row = ttk.Frame(details)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=16).pack(side="left")
            ttk.Label(row, textvariable=var, anchor="w", justify="left",
                      wraplength=510).pack(side="left", fill="x", expand=True)

        self._version_progress = ttk.Progressbar(body, mode="indeterminate")
        self._version_progress.pack(fill="x", pady=(18, 8))
        ttk.Label(body,
                  text="僅讀取資源版本資訊，不會使用帳號、密碼或登入遊戲。",
                  style="Muted.TLabel").pack(anchor="w")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(13, 0))
        ttk.Button(actions, text="結束程式", command=self.close).pack(side="left")
        ttk.Button(actions, text="選擇遊戲目錄",
                   command=self.choose_version_folder).pack(side="left", padx=(10, 0))
        self._version_retry_button = ttk.Button(
            actions, text="重新檢查", command=self.start_version_check)
        self._version_retry_button.pack(side="left", padx=(10, 0))
        self._version_continue_button = ttk.Button(
            actions, text="進入登入畫面", command=self.continue_to_login)
        self._version_continue_button.pack(side="right")
        self._render_version_window()
        window.lift()
        window.focus_set()

    def hide_version_check(self):
        window = self.version_window
        if window is not None and window.winfo_exists():
            window.withdraw()

    def _render_version_window(self):
        window = self.version_window
        if window is None or not window.winfo_exists():
            return
        result = self._version_gate_result or {}
        local = result.get("local", {})
        remote = result.get("remote", {})
        self._version_path.set(local.get("root") or "未找到，請按「選擇遊戲目錄」")
        for package, variable in (("MainPackage", self._version_main),
                                  ("DataPackage", self._version_data)):
            record = local.get("packages", {}).get(package, {})
            version = record.get("version")
            if version:
                variable.set(f"{version}（基準 1262）" +
                             (" · 偵測到異動" if version != "1262" else " · 本機一致"))
            else:
                variable.set("無可確認的完整 Manifest")
        remote_status = remote.get("status", "unverified")
        self._version_remote.set({
            "same_resources": "兩個版本識別值為 1262（協定未驗證）",
            "resources_changed": "官方資源版本異動",
        }.get(remote_status, "未確認正式線上查詢網址／無法驗證"))

        if self.version_gate_state == "checking":
            self._version_heading.set("正在檢測遊戲版本…")
            self._version_progress.start(12)
            self._version_continue_button.configure(state="disabled")
        else:
            self._version_progress.stop()
            if self.version_gate_state == "blocked":
                self._version_heading.set("遊戲版本異動 · 請等待 LaLa 更新")
                self._version_continue_button.configure(state="disabled")
            elif result.get("status") == "version_identifiers_match":
                self._version_heading.set("資源版本識別值一致")
                self._version_continue_button.configure(text="進入登入畫面", state="normal")
            else:
                self._version_heading.set("無法完整驗證官方線上版本")
                self._version_continue_button.configure(
                    text="了解風險，繼續登入", state="normal")

    def continue_to_login(self):
        """No login form until this check finishes and no change is confirmed."""
        if not self.can_login_after_version_check():
            return
        self.hide_version_check()
        self.show_login()

    def choose_version_folder(self):
        folder = filedialog.askdirectory(
            parent=self.dialog_parent(), title="選擇官方遊戲安裝目錄或 YooAsset 資料夾")
        if not folder:
            return
        root = find_yoo_root(folder, strict=True)
        if root is None:
            messagebox.showwarning(
                "遊戲目錄不正確",
                "找不到 MainPackage 與 DataPackage 的 ManifestFiles，請選擇官方遊戲的 *_Data/yoo 資料夾。",
                parent=self.dialog_parent())
            return
        self.version_gate_root = str(root)
        try:
            path = data_root() / "official_game_yoo_root.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(root), encoding="utf-8")
        except OSError:
            pass
        self.start_version_check()

    def _set_login_gate_button(self):
        if hasattr(self, "connect_button") and self.connect_button.winfo_exists():
            disabled = (self.live_active or self.version_gate_state in ("checking", "blocked"))
            self.connect_button.configure(state="disabled" if disabled else "normal")

    def start_version_check(self):
        if self._closing:
            return
        # Any explicit recheck returns to the dedicated pre-login screen.
        if (self.login_window is not None and self.login_window.winfo_exists()
                and self.login_window.state() != "withdrawn" and not self.live_active):
            self.show_version_check()
        self._version_gate_generation += 1
        generation = self._version_gate_generation
        selected = self.version_gate_root
        self.version_gate_state = "checking"
        self._version_gate_result = None
        self.version_gate_text.set("正在檢查遊戲資源版本（1262 基準）…")
        self._set_login_gate_button()
        self._render_version_window()

        def worker():
            try:
                result = run_prelogin_check(selected)
            except Exception:
                result = {"blocked": False, "status": "unverified",
                          "message": "版本檢查執行失敗，無法驗證線上版本；未確認是否有更新。"}
            self._version_gate_messages.put((generation, result))

        threading.Thread(target=worker, name="official-version-check", daemon=True).start()

    def drain_version_checks(self):
        while True:
            try:
                generation, result = self._version_gate_messages.get_nowait()
            except queue.Empty:
                return
            if generation != self._version_gate_generation or self._closing:
                continue
            self._version_gate_result = result
            self._version_gate_checked = time.monotonic()
            self.version_gate_state = "blocked" if result["blocked"] else "ready"
            self.version_gate_text.set(result["message"])
            self._set_login_gate_button()
            self._render_version_window()
            if result["blocked"] and not self.live_active:
                self.show_version_check()

    def _block_for_local_change(self, local):
        message = "偵測到官方遊戲本機 Manifest 資源版本與 LaLa 1262 不同，禁止登入。請等待 LaLa 更新與相容性驗證。"
        self._version_gate_result = {"blocked": True, "status": "blocked",
                                     "message": message, "local": local}
        self.version_gate_state = "blocked"
        self.version_gate_text.set(message)
        self._set_login_gate_button()
        self.show_version_check()

    def can_login_after_version_check(self):
        """Authoritative guard for App.connect, independent of disabled widgets."""
        if self.version_gate_state == "checking":
            messagebox.showinfo("版本檢查中", "請先完成遊戲資源版本檢查。", parent=self.dialog_parent())
            return False
        if self.version_gate_state == "blocked":
            self.show_version_check()
            messagebox.showwarning("遊戲版本已變更", self.version_gate_text.get(), parent=self.dialog_parent())
            return False
        try:
            local = scan_local_manifests(self.version_gate_root)
        except (OSError, ValueError):
            local = {"status": "unverified"}
        if local["status"] == "changed":
            self._block_for_local_change(local)
            messagebox.showwarning("遊戲版本已變更", self.version_gate_text.get(), parent=self.dialog_parent())
            return False
        import os
        sources_configured = (os.getenv("WLRE_OFFICIAL_MAIN_VERSION_URL") and
                              os.getenv("WLRE_OFFICIAL_DATA_VERSION_URL"))
        if sources_configured and (not self._version_gate_checked or
                                   time.monotonic() - self._version_gate_checked > 300):
            self.start_version_check()
            messagebox.showinfo("重新驗證版本",
                                "檢測資料已逾期，正在重新讀取官方版本；完成後請再按登入。",
                                parent=self.dialog_parent())
            return False
        return True
