"""One Tk-safe startup window; resource preparation never grants login."""
import os
import queue
import threading
import time
import tkinter as tk
from wlre.progress_widgets import CyanProgress
from wlre.launcher_progress import _ProgressMailbox
from wlre.services.world.launcher_catalog import prepare_on_launch
from tkinter import messagebox, ttk
from wlre import __version__
from wlre.services.lala_updater import (
    UpdateError, check_lala_release, download_verified_release,
)

from wlre.services.game_version_gate import run_prelogin_check
from wlre.services.official_version import BASELINE
from wlre.services.resource_compatibility import baseline_label
from wlre.ui.window_layout import configure_dialog


def _is_verified_login_result(result):
    """Only a complete, positively verified official response can grant entry."""
    if not isinstance(result,dict) or result.get("blocked") is not False:
        return False
    if result.get("dynamic_runtime") in ("verified","unavailable"):
        from wlre.services.game_version_gate import compare_database_identity
        return (result.get("status")=="database_matches_official"
                and result.get("dynamic_runtime")=="verified"
                and result.get("login_allowed") is True
                and result.get("database_verified") is True
                and result.get("database_comparison")=="same"
                and result.get("data_compatibility")=="compatible"
                and compare_database_identity(result.get("remote"),result.get("runtime_identity"))=="same")
    if result.get("status")!="version_identifiers_match":
        return False
    remote = result.get("remote")
    if not isinstance(remote, dict) or remote.get("status") != "same_resources":
        return False
    packages = remote.get("packages")
    return (isinstance(packages, dict) and
            all(isinstance(packages.get(package), dict) and
                packages[package].get("comparison") == "same"
                for package in BASELINE))


def _launcher_status_text():
    """Read only sanitized, display-only resource receipts, never login approval."""
    # Display-only launcher receipt. This never affects the online game gate.
    from wlre.services.world.launcher_catalog import read_launcher_status
    receipt = read_launcher_status()
    code = None if receipt is None else receipt['status']
    status = {
        'verified_official': '官方資源來源已驗證',
        'downloaded_unparsed': '官方原始資源已保存；各類解析結果另列',
        'error': '資源收集未完成；正式 Runtime 結果另列',
        'preview': '僅預覽資源收集計畫',
    }.get(code, '尚無官方資源收集紀錄')
    if receipt and receipt.get('failure_feature') and receipt.get('failure_stage'):
        feature = {'npc': 'NPC', 'shops': '商店', 'crafting': '製作',
                   'scenes': '場景', 'items': '物品'}[receipt['failure_feature']]
        status += (
            f"｜{feature}資料失敗：{receipt['failure_stage']}")
    # Current runtime verdict is rendered from the live prelogin result.
    # Historical ZIP diagnostics remain available in their own report.
    if receipt is not None and receipt.get('status') in ('verified_official', 'downloaded_unparsed'):
        from wlre.services.world.resource_rebuilder import read_inventory_summary, read_processing_summary
        raw_inventory = read_inventory_summary(receipt['catalog_key'])
        if raw_inventory is not None:
            status += (
                f"｜原始資源 {raw_inventory['asset_collected']}/"
                f"{raw_inventory['asset_total']}，"
                f"重用 {raw_inventory['existing_or_cached_reused']}")
        processing = read_processing_summary(receipt['catalog_key'])
        if processing:
            done = sum(state == '已解析' for state in processing.values())
            pending = [name for name, state in processing.items()
                       if state != '已解析']
            status += f'｜收集階段解析 {done}/{len(processing)}'
            if pending:
                status += '；待處理：' + '、'.join(pending)
        elif code == 'downloaded_unparsed':
            status += '｜尚無各類解析驗證紀錄'
        # This number is a display-only derived candidate, NOT evidence
        # that the missing pinned formal indexes are available.
    return status


class VersionGateController:
    def initialize_version_gate(self):
        self.version_gate_state = "checking"
        self.version_gate_text = tk.StringVar(
            value="準備 LaLa 官方資源，完成後將獨立檢查官方版本與 Runtime…")
        self._version_gate_result = None
        self._version_gate_checked = 0.0
        self._version_gate_generation = 0
        self._version_gate_messages = queue.SimpleQueue()
        self._version_gate_entry_approved = False
        self._login_version_status = tk.StringVar(value="版本尚未確認，請先完成官方版本檢測。")
        self.version_window = None
        self._version_heading = tk.StringVar(value="正在準備啟動…")
        self._version_baseline = tk.StringVar(value="等待官方版本確認")
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
        self._startup_prepared = threading.Event()
        self._startup_exit_requested = threading.Event()
        self._version_worker_done = threading.Event()
        self._version_worker_done.set()
        self._startup_progress = _ProgressMailbox()
        self._official_progress = _ProgressMailbox()
        self._startup_started_at = None
        self._startup_stage_started_at = None
        self._startup_finished_at = None
        self._startup_elapsed_signature = None
        self._startup_stage_key = None
        self._startup_elapsed = tk.StringVar(value="準備開始；不以動畫推估完成比例")
        self._startup_phase = 'preparing'
        self._startup_progress_update = None
        self._startup_failure = None
        self._startup_close_job = None
        self._launcher_catalog_status = _launcher_status_text()

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
        window.title("飄流Re:LaLa · 資源準備與官方線上版本檢測")
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
        self._version_shell = shell
        self._version_fit_job = None

        # Anchor the buttons BEFORE the data sections, so changing error text,
        # translation length or display scale cannot push them offscreen.
        footer = ttk.Frame(shell)
        footer.pack(side="bottom", fill="x")
        ttk.Separator(footer, orient="horizontal").pack(fill="x", pady=(6, 9))
        self._version_elapsed_label = ttk.Label(
            footer, textvariable=self._startup_elapsed, style="Muted.TLabel",
            justify="left")
        self._version_elapsed_label.pack(anchor="w", fill="x", pady=(0, 5))
        self._version_progress = CyanProgress(footer, tk)
        self._version_progress.canvas.pack_configure(pady=(0, 8))
        self._version_footer_hint = ttk.Label(
            footer, text="僅查官方公開版本，不需要遊戲帳號或密碼。",
            style="Muted.TLabel", justify="left")
        self._version_footer_hint.pack(anchor="w", fill="x", pady=(0, 9))

        actions = ttk.Frame(footer)
        actions.pack(fill="x")
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="version_actions")
        self._version_exit_button = ttk.Button(actions, text="結束程式", command=self.close)
        self._version_exit_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._version_retry_button = ttk.Button(
            actions, text="重新查詢官方版本", command=self.start_version_check)
        self._version_retry_button.grid(row=0, column=1, sticky="ew", padx=5)
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
        self._version_resource_labels = []
        for index, (label, variable) in enumerate((
                ("資源路徑 DataVer", self._version_path),
                ("DataPackage", self._version_data),
                ("MainPackage", self._version_main),
                ("目前 Runtime 資源版本", self._version_baseline),
                ("檢查結果", self._version_remote))):
            name_label = ttk.Label(details, text=label, anchor="w")
            name_label.grid(row=index, column=0, sticky="nw", pady=4, padx=(0, 12))
            self._version_resource_labels.append(name_label)
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
        self._lala_retry_button = ttk.Button(
            controls, text="重新確認 LaLa 版本", command=self.start_lala_release_check)
        self._lala_retry_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
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
        # Textvariable writes can be processed before pack/grid have updated
        # the requested section heights. Observe their settled geometry too.
        for section in (alert, details, updates, footer):
            section.bind('<Configure>', lambda event: self._schedule_version_fit(), add='+')
        for variable in (self.version_gate_text, self._version_remote, self._lala_release_text):
            variable.trace_add('write', lambda *args: self._schedule_version_fit())
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
        label_width = max(160, *(label.winfo_reqwidth() for label in self._version_resource_labels))
        for value_label in self._version_resource_values:
            value_label.configure(wraplength=max(240, width - label_width - 130))
        self._version_release_label.configure(wraplength=max(300, width - 108))
        self._version_footer_hint.configure(wraplength=max(300, width - 65))
        self._version_elapsed_label.configure(wraplength=max(300, width - 65))
        self._schedule_version_fit()

    def _schedule_version_fit(self):
        window = self.version_window
        if self._closing or window is None or not window.winfo_exists():
            return
        pending = getattr(self, '_version_fit_job', None)
        if pending is not None:
            window.after_cancel(pending)
        self._version_fit_job = window.after_idle(self._fit_version_height)

    def _fit_version_height(self):
        """Allow late long status text to grow the view above its pinned footer."""
        self._version_fit_job = None
        window = self.version_window
        if self._closing or window is None or not window.winfo_exists():
            return
        # GlassTheme inserts its own title bar above shell. The Toplevel's
        # request includes that bar; shell.winfo_reqheight() omits it.
        needed = min(window.winfo_reqheight(), window.winfo_screenheight() - 48)
        if needed > window.winfo_height():
            window.geometry(f'{window.winfo_width()}x{needed}')

    def hide_version_check(self):
        window = self.version_window
        if window is not None and window.winfo_exists():
            window.withdraw()

    def _render_version_window(self):
        window = self.version_window
        if window is None or not window.winfo_exists():
            return
        if getattr(self, '_startup_exit_requested', None) is not None and self._startup_exit_requested.is_set():
            self._version_heading.set("正在安全結束…")
            self.version_gate_text.set("正在完成目前的資源寫入與檢查，完成後會結束程式。")
            self._version_footer_hint.configure(text="不會開啟登入畫面，也不會中斷資源快取寫入。")
            self._version_progress.set_counts(None)
            self._version_continue_button.configure(text="正在結束", state="disabled")
            for button in (self._version_retry_button, self._version_exit_button,
                           self._lala_retry_button, self._lala_download_button,
                           self._lala_open_button):
                button.configure(state="disabled")
            return
        result = self._version_gate_result or {}
        remote = result.get("remote")
        remote = remote if isinstance(remote, dict) else {}
        packages = remote.get("packages")
        packages = packages if isinstance(packages, dict) else {}
        dynamic_mode = result.get("dynamic_runtime") in ("verified", "unavailable")
        if dynamic_mode:
            self._version_baseline.set(result.get("baseline_label", "官方動態 Runtime"))
        elif result:
            self._version_baseline.set(result.get("baseline_label", baseline_label(BASELINE)))
        for package, variable in (("MainPackage", self._version_main),
                                  ("DataPackage", self._version_data)):
            record = packages.get(package, {})
            value = record.get("remote")
            comparison = record.get("comparison", "unverified")
            supported = BASELINE[package]
            if value is None:
                reason = record.get("reason")
                variable.set("無法驗證：" + reason if reason else "無法驗證：尚無官方版本回應")
            elif dynamic_mode:
                suffix = ("已由官方 Manifest／Runtime 核對" if result.get("dynamic_runtime") == "verified"
                          else "官方版本已取得；Runtime 尚未驗證")
                variable.set(f"{value} · {suffix}")
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
        if dynamic_mode and remote.get("status") in ("same_resources", "resources_changed"):
            status_text = ("官方資源與 Runtime 版本一致" if result.get("dynamic_runtime") == "verified"
                           else "官方版本已確認，完整 Runtime 尚未就緒")
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
        db_status = {'same': '資料庫版本符合官方', 'different': '資料庫版本與官方不同',
                     'unverified': '資料庫版本未確認'}.get(result.get('database_comparison'))
        self._version_remote.set(
            "正式 Runtime／登入驗證：" + status_text + (('｜' + db_status) if db_status else '')
            + "\n資源收集紀錄：" + self._launcher_catalog_status)
        if hasattr(self, '_version_retry_button'):
            self._version_retry_button.configure(
                state="disabled" if self.version_gate_state == "checking" else "normal")
        if self.version_gate_state == "checking":
            preparing = self._startup_phase == 'preparing'
            update = self._startup_progress_update
            self._version_heading.set("正在收集與整理官方資源…" if preparing else
                                      ((update[0] + "…") if update else "正在進行正式登入驗證…"))
            self._version_main.set("等待資源收集完成" if preparing else "等待正式驗證結果")
            self._version_data.set("等待資源收集完成" if preparing else "等待正式驗證結果")
            self._version_path.set("等待正式驗證結果")
            self._version_remote.set("正在準備並校驗官方資源" if preparing else
                                     "正在檢查官方線上來源")
            self._version_progress.set_counts(update[2] if update else None)
            if update:
                self._version_remote.set(update[0] + (
                    '｜' + self._startup_failure if self._startup_failure else ''))
            self._version_footer_hint.configure(text=(
                "1 / 2 · 資源收集與解析摘要不代表 Runtime 已授權；正式驗證完成前不能登入。" if preparing else
                "2 / 2 · 正式核對官方版本、Runtime 與資料庫實際內容；完成前不能登入。"))
            self._version_continue_button.configure(
                text="資源準備中" if preparing else "檢查中", state="disabled")
            return

        VersionGateController._finish_startup_presentation(self)
        if hasattr(self, '_version_footer_hint'):
            self._version_footer_hint.configure(text="以上方正式登入驗證結果為準；資源收集與解析摘要不授予登入權限。")
        if self.version_gate_state == "blocked":
            # Official versions may MATCH while mandatory, release-pinned
            # full data is still absent. Don't mislabel that as a CDN update.
            if result.get("status") == "database_mismatch":
                self._version_heading.set("LaLa 資料庫與官方尚未一致 · 請先同步")
            elif result.get("status") == "runtime_unavailable":
                self._version_heading.set("目前官方 Runtime 尚未就緒 · 請查看資源驗證結果")
            elif result.get("status") == "client_unsupported":
                self._version_heading.set("官方客戶端已更新 · 協定相容性待驗收")
            elif ('LaLa 1275 缺少已校驗' in result.get('message', '')
                    or ('1275 資料驗證未通過' in result.get('message', '')
                        and source_status == 'same_resources')):
                self._version_heading.set("1275 正式資源尚未就緒 · 請先完成驗證")
            elif result.get("status") == "unverified":
                self._version_heading.set("官方遊戲版本無法驗證 · 禁止登入")
            else:
                self._version_heading.set("官方版本異動 · 請等待 LaLa 更新")
            self._version_continue_button.configure(text="禁止登入", state="disabled")
        elif _is_verified_login_result(result):
            self._version_heading.set(
                "LaLa 資料庫與官方一致 · 可以登入" if dynamic_mode else
                f"官方版本識別值符合 LaLa 支援基準 {baseline_label(BASELINE)}")
            self._version_continue_button.configure(text="進入登入畫面", state="normal")
        else:
            self._version_heading.set("官方遊戲版本無法驗證 · 禁止登入")
            self._version_continue_button.configure(
                text="禁止登入", state="disabled")

    def continue_to_login(self):
        """Explicit acknowledgement grants one login stage, not network access."""
        if self._closing or self._startup_exit_requested.is_set() or self.version_gate_state == "checking":
            return
        if (self.version_gate_state != "ready" or
                not _is_verified_login_result(self._version_gate_result)):
            messagebox.showwarning("禁止登入", self.version_gate_text.get(),
                                   parent=self.dialog_parent())
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

    def _update_login_version_status(self):
        """Describe the gate policy without implying live server monitoring."""
        if not hasattr(self, '_login_version_status'):
            return
        if self._closing or self._startup_exit_requested.is_set():
            text = "正在安全結束程式；不會建立新的連線。"
        elif self.version_gate_state == 'checking':
            text = "正在準備資源或檢查官方版本；完整驗證通過前不會連線。"
        elif (self.version_gate_state == 'ready' and self._version_gate_entry_approved
              and _is_verified_login_result(self._version_gate_result)):
            if (not self._version_gate_checked
                    or time.monotonic() - self._version_gate_checked > 300):
                text = "上次檢查已過期；按登入後會先重新檢查，通過前不會連線。"
            else:
                # This remains true if the page stays open beyond five minutes.
                # Do not claim the currently unseen official version is unchanged.
                text = "上次官方檢查通過；結果最多沿用 5 分鐘，登入時會確認是否過期（非即時監測）。"
        else:
            text = "版本尚未確認或資料不一致，請按「版本檢測」重新確認。"
        self._login_version_status.set(text)

    def _set_login_gate_button(self):
        self._update_login_version_status()
        if hasattr(self, "connect_button") and self.connect_button.winfo_exists():
            enabled = (self._version_gate_entry_approved and
                       self.version_gate_state == "ready" and
                       _is_verified_login_result(self._version_gate_result) and
                       not self.live_active)
            self.connect_button.configure(state="normal" if enabled else "disabled")

    def start_version_check(self):
        if self._closing or self._startup_exit_requested.is_set():
            return
        # Serialize cache-writing work. Rapid clicks cannot start duplicate
        # preparation or race runtime activation. A completed retry always
        # makes a fresh official check, never reuses the launcher receipt.
        if not self._version_worker_done.is_set():
            return
        if (self.login_window is not None and self.login_window.winfo_exists()
                and self.login_window.state() != "withdrawn" and not self.live_active):
            self.show_version_check()
        self._version_gate_generation += 1
        generation = self._version_gate_generation
        self._version_gate_entry_approved = False
        self.version_gate_state = "checking"
        self._version_gate_result = None
        self._startup_progress.take()  # Discard an earlier generation's display.
        self._official_progress.take()
        self._startup_progress_update = None
        self._startup_started_at = time.monotonic()
        self._startup_stage_started_at = self._startup_started_at
        self._startup_finished_at = None
        self._startup_elapsed_signature = None
        self._startup_stage_key = None
        bar = getattr(self, '_version_progress', None)
        if bar is not None:
            bar.reset()
        self._update_startup_elapsed()
        self._startup_phase = 'official' if self._startup_prepared.is_set() else 'preparing'
        self.version_gate_text.set(
            "正在向官方來源確認資源版本與完整 Runtime…" if self._startup_prepared.is_set() else
            "正在準備並校驗 LaLa 官方資源，完成後將獨立檢查登入條件…")
        self._set_login_gate_button()
        self._render_version_window()
        # GitHub is independent: an outage never changes the game login gate.
        self.start_lala_release_check()
        official_messages = self._version_gate_messages
        prepared = self._startup_prepared
        progress = self._startup_progress
        official_progress = self._official_progress
        exiting = self._startup_exit_requested
        done = self._version_worker_done
        done.clear()

        def worker():
            # Capture only thread-safe data, never App/Tk objects. A non-daemon
            # worker and deferred close keep cache writes alive until completed.
            try:
                if not prepared.is_set():
                    try:
                        receipt = prepare_on_launch(progress=progress.report)
                        if not isinstance(receipt, dict) or receipt.get('status') == 'error':
                            status = '資源收集未完成；正式 Runtime 結果另列'
                        else:
                            status = _launcher_status_text()
                    except Exception:
                        status = '資源收集發生例外；正式 Runtime 結果另列'
                    progress.finish(status)
                    prepared.set()
                if exiting.is_set():
                    return
                try:
                    result = run_prelogin_check(progress=official_progress.report)
                except Exception:
                    result = {"blocked": True, "status": "unverified",
                              "message": "版本檢測程式發生例外，已禁止登入；請重新查詢或回報開發者。",
                              "remote": {"status": "unverified", "failed_stage": "檢測程式",
                                         "reason": "內部例外（非官方版本回應）"}}
                official_messages.put((generation, result))
            finally:
                done.set()

        thread = threading.Thread(target=worker, name="official-version-check", daemon=False)
        try:
            thread.start()
        except RuntimeError:
            done.set()
            official_messages.put((generation, {
                "blocked": True, "status": "unverified",
                "message": "啟動檢查無法開始，已禁止登入；請重新查詢。"}))

    def _drain_startup_progress(self):
        update, failure, terminal = self._startup_progress.take()
        official_update, _, _ = self._official_progress.take()
        if self._closing or self._startup_exit_requested.is_set() or self.version_gate_state != 'checking':
            return
        if failure is not None:
            self._startup_failure = failure
        if terminal is not None:
            self._launcher_catalog_status = terminal[0]
            if self._startup_failure:
                self._launcher_catalog_status += '｜收集階段：' + self._startup_failure
            self._startup_phase = 'official'
            self._startup_progress_update = None
        if official_update is not None:
            self._startup_phase = 'official'
            update = official_update
        elif self._startup_phase != 'preparing':
            update = None  # Late collection messages cannot replace the formal phase.
        if update is not None:
            self._startup_progress_update = update
            if update[0] != self._startup_stage_key:
                self._startup_stage_key = update[0]
                self._startup_stage_started_at = time.monotonic()
        if update is not None:
            self.version_gate_text.set(update[1])
        elif terminal is not None:
            self.version_gate_text.set("資源收集階段已結束，正在獨立核對官方版本、Runtime 與資料庫實際內容…")
        if update is not None or terminal is not None:
            self._render_version_window()

    def _update_startup_elapsed(self):
        """Use the existing UI poll; at most one text change per second, no timer."""
        if not hasattr(self, '_startup_elapsed') or self._startup_started_at is None:
            return
        finished = self._startup_finished_at
        now = time.monotonic() if finished is None else finished
        total = max(0, int(now - self._startup_started_at))
        stage = max(0, int(now - (self._startup_stage_started_at or self._startup_started_at)))
        if finished is not None:
            state = 'complete' if self.version_gate_state == 'ready' else 'blocked'
            text = ('本次正式檢查完成' if state == 'complete' else '本次正式檢查未通過') + f' · 共用 {total} 秒'
            signature = state, total
        else:
            closing = self._startup_exit_requested.is_set()
            text = (f'安全結束中 · 已用 {total} 秒' if closing else
                    f'已用 {total} 秒 · 目前階段 {stage} 秒（不估算完成比例）')
            signature = closing, total, stage
        if signature != self._startup_elapsed_signature:
            self._startup_elapsed_signature = signature
            self._startup_elapsed.set(text)

    def _finish_startup_presentation(self):
        if getattr(self, '_startup_started_at', None) is not None and self._startup_finished_at is None:
            self._startup_finished_at = time.monotonic()
        bar = getattr(self, '_version_progress', None)
        if bar is not None:
            bar.finish()
        if hasattr(self, '_startup_elapsed'):
            VersionGateController._update_startup_elapsed(self)

    def defer_close_for_startup(self):
        """Keep the same responsive window until current writes safely finish."""
        done = getattr(self, '_version_worker_done', None)
        if done is None or done.is_set():
            return False
        self._startup_exit_requested.set()
        self._version_gate_entry_approved = False
        self._version_gate_result = None
        self._set_login_gate_button()
        self._render_version_window()
        if self._startup_close_job is None:
            self._startup_close_job = self.root.after(80, self._finish_startup_close)
        return True

    def _finish_startup_close(self):
        self._startup_close_job = None
        self.close()

    def drain_version_checks(self):
        self._drain_startup_progress()
        while True:
            try:
                generation, result = self._version_gate_messages.get_nowait()
            except queue.Empty:
                self._drain_lala_update_messages()
                self._update_startup_elapsed()
                return
            if (generation != self._version_gate_generation or self._closing
                    or self._startup_exit_requested.is_set()):
                continue
            if not isinstance(result, dict):
                result = {}
            result = dict(result)
            if not _is_verified_login_result(result):
                # Treat missing/contradictory status or an unexpected response
                # as a failed verification, even if the worker said blocked=False.
                result["blocked"] = True
                if result.get("status") == "version_identifiers_match":
                    result["status"] = "unverified"
                    result["message"] = "官方版本驗證結果不完整或互相矛盾；禁止登入，請重新查詢。"
            self._version_gate_result = result
            self._version_gate_checked = time.monotonic()
            self.version_gate_state = (
                "ready" if _is_verified_login_result(result) else "blocked")
            self._finish_startup_presentation()
            self.version_gate_text.set(
                result.get("message") or "官方版本無法完整驗證；禁止登入，請重新查詢。")
            self._set_login_gate_button()
            self._render_version_window()
            if self.version_gate_state == "blocked" and not self.live_active:
                self.show_version_check()

    def start_lala_release_check(self):
        if self._closing or self._startup_exit_requested.is_set():
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
        if (self._closing or self._startup_exit_requested.is_set() or self._lala_update_busy or not info
                or info.get("status") != "update_available"):
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
            if (generation != self._lala_update_generation or self._closing
                    or self._startup_exit_requested.is_set()):
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
        self._update_login_version_status()
        if self._closing or self._startup_exit_requested.is_set():
            return False
        if (self.version_gate_state != "ready" or
                not self._version_gate_entry_approved or
                self._version_gate_result is None):
            messagebox.showinfo("先完成版本檢測",
                                "請先在官方版本檢測視窗檢查並確認結果。",
                                parent=self.dialog_parent())
            self.show_version_check()
            return False
        if not _is_verified_login_result(self._version_gate_result):
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
