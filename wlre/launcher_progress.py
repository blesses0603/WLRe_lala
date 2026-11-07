"""A compact LaLa launcher splash with *real* official sync stages.

This window is created, updated and destroyed only on Tk's main thread.
The resource worker never references the window. It sends bounded event data
through a coalescing mailbox; completed/failed preparation never grants login permission.
"""
from __future__ import annotations

import os
import sys
import threading

from wlre.progress_widgets import (
    ACCENT as _ACCENT, TRACK as _TRACK, CyanProgress as _CyanProgress,
)

STEPS = (
    'official_version', 'manifest', 'bundle_plan', 'bundle_sync',
    'bundle_verify', 'extract', 'official_store',
)
FEATURE_LABELS = {
    'npc': 'NPC 事件', 'shops': '商店與物品',
    'crafting': '製作配方', 'scenes': '場景資料',
}
STEP_LABELS = {
    'official_version': '檢查官方版本',
    'official_revision': '已比對官方版本變化，準備增量資源',
    'official_revision_unavailable': '本次版本紀錄無法保存，保留資源校驗結果',
    'manifest': '讀取並驗證 Manifest',
    'bundle_plan': '分析資源位置與相依',
    'bundle_sync': '下載並校驗必要 Bundle',
    'bundle_item': '逐個驗證 Bundle 完整性',
    'bundle_verify': '重新核對 Bundle 完整性',
    'extract': '解包並驗證遊戲資料',
    'official_store': '建立版本化私人快取',
    'compatibility_check': '核對五類資料的相容性',
    'compatibility_ready': '資料格式檢查通過，協定仍待驗證',
    'formal_check': '核對完整正式 1275 資料來源',
    'formal_checked': '正式資源載入條件檢查完成',
    'raw_rebuild': '補建官方全部原始資料，重用已驗證檔案',
    'raw_resource_item': '整理已存在及新取得的資源',
    'raw_rebuild_ready': '本次資源補建與續補已完成',
    'raw_rebuild_unavailable': '部分原始資源仍待補建',
    'classification_ready': '現有資料分類索引已更新',
    'classification_unavailable': '分類索引暫不可用，原有安全限制不變',
    'cached_official': '已使用驗證過的正式 SQLite 快取',
    'preview_ready': '資源預覽完成',
    'download_ready': 'Bundle 同步完成',
    'verified_official': '官方資源資料已建立',
    'extract_failed': '官方資源資料解析失敗',
    'server_list_ready': '官方伺服器清單已驗證並同步',
    'server_list_unavailable': '官方伺服器清單暫不可用，登入仍須獨立驗證',
    'runtime_identity_verified': '官方版本與資源清單已核對',
    'runtime_identity_unavailable': '官方版本資訊暫不可用，繼續獨立驗證',
    'runtime_bundle_plan': '核對當次官方版本所需的 Bundle',
    'runtime_bundle_ready': '官方 Runtime Bundle 已下載並完成完整性校驗',
    'runtime_bundle_unavailable': '官方 Runtime Bundle 尚未補齊或驗證，將繼續官方資源資料流程',
}
_BG = '#101927'
_PANEL = '#172539'
_FG = '#eef6ff'
_MUTED = '#a6b9cc'
_WARNING = '#f0c674'
_POLL_MS = 80


def progress_message(phase, details=None):
    """Convert whitelisted stage data into a short human-readable message."""
    details = details if isinstance(details, dict) else {}
    if phase == 'official_revision':
        state, data, main = (details.get('state'), details.get('data'),
                             details.get('main'))
        if (state in ('first_observation', 'changed', 'unchanged')
                and all(isinstance(value, str) and value.isdigit()
                        and 1 <= len(value) <= 6 for value in (data, main))):
            names = f'DataPackage {data}／MainPackage {main}'
            if state == 'changed':
                return f'偵測到官方資源版本異動（{names}）；自動準備新版官方資源'
            if state == 'first_observation':
                return f'首次記錄官方資源版本（{names}）；開始驗證官方資源'
            return f'官方資源版本未變（{names}）；重新核對既有資料'
        return '已比對官方資源版本，官方資源仍需獨立校驗'
    if phase == 'runtime_bundle_ready':
        done, downloaded = details.get('completed'), details.get('downloaded')
        if (type(done) is int and type(downloaded) is int
                and 0 <= downloaded <= done <= 24):
            return f'已核對 {done} 份必要 Bundle（本輪補下載 {downloaded}）'
    if phase == 'classification_ready':
        total, existing = details.get('total'), details.get('existing')
        if (type(total) is int and type(existing) is int
                and 0 <= existing <= total <= 100000):
            return f'已分類 {total} 筆官方資源；本機已有 {existing} 筆原始官方資源'
    if phase in ('raw_resource_item', 'raw_rebuild_ready'):
        done, total = details.get('completed'), details.get('total')
        if (type(done) is int and type(total) is int
                and 0 <= done <= total and total > 0):
            message = f'已驗證整理 {done} / {total} 份官方資源'
            blockers = details.get('formal_blockers')
            if (phase == 'raw_rebuild_ready' and type(blockers) is list
                    and 0 < len(blockers) <= 8
                    and all(type(item) is str for item in blockers)):
                return message + f'｜正式啟用仍有 {len(blockers)} 類獨立驗證缺口'
            return message
    if phase == 'manifest':
        package = details.get('package')
        if package in ('DataPackage', 'MainPackage'):
            return f'正在驗證 {package} Manifest'
    if phase == 'bundle_sync':
        count = details.get('count')
        size = details.get('bytes')
        if type(count) is int and type(size) is int and count >= 0 and size >= 0:
            if count == 0:
                return 'Bundle 已在本機快取，重新校驗中'
            return f'待同步 {count} 個 Bundle，約 {size / (1024 * 1024):.1f} MiB'
    if phase == 'bundle_item':
        done, total = details.get('completed'), details.get('total')
        if (type(done) is int and type(total) is int
                and 0 <= done <= total and total > 0):
            return f'已校驗 {done} / {total} 個必要 Bundle'
    if phase == 'formal_checked':
        status = details.get('status')
        choices = {
            'already_verified': '完整正式資源已安裝並通過交叉驗證',
            'installed_and_verified': '完整正式資源已安全安裝並重新校驗',
            'awaiting_complete_reviewed_archives': '四類資料格式相容；舊式 ZIP 未齊（可改走已驗證 Bundle）',
            'optional_failed': '舊式 ZIP 交叉驗證未通過；官方資源結果仍保留，正式 Bundle 需獨立驗證',
        }
        return choices.get(status, '正式來源仍需獨立驗證')
    if phase == 'extract_failed':
        feature = details.get('feature')
        stage = details.get('stage')
        reviewed = ('UnityFS／TextAsset', 'Eve 二進位事件',
                    'ItemData 二進位表', '資料 Schema',
                    '未分類解包例外', '未分類 Schema 例外')
        if feature in FEATURE_LABELS and stage in reviewed:
            return f'{FEATURE_LABELS[feature]}：{stage} 驗證失敗'
        return '新版官方資源資料格式未通過驗證'
    if phase == 'extract':
        feature = details.get('feature')
        if feature in FEATURE_LABELS:
            return f'正在轉換{FEATURE_LABELS[feature]}'
    return STEP_LABELS.get(phase, '準備 LaLa 資源')


def _format_stage(phase):
    if phase.startswith('server_list_'):
        return '同步官方伺服器清單'
    if phase.startswith('runtime_identity_'):
        return '核對官方版本'
    if phase.startswith('runtime_bundle_'):
        return '準備必要資源'
    if phase in ('raw_rebuild', 'raw_resource_item', 'raw_rebuild_ready',
                 'raw_rebuild_unavailable'):
        return '補建資源清單（官方資源不直接啟用）'
    if phase in ('classification_ready', 'classification_unavailable'):
        return '現有官方資源索引分類'
    if phase == 'bundle_item':
        return f'第 {STEPS.index("bundle_sync") + 1} / {len(STEPS)} 階段'
    if phase == 'cached_official':
        return '已驗證快取，無須重新解包'
    if phase in ('preview_ready', 'download_ready', 'verified_official'):
        return '資源準備結果已確認'
    try:
        return f'第 {STEPS.index(phase) + 1} / {len(STEPS)} 階段'
    except ValueError:
        return '檢查中'



def _progress_counts(phase, details):
    """Only actual item counts authorize a determinate *stage* indicator."""
    if phase not in ('bundle_item', 'raw_resource_item') or not isinstance(details, dict):
        return None
    done, total = details.get('completed'), details.get('total')
    if type(done) is int and type(total) is int and 0 <= done <= total <= 1000000 and total > 0:
        return done, total
    return None


class _ProgressMailbox:
    """One display snapshot, sticky failure and terminal receipt, not a backlog.

    Coalescing affects presentation only. The resource task still performs every
    check. No Tk object is touched by the producer, and errors survive bursts.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._latest = self._failure = self._terminal = None

    def report(self, phase, details):
        if phase not in STEP_LABELS:
            return
        update = (_format_stage(phase), progress_message(phase, details),
                  _progress_counts(phase, details))
        with self._lock:
            self._latest = update
            if phase == 'extract_failed':
                self._failure = update[1]

    def finish(self, result):
        with self._lock:
            self._terminal = (result,)

    def take(self):
        with self._lock:
            snapshot = self._latest, self._failure, self._terminal
            self._latest = self._failure = self._terminal = None
        return snapshot



def _ui_font(root):
    from tkinter import font
    available = set(font.families(root))
    for candidate in ('Microsoft JhengHei UI', 'Microsoft JhengHei',
                      'PingFang TC', 'Noto Sans CJK TC'):
        if candidate in available:
            return candidate
    return font.nametofont('TkDefaultFont', root=root).actual('family')

def _console_prepare(task):
    """Headless environments keep the same workflow without a window."""
    def report(phase, details):
        print('LaLa Launcher｜' + progress_message(phase, details), flush=True)
    return task(progress=report)


def run_with_progress(task):
    """Run a synchronous launch task in a worker, with Tk main-loop feedback.

    The task accepts progress(phase, details) and returns a result dict.
    The window closes only after worker completion. If Tk is unavailable,
    output deterministic textual stages instead of preventing boot.
    """
    if not callable(task):
        raise TypeError('Launcher task must be callable')
    if (os.environ.get('WLRE_DISABLE_AUTO_CATALOG') == '1'
            or (sys.platform.startswith('linux') and not os.environ.get('DISPLAY'))):
        return task() if os.environ.get('WLRE_DISABLE_AUTO_CATALOG') == '1' else _console_prepare(task)
    try:
        import tkinter as tk
        root = tk.Tk()
    except (ImportError, RuntimeError, OSError):
        return _console_prepare(task)
    except Exception as exc:
        if exc.__class__.__name__ == 'TclError':
            return _console_prepare(task)
        raise

    messages = _ProgressMailbox()
    state = {'result': None, 'done': False, 'last_error': None}
    root.title('飄流幻境 RE · LaLa Launcher')
    root.configure(bg=_BG)
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    scale = max(1.0, float(root.tk.call('tk', 'scaling')) / (96 / 72))
    width = min(round(640 * scale), max(480, screen_w - 36))
    height = min(round(376 * scale), max(300, screen_h - 64))
    root.geometry(f'{width}x{height}')
    min_width = min(round(540 * scale), width)
    root.minsize(min_width, min(round(352 * scale), height))
    root.resizable(True, True)
    try:
        root.eval('tk::PlaceWindow . center')
    except tk.TclError:
        pass

    family = _ui_font(root)
    shell = tk.Frame(root, bg=_BG, padx=28, pady=24)
    shell.pack(fill='both', expand=True)
    tk.Label(shell, text='✦  WLRe : LaLa', font=(family, 22, 'bold'),
             bg=_BG, fg=_FG, anchor='w').pack(fill='x')
    tk.Label(shell, text='正在準備官方資源與遊戲資料',
             font=(family, 11), bg=_BG, fg=_MUTED, anchor='w').pack(
                 fill='x', pady=(6, 19))
    panel = tk.Frame(shell, bg=_PANEL, padx=18, pady=17)
    panel.pack(fill='x')
    stage = tk.StringVar(master=root, value='準備檢查')
    detail = tk.StringVar(master=root, value='正在初始化安全資源流程…')
    stage_label = tk.Label(panel, textvariable=stage, font=(family, 12, 'bold'),
             bg=_PANEL, fg=_ACCENT, anchor='w', justify='left',
             wraplength=max(240, width - 115))
    stage_label.pack(fill='x')
    detail_label = tk.Label(
        panel, textvariable=detail, font=(family, 11),
        bg=_PANEL, fg=_FG, anchor='w', justify='left',
        wraplength=max(300, width - 115))
    detail_label.pack(fill='x', pady=(9, 14))
    count_text = tk.StringVar(master=root, value='處理中 · 目前階段尚無總量')
    count_label = tk.Label(panel, textvariable=count_text, font=(family, 9),
                           bg=_PANEL, fg=_MUTED, anchor='w', justify='left',
                           wraplength=max(240, width - 115))
    count_label.pack(fill='x')
    progress = _CyanProgress(panel, tk)
    footer = tk.StringVar(master=root, value='資源準備不代表已可登入；主程式仍會獨立驗證。')
    footer_label = tk.Label(shell, textvariable=footer, font=(family, 9),
                            bg=_BG, fg=_MUTED, anchor='w', justify='left',
                            wraplength=max(300, width - 95))
    footer_label.pack(fill='x', pady=(16, 0))

    fit_pending = [None]

    def fit_content():
        # Keep the guard while Tk settles wrapped-label geometry.
        fit_pending[0] = 'running'
        root.update_idletasks()
        # Font scaling and multi-line stages must not pack the bar/footer away.
        required = min(shell.winfo_reqheight(), max(300, screen_h - 64))
        root.minsize(min_width, max(min(round(352 * scale), height), required))
        if root.winfo_height() < required:
            root.geometry(f'{root.winfo_width()}x{required}')
        fit_pending[0] = None

    def schedule_fit():
        if fit_pending[0] is None:
            fit_pending[0] = root.after_idle(fit_content)

    last_width = [None]

    def resize_text(event):
        if event.widget is root and event.width != last_width[0]:
            last_width[0] = event.width
            count_label.configure(wraplength=max(240, event.width - 115))
            stage_label.configure(wraplength=max(240, event.width - 115))
            detail_label.configure(wraplength=max(240, event.width - 115))
            footer_label.configure(wraplength=max(240, event.width - 95))
            schedule_fit()
    root.bind('<Configure>', resize_text, add='+')
    schedule_fit()

    # Closing the window does not abandon a write or leave an untracked
    # downloader modifying the user's private cache.
    root.protocol('WM_DELETE_WINDOW',
                  lambda: footer.set('正在安全完成目前的資源步驟；結束後會進入 LaLa。'))

    def worker():
        try:
            result = task(progress=messages.report)
        except Exception:
            result = {'status': 'error', 'assets_ready': False,
                      'can_send_packets': False}
        messages.finish(result)

    thread = threading.Thread(target=worker, name='lala-launcher-resource',
                              daemon=True)
    thread.start()

    def pump():
        update, failure, terminal = messages.take()
        if failure is not None:
            state['last_error'] = failure
        if update is not None:
            title, message, counts = update
            stage.set(title)
            detail.set(message)
            progress.set_counts(counts)
            count_text.set(f'本階段 {counts[0]} / {counts[1]} 份' if counts else
                           '處理中 · 目前階段尚無總量')
        if terminal is not None:
            state['done'] = True
            state['result'] = terminal[0]
            progress.stop()
        schedule_fit()
        if state['done']:
            receipt = state['result'] or {}
            if receipt.get('status') == 'verified_official':
                stage.set('資源準備完成')
                count_text.set('準備開啟 LaLa')
                detail.set('官方資源快取已建立或校驗完成，等待遊戲相容性審核。')
                footer.set('現在開啟 LaLa 主程式，由官方版本安全檢查決定登入。')
                root.after(700, root.quit)
            else:
                stage.set('資源尚未完成 · 將開啟 LaLa')
                stage_label.configure(fg=_WARNING)
                count_text.set('主程式將再次檢查，尚未授予登入權限')
                detail.set(state['last_error'] or
                           '官方資源準備未完成；主程式仍會獨立檢查官方遊戲版本。')
                footer.set('官方資源資料未啟用；原有登入安全檢查仍有效。')
                root.after(1100, root.quit)
        else:
            root.after(_POLL_MS, pump)

    root.after(_POLL_MS, pump)
    try:
        root.mainloop()
    finally:
        progress.stop()
        if fit_pending[0] is not None:
            root.after_cancel(fit_pending[0])
        root.destroy()
        thread.join(timeout=1)
    return state['result']
