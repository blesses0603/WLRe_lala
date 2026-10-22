"""Tk-safe, official-REMOTE-only game version verification before login."""
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from wlre.services.game_version_gate import configured_sources, run_prelogin_check
from wlre.ui.window_layout import configure_dialog


class VersionGateController:
    def initialize_version_gate(self):
        self.version_gate_state = "checking"
        self.version_gate_text = tk.StringVar(value="準備查詢官方遊戲資源版本（LaLa 基準 1262）…")
        self._version_gate_result = None
        self._version_gate_checked = 0.0
        self._version_gate_generation = 0
        self._version_gate_messages = queue.SimpleQueue()
        self._version_gate_entry_approved = False
        self.version_window = None
        self._version_heading = tk.StringVar(value="正在檢測版本…")
        self._version_baseline = tk.StringVar(value="1262")
        self._version_main = tk.StringVar(value="等待官方查詢")
        self._version_data = tk.StringVar(value="等待官方查詢")
        self._version_remote = tk.StringVar(value="尚未驗證")

    def show_version_check(self):
        """Only show credential UI after this separate window is acknowledged."""
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
        window.title("飄流Re:LaLa · 官方線上版本檢測")
        configure_dialog(window, 720, 440)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.resizable(False, False)

        body = ttk.Frame(window, padding=(25, 23))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="官方伺服器遊戲資源版本檢測",
                  font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(body, text="只查詢官方線上 YooAsset 版本，不讀取本機遊戲檔案",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        ttk.Label(body, textvariable=self._version_heading,
                  font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(0, 7))
        ttk.Label(body, textvariable=self.version_gate_text,
                  wraplength=650, justify="left").pack(anchor="w", fill="x", pady=(0, 13))

        details = ttk.LabelFrame(body, text="線上版本比較", padding=(12, 9))
        details.pack(fill="x")
        for label, var in (("LaLa 支援資源", self._version_baseline),
                           ("MainPackage", self._version_main),
                           ("DataPackage", self._version_data),
                           ("查詢狀態", self._version_remote)):
            row = ttk.Frame(details)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=16).pack(side="left")
            ttk.Label(row, textvariable=var, wraplength=500,
                      justify="left").pack(side="left", fill="x", expand=True)

        self._version_progress = ttk.Progressbar(body, mode="indeterminate")
        self._version_progress.pack(fill="x", pady=(14, 7))
        ttk.Label(body, text="版本查詢不需要帳號或密碼。官方端點未驗證時將顯示未知。",
                  style="Muted.TLabel").pack(anchor="w")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(13, 0))
        ttk.Button(actions, text="結束程式", command=self.close).pack(side="left")
        ttk.Button(actions, text="重新查詢官方版本",
                   command=self.start_version_check).pack(side="left", padx=(9, 0))
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
        remote = result.get("remote", {})
        packages = remote.get("packages", {})
        for package, variable in (("MainPackage", self._version_main),
                                  ("DataPackage", self._version_data)):
            record = packages.get(package, {})
            value = record.get("remote")
            comparison = record.get("comparison", "unverified")
            if value is None:
                variable.set("無法驗證官方線上版本")
            elif comparison == "same":
                variable.set(f"{value} · 與 1262 相同")
            else:
                variable.set(f"{value} · 與 1262 不同")

        source_status = remote.get("status")
        self._version_remote.set({
            "same_resources": "兩個官方資源版本識別值均符合 1262",
            "resources_changed": "官方資源版本已異動",
        }.get(source_status, "官方公開版本來源尚未確認或連線失敗"))
        if self.version_gate_state == "checking":
            self._version_heading.set("正在向官方來源查詢版本…")
            self._version_main.set("查詢中…")
            self._version_data.set("查詢中…")
            self._version_remote.set("正在檢查官方線上來源")
            self._version_progress.start(12)
            self._version_continue_button.configure(text="檢查中", state="disabled")
            return

        self._version_progress.stop()
        if self.version_gate_state == "blocked":
            self._version_heading.set("官方版本異動 · 請等待 LaLa 更新")
            self._version_continue_button.configure(text="禁止登入", state="disabled")
        elif result.get("status") == "version_identifiers_match":
            self._version_heading.set("官方版本識別值符合 1262")
            self._version_continue_button.configure(text="進入登入畫面", state="normal")
        else:
            self._version_heading.set("官方遊戲版本無法驗證")
            self._version_continue_button.configure(
                text="了解風險，繼續登入", state="normal")

    def continue_to_login(self):
        """Explicit acknowledgement grants one login stage, not network access."""
        if self.version_gate_state == "checking":
            return
        if self.version_gate_state == "blocked":
            messagebox.showwarning("禁止登入", self.version_gate_text.get(),
                                   parent=self.dialog_parent())
            return
        if self._version_gate_result is None:
            return
        self._version_gate_entry_approved = True
        self.hide_version_check()
        self.show_login()
        self._set_login_gate_button()

    def reopen_version_check(self):
        if self.live_active:
            messagebox.showinfo("已連線", "請先中斷連線再重新檢查版本。",
                                parent=self.dialog_parent())
            return
        self._version_gate_entry_approved = False
        self._set_login_gate_button()
        self.show_version_check()
        self.start_version_check()

    def _set_login_gate_button(self):
        if hasattr(self, "connect_button") and self.connect_button.winfo_exists():
            enabled = (self._version_gate_entry_approved and
                       self.version_gate_state == "ready" and not self.live_active)
            self.connect_button.configure(state="normal" if enabled else "disabled")

    def start_version_check(self):
        if self._closing:
            return
        if (self.login_window is not None and self.login_window.winfo_exists()
                and self.login_window.state() != "withdrawn" and not self.live_active):
            self.show_version_check()
        self._version_gate_generation += 1
        generation = self._version_gate_generation
        self._version_gate_entry_approved = False
        self.version_gate_state = "checking"
        self._version_gate_result = None
        self.version_gate_text.set("向官方更新來源查詢資源版本；LaLa 支援基準 1262…")
        self._set_login_gate_button()
        self._render_version_window()

        def worker():
            try:
                result = run_prelogin_check()
            except Exception:
                result = {"blocked": False, "status": "unverified",
                          "message": "官方版本查詢失敗，無法確認最新版，不代表已同步。"}
            self._version_gate_messages.put((generation, result))

        threading.Thread(target=worker, name="official-version-check",
                         daemon=True).start()

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
            self.version_gate_state = "blocked" if result.get("blocked") else "ready"
            self.version_gate_text.set(result["message"])
            self._set_login_gate_button()
            self._render_version_window()
            if result.get("blocked") and not self.live_active:
                self.show_version_check()

    def can_login_after_version_check(self):
        """Authoritative App.connect guard, even when invoked without button."""
        if (self.version_gate_state != "ready" or
                not self._version_gate_entry_approved or
                self._version_gate_result is None):
            messagebox.showinfo("先完成版本檢測",
                                "請先在官方版本檢測視窗檢查並確認結果。",
                                parent=self.dialog_parent())
            self.show_version_check()
            return False
        if self._version_gate_result.get("blocked"):
            messagebox.showwarning("禁止登入", self.version_gate_text.get(),
                                   parent=self.dialog_parent())
            self.show_version_check()
            return False
        # A previously checked official version can go stale while browsing
        # login settings. Never use an expired online result as a login pass.
        sources = configured_sources()
        if any(sources.values()) and (
                not self._version_gate_checked or
                time.monotonic() - self._version_gate_checked > 300):
            self.start_version_check()
            messagebox.showinfo("版本重新檢查",
                                "上次官方版本檢查已過期，請重新確認檢測結果。",
                                parent=self.dialog_parent())
            return False
        return True
