"""Tk-safe desktop version check UI coordinator; worker never touches widgets."""
import queue
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox
from wlre.services.game_version_gate import find_yoo_root, run_prelogin_check, scan_local_manifests
from wlre.storage.paths import data_root


class VersionGateController:
    def initialize_version_gate(self):
        import tkinter as tk
        self.version_gate_state = "checking"
        self.version_gate_text = tk.StringVar(value="正在準備 1262 官方資源版本檢測…")
        self._version_gate_result = None
        self._version_gate_checked = 0.0
        self._version_gate_generation = 0
        self._version_gate_messages = queue.SimpleQueue()
        self.version_gate_root = self._load_game_root()

    @staticmethod
    def _load_game_root():
        path = data_root() / "official_game_yoo_root.txt"
        try:
            if not path.is_file() or path.stat().st_size > 4096:
                return None
            return path.read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeError):
            return None

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
            # Continue with this session's selected directory without persistence.
            pass
        self.start_version_check()

    def _set_login_gate_button(self):
        if hasattr(self, "connect_button") and self.connect_button.winfo_exists():
            disabled = (self.live_active or self.version_gate_state in ("checking", "blocked"))
            self.connect_button.configure(state="disabled" if disabled else "normal")

    def start_version_check(self):
        if self._closing:
            return
        self._version_gate_generation += 1
        generation = self._version_gate_generation
        selected = self.version_gate_root
        self.version_gate_state = "checking"
        self.version_gate_text.set("正在檢查遊戲資源版本（1262 基準）…")
        self._set_login_gate_button()

        def worker():
            try:
                result = run_prelogin_check(selected)
            except Exception:
                # Never treat an implementation/network failure as a match.
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

    def _block_for_local_change(self, local):
        message = "偵測到官方遊戲本機 Manifest 資源版本與 LaLa 1262 不同，禁止登入。請等待 LaLa 更新與相容性驗證。"
        self._version_gate_result = {"blocked": True, "status": "blocked",
                                     "message": message, "local": local}
        self.version_gate_state = "blocked"
        self.version_gate_text.set(message)
        self._set_login_gate_button()

    def can_login_after_version_check(self):
        """Authoritative guard for App.connect, independent of widget disabled state."""
        if self.version_gate_state == "checking":
            messagebox.showinfo("版本檢查中", "請先完成遊戲資源版本檢查。", parent=self.dialog_parent())
            return False
        if self.version_gate_state == "blocked":
            messagebox.showwarning("遊戲版本已變更", self.version_gate_text.get(), parent=self.dialog_parent())
            return False
        # Rescan disk synchronously to catch a game update after startup.
        try:
            local = scan_local_manifests(self.version_gate_root)
        except (OSError, ValueError):
            local = {"status": "unverified"}
        if local["status"] == "changed":
            self._block_for_local_change(local)
            messagebox.showwarning("遊戲版本已變更", self.version_gate_text.get(), parent=self.dialog_parent())
            return False
        # Once a verified online source is configured, refresh stale checks.
        import os
        sources_configured = (os.getenv("WLRE_OFFICIAL_MAIN_VERSION_URL") and
                              os.getenv("WLRE_OFFICIAL_DATA_VERSION_URL"))
        if sources_configured and (not self._version_gate_checked or
                                   time.monotonic() - self._version_gate_checked > 300):
            self.start_version_check()
            messagebox.showinfo("重新驗證版本", "檢測資料已逾期，正在重新讀取官方版本；完成後請再按登入。",
                                parent=self.dialog_parent())
            return False
        return True
