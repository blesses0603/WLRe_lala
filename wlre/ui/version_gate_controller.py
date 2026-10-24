"""Tk-safe, official-REMOTE-only game version verification before login."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from wlre import __version__
from wlre.services.lala_updater import (
    UpdateError, check_lala_release, download_verified_release,
)

from wlre.services.game_version_gate import run_prelogin_check
from wlre.services.official_version import BASELINE
from wlre.services.resource_compatibility import baseline_label
from wlre.ui.window_layout import configure_dialog


class VersionGateController:
    def initialize_version_gate(self):
        self.version_gate_state = "checking"
        self.version_gate_text = tk.StringVar(
            value=f"準備查詢官方遊戲資源版本（LaLa 基準 {baseline_label(BASELINE)}）…")
        self._version_gate_result = None
        self._version_gate_checked = 0.0
        self._version_gate_generation = 0
        self._version_gate_messages = queue.SimpleQueue()
        self._version_gate_entry_approved = False
        self.version_window = None
        self._version_heading = tk.StringVar(value="正在檢測版本…")
        self._version_baseline = tk.StringVar(value=baseline_label(BASELINE))
        self._version_main = tk.StringVar(value="等待官方查詢")
        self._version_data = tk.StringVar(value="等待官方查詢")
        self._version_remote = tk.StringVar(value="尚未驗證")
        self._version_path = tk.StringVar(value="尚未確認官方資源路徑")
        self._lala_release_text = tk.StringVar(value=f"LaLa v{__version__} · 等待 GitHub Release 查詢")
        self._lala_update_messages = queue.SimpleQueue()
        self._lala_update_generation = 0
        self._lala_update_info = None
        self._lala_update_busy = False
        self._lala_downloaded = None
        # Display-only launcher receipt. This never affects the online game gate.
        from wlre.services.world.launcher_catalog import read_launcher_status
        receipt = read_launcher_status()
        code = None if receipt is None else receipt['status']
        self._launcher_catalog_status = {
            'review_required': (
                'Launcher 四類資料格式相容，遊戲協定仍待審核'
                if receipt is not None and
                   receipt.get('data_compatibility') == 'compatible'
                else 'Launcher 已建立候選，資料及協定仍待審核'),
            'downloaded_unparsed': 'Launcher 僅下載資料，尚未驗證解包',
            'error': 'Launcher 本次候選準備未完成，安全限制不變',
            'preview': 'Launcher 僅預覽下載計畫',
        }.get(code, '尚無 Launcher 自動資源準備紀錄')
        # Display the actual missing full-runtime inputs instead of telling
        # users to guess which two ZIPs or internal tables are absent.
        # Local report is untrusted and must never affect login eligibility.
        from wlre.services.world.resource_gap_diagnostics import read_report, summarize
        gaps = (read_report(expected_checked_at_utc=receipt['checked_at_utc'])
                if receipt is not None else None)
        if gaps is not None:
            if gaps['formal_ready']:
                self._launcher_catalog_status += '｜舊式雙 ZIP 亦已通過校驗'
            elif (receipt is not None and code == 'review_required'
                    and receipt.get('data_compatibility') == 'compatible'):
                # The former ZIP-only diagnostic is not the authoritative
                # verdict for independently validated official Bundles.
                self._launcher_catalog_status += (
                    '｜舊式 ZIP 未通過校驗；官方 Bundle 由正式 Runtime 另外核對')
            else:
                self._launcher_catalog_status += '｜舊式 ZIP 診斷：' + summarize(gaps)
        if receipt is not None and receipt.get('status') == 'review_required':
            from wlre.services.world.resource_rebuilder import read_inventory_summary
            raw_inventory = read_inventory_summary(receipt['catalog_key'])
            if raw_inventory is not None:
                self._launcher_catalog_status += (
                    f"｜原始資源 {raw_inventory['asset_collected']}/"
                    f"{raw_inventory['asset_total']}，"
                    f"重用 {raw_inventory['existing_or_cached_reused']}")
            # This number is a display-only derived candidate, NOT evidence
            # that the missing pinned formal indexes are available.

    def show_version_check(self):
        """Compact, single-page version review before exposing credentials.

        No scrollable Tk canvas: the global artwork renderer does not repaint
        plain Canvas surfaces, which previously produced a large opaque slab.
        Keep footer actions separate from informational labels and never pack
        content into a fixed-height canvas.
        """
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
        # The wallpaper remains visible but no longer competes with version
        # identifiers or warning text. Only this window gets the darker tint.
        window._glass_background_dim = 0.79
        # The larger result typography needs enough physical height on
        # Windows, where ttk buttons and CJK fonts have taller native metrics.
        # Otherwise the GitHub-update action row may be clipped off-screen.
        configure_dialog(window, 1000, 710)
        window.protocol("WM_DELETE_WINDOW", self.close)
        # The helper is replaced with a no-result stub in native GUI smoke
        # tests. Never depend on its return value; derive usable dimensions
        # from Tk's own screen metrics instead.
        width = max(1, min(1000, window.winfo_screenwidth() - 24))
        height = max(1, min(710, window.winfo_screenheight() - 24))
        # configure_dialog normally fixes both maxsize and minsize. This
        # information-heavy view must reflow and grow on high-DPI desktops.
        window.minsize(min(850, width), min(590, height))
        window.maxsize(max(width, window.winfo_screenwidth() - 24),
                       max(height, window.winfo_screenheight() - 48))
        window.resizable(True, True)

        # Native ttk panels participate in LaLa's existing glass-background
        # compositor; unlike a standalone Canvas they do not obscure artwork.
        shell = ttk.Frame(window, padding=(22, 16, 22, 14))
        shell.pack(fill="both", expand=True)

        # Anchor the buttons BEFORE the data sections, so changing error text,
        # translation length or display scale cannot push them offscreen.
        footer = ttk.Frame(shell)
        footer.pack(side="bottom", fill="x")
        ttk.Separator(footer, orient="horizontal").pack(fill="x", pady=(6, 9))
        self._version_progress = ttk.Progressbar(footer, mode="indeterminate")
        self._version_progress.pack(fill="x", pady=(0, 8))
        self._version_footer_hint = ttk.Label(
            footer, text="僅查官方公開版本，不需要遊戲帳號或密碼。",
            style="Muted.TLabel", justify="left")
        self._version_footer_hint.pack(anchor="w", fill="x", pady=(0, 9))

        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="version_actions")
        ttk.Button(actions, text="結束程式", command=self.close).grid(
            row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(actions, text="重新查詢官方版本",
                   command=self.start_version_check).grid(
            row=0, column=1, sticky="ew", padx=5)
        self._version_continue_button = ttk.Button(
            actions, text="進入登入畫面", command=self.continue_to_login)
        self._version_continue_button.grid(
            row=0, column=2, sticky="ew", padx=(5, 0))

        # Single compact content column, sized naturally rather than
        # scrolling through a tall, partly empty embedded window.
        body = ttk.Frame(shell)
        body.pack(side="top", fill="both", expand=True, pady=(3, 9))
        self._version_body = body
        # The title bar already names this page. Do not repeat the
        # heading or explanatory paragraph here: the status is the focus.
        # One card holds both the prominent result and its detailed reason.
        alert = ttk.Frame(body, padding=(18, 14, 18, 15))
        alert._section_outline = True
        alert._surface_fill = (9, 27, 46, 235)
        alert.pack(fill="x", pady=(0, 15))
        self._version_alert_panel = alert
        self._version_alert_heading_label = ttk.Label(
            alert, textvariable=self._version_heading,
            style="VersionAlertHeading.TLabel", anchor="w",
            justify="left", wraplength=870)
        self._version_alert_heading_label.pack(anchor="w", fill="x", pady=(0, 5))
        self._version_alert_message_label = ttk.Label(
            alert, textvariable=self.version_gate_text,
            style="VersionAlertMessage.TLabel", anchor="w",
            justify="left", wraplength=870)
        self._version_alert_message_label.pack(anchor="w", fill="x")

        # A title above a single painted section avoids the native
        # TLabelframe notch + glass outline which created the double border.
        ttk.Label(body, text="官方遊戲資源（唯讀）",
                  style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        details = ttk.Frame(body, padding=(17, 12, 17, 12))
        details._section_outline = True
        details._surface_fill = (6, 20, 36, 226)
        details.pack(fill="x")
        self._version_resource_panel = details
        details.columnconfigure(0, minsize=160)
        details.columnconfigure(1, weight=1)
        self._version_resource_values = []
        for index, (label, variable) in enumerate((
                ("資源路徑 DataVer", self._version_path),
                ("DataPackage", self._version_data),
                ("MainPackage", self._version_main),
                ("LaLa 支援基準", self._version_baseline),
                ("檢查結果", self._version_remote))):
            ttk.Label(details, text=label, width=17,
                      anchor="w").grid(row=index, column=0,
                                       sticky="nw", pady=4, padx=(0, 12))
            value_label = ttk.Label(details, textvariable=variable,
                                    anchor="w", wraplength=710, justify="left")
            value_label.grid(row=index, column=1, sticky="ew", pady=4)
            self._version_resource_values.append(value_label)

        ttk.Label(body, text="LaLa 程式更新（GitHub 正式 Release）",
                  style="Section.TLabel").pack(anchor="w", pady=(15, 6))
        updates = ttk.Frame(body, padding=(17, 12, 17, 13))
        updates._section_outline = True
        updates._surface_fill = (6, 20, 36, 226)
        updates.pack(fill="x")
        self._version_release_panel = updates
        self._version_release_label = ttk.Label(
            updates, textvariable=self._lala_release_text,
            wraplength=850, justify="left")
        self._version_release_label.pack(anchor="w", fill="x")

        controls = ttk.Frame(updates)
        controls.pack(fill="x", pady=(10, 0))
        for column in range(3):
            controls.columnconfigure(column, weight=1, uniform="lala_update_actions")
        ttk.Button(controls, text="重新確認 LaLa 版本",
                   command=self.start_lala_release_check).grid(
                       row=0, column=0, sticky="ew", padx=(0, 5))
        self._lala_download_button = ttk.Button(
            controls, text="下載並驗證新版", command=self.download_lala_release)
        self._lala_download_button.grid(
            row=0, column=1, sticky="ew", padx=5)
        self._lala_download_button.configure(state="disabled")
        self._lala_open_button = ttk.Button(
            controls, text="開啟更新資料夾", command=self.open_lala_update_folder)
        self._lala_open_button.grid(
            row=0, column=2, sticky="ew", padx=(5, 0))
        self._lala_open_button.configure(state="disabled")

        # A <Configure> event of this window is the only event which can
        # change label wraplength. Do not use a Canvas over the artwork.
        window.bind("<Configure>", self._resize_version_text, add="+")
        self._resize_version_text()
        self._render_version_window()
        window.lift()
        window.focus_set()

    def _resize_version_text(self, event=None):
        """Reflow warning, table details and GitHub text on window resize."""
        window = self.version_window
        if window is None or not window.winfo_exists():
            return
        if event is not None and event.widget is not window:
            return
        width = window.winfo_width()
        if width <= 1:
            width = int(window.geometry().split("x", 1)[0])
        self._version_alert_heading_label.configure(wraplength=max(300, width - 112))
        self._version_alert_message_label.configure(wraplength=max(300, width - 112))
        for value_label in self._version_resource_values:
            value_label.configure(wraplength=max(240, width - 290))
        self._version_release_label.configure(wraplength=max(300, width - 108))
        self._version_footer_hint.configure(wraplength=max(300, width - 65))

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
            supported = BASELINE[package]
            if value is None:
                reason = record.get("reason")
                variable.set("無法驗證：" + reason if reason else "無法驗證：尚無官方版本回應")
            elif comparison == "same":
                variable.set(f"{value} · 與 {supported} 相同")
            else:
                variable.set(f"{value} · 與 {supported} 不同")

        path = remote.get("resource_path")
        value = path if isinstance(path, str) else (
            path.get("resource_path_version") if isinstance(path, dict) else None)
        self._version_path.set(value or "無法確認")
        source_status = remote.get("status")
        status_text = {
            "same_resources": f"兩個官方資源版本識別值均符合 {baseline_label(BASELINE)}",
            "resources_changed": "官方資源版本已異動",
        }.get(source_status)
        if not status_text:
            stage = remote.get("failed_stage")
            reason = remote.get("reason")
            if stage:
                if not reason:
                    record = packages.get(stage.removesuffix(".version"), {})
                    reason = record.get("reason", "無法讀取官方回應")
                status_text = f"{stage}：{reason}"
            else:
                status_text = "無法完整驗證；請檢查各資源包的錯誤原因"
        self._version_remote.set(status_text + "｜" + self._launcher_catalog_status)
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
            # Official versions may MATCH while mandatory, release-pinned
            # full data is still absent. Don't mislabel that as a CDN update.
            if ('LaLa 1275 缺少已校驗' in result.get('message', '')
                    or ('1275 資料驗證未通過' in result.get('message', '')
                        and source_status == 'same_resources')):
                self._version_heading.set("1275 正式資源尚未就緒 · 請先完成驗證")
            else:
                self._version_heading.set("官方版本異動 · 請等待 LaLa 更新")
            self._version_continue_button.configure(text="禁止登入", state="disabled")
        elif result.get("status") == "version_identifiers_match":
            self._version_heading.set(
                f"官方版本識別值符合 LaLa 支援基準 {baseline_label(BASELINE)}")
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
        self.version_gate_text.set(
            f"向官方更新來源查詢資源版本；LaLa 支援基準 {baseline_label(BASELINE)}…")
        self._set_login_gate_button()
        self._render_version_window()
        # Both channels are independent; a GitHub outage never changes the
        # official game resource login decision.
        self.start_lala_release_check()
        official_messages = self._version_gate_messages

        def worker():
            try:
                result = run_prelogin_check()
            except Exception:
                result = {"blocked": False, "status": "unverified",
                          "message": "版本檢測程式發生例外，請回報開發者；不代表版本已同步。",
                          "remote": {"status": "unverified", "failed_stage": "檢測程式",
                                     "reason": "內部例外（非官方版本回應）"}}
            official_messages.put((generation, result))

        threading.Thread(target=worker, name="official-version-check",
                         daemon=True).start()

    def drain_version_checks(self):
        while True:
            try:
                generation, result = self._version_gate_messages.get_nowait()
            except queue.Empty:
                self._drain_lala_update_messages()
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

    def start_lala_release_check(self):
        if self._closing:
            return
        self._lala_update_generation += 1
        generation = self._lala_update_generation
        self._lala_update_info = None
        self._lala_downloaded = None
        self._lala_update_busy = True
        self._lala_release_text.set(f"LaLa v{__version__} · 正在確認 GitHub 正式發布版本…")
        self._lala_download_button.configure(state="disabled")
        self._lala_open_button.configure(state="disabled")
        update_messages = self._lala_update_messages

        def worker():
            try:
                result = check_lala_release()
                update_messages.put((generation, "check", result))
            except (UpdateError, OSError, ValueError):
                update_messages.put((generation, "error", "無法查詢 GitHub Release，請稍後重試。"))
        threading.Thread(target=worker, name="lala-release-check", daemon=True).start()

    def download_lala_release(self):
        info = self._lala_update_info
        if (self._closing or self._lala_update_busy or not info
                or info.get("status") != "update_available"):
            return
        if not messagebox.askyesno(
                "確認下載 LaLa 更新",
                f"下載 {info['published']} 並驗證 ZIP SHA-256？\n"
                "更新包將存入使用者資料夾，不會覆蓋執行中的 LaLa。",
                parent=self.dialog_parent()):
            return
        self._lala_update_busy = True
        generation = self._lala_update_generation
        self._lala_release_text.set("下載中，完成後會驗證官方 SHA-256 與 ZIP 完整性…")
        self._lala_download_button.configure(state="disabled")
        download_messages = self._lala_update_messages

        def worker():
            try:
                archive = download_verified_release(info)
                download_messages.put((generation, "download", str(archive)))
            except (UpdateError, OSError, ValueError):
                download_messages.put((generation, "error", "更新包下載或完整性驗證失敗；不會替換任何程式。"))
        threading.Thread(target=worker, name="lala-release-download", daemon=True).start()

    def _drain_lala_update_messages(self):
        while True:
            try:
                generation, kind, value = self._lala_update_messages.get_nowait()
            except queue.Empty:
                break
            if generation != self._lala_update_generation or self._closing:
                continue
            self._lala_update_busy = False
            if kind == "check":
                self._lala_update_info = value
                if value["status"] == "update_available":
                    self._lala_release_text.set(
                        f"LaLa v{__version__} → {value['published']} 已正式發布，可下載驗證。")
                    self._lala_download_button.configure(state="normal")
                else:
                    self._lala_release_text.set(
                        f"LaLa v{__version__} · GitHub 最新正式版 {value['published']}；目前無較新正式更新。")
            elif kind == "download":
                self._lala_downloaded = value
                self._lala_release_text.set("更新包已完成 SHA-256／ZIP 驗證。請關閉 LaLa 後從資料夾安裝新版。")
                self._lala_open_button.configure(state="normal")
            else:
                self._lala_release_text.set(value)
                if self._lala_update_info and self._lala_update_info.get("status") == "update_available":
                    self._lala_download_button.configure(state="normal")

    def open_lala_update_folder(self):
        if not self._lala_downloaded:
            return
        from pathlib import Path
        from subprocess import Popen
        folder = str(Path(self._lala_downloaded).parent)
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif os.name == "posix":
                import sys
                Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
        except OSError:
            messagebox.showinfo("更新資料夾", folder, parent=self.dialog_parent())

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
        if not self._version_gate_checked or time.monotonic() - self._version_gate_checked > 300:
            self.start_version_check()
            messagebox.showinfo("版本重新檢查",
                                "上次官方版本檢查已過期，請重新確認檢測結果。",
                                parent=self.dialog_parent())
            return False
        return True
