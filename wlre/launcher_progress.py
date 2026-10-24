"""A compact LaLa launcher splash with *real* official sync stages.

This window is created, updated and destroyed only on Tk's main thread.
The resource worker never references the window. It sends bounded event data
through a queue; completed/failed preparation never grants login permission.
"""
from __future__ import annotations

import os
import queue
import sys
import threading

STEPS = (
    'official_version', 'manifest', 'bundle_plan', 'bundle_sync',
    'bundle_verify', 'extract', 'candidate_write',
)
FEATURE_LABELS = {
    'npc': 'NPC 事件', 'shops': '商店與物品',
    'crafting': '製作配方', 'scenes': '場景資料',
}
STEP_LABELS = {
    'official_version': '檢查官方版本',
    'manifest': '讀取並驗證 Manifest',
    'bundle_plan': '分析資源位置與相依',
    'bundle_sync': '下載並校驗必要 Bundle',
    'bundle_item': '逐個驗證 Bundle 完整性',
    'bundle_verify': '重新核對 Bundle 完整性',
    'extract': '解包並驗證遊戲資料',
    'candidate_write': '建立版本化私人快取',
    'compatibility_check': '核對四類資料的相容性',
    'compatibility_ready': '資料格式檢查通過，協定仍待驗證',
    'cached_candidate': '已使用驗證過的私人候選快取',
    'preview_ready': '資源預覽完成',
    'download_ready': 'Bundle 同步完成',
    'candidate_ready': '候選資料已建立',
    'extract_failed': '候選資料解析失敗',
}
_BG = '#101927'
_PANEL = '#172539'
_FG = '#eef6ff'
_MUTED = '#a6b9cc'
_ACCENT = '#56c8e9'


def progress_message(phase, details=None):
    """Convert whitelisted stage data into a short human-readable message."""
    details = details if isinstance(details, dict) else {}
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
    if phase == 'extract_failed':
        feature = details.get('feature')
        stage = details.get('stage')
        reviewed = ('UnityFS／TextAsset', 'Eve 二進位事件',
                    'ItemData 二進位表', '資料 Schema',
                    '未分類解包例外', '未分類 Schema 例外')
        if feature in FEATURE_LABELS and stage in reviewed:
            return f'{FEATURE_LABELS[feature]}：{stage} 驗證失敗'
        return '新版候選資料格式未通過驗證'
    if phase == 'extract':
        feature = details.get('feature')
        if feature in FEATURE_LABELS:
            return f'正在轉換{FEATURE_LABELS[feature]}'
    return STEP_LABELS.get(phase, '準備 LaLa 資源')


def _format_stage(phase):
    if phase == 'bundle_item':
        return f'第 {STEPS.index("bundle_sync") + 1} / {len(STEPS)} 階段'
    if phase == 'cached_candidate':
        return '已驗證快取，無須重新解包'
    if phase in ('preview_ready', 'download_ready', 'candidate_ready'):
        return '資源準備結果已確認'
    try:
        return f'第 {STEPS.index(phase) + 1} / {len(STEPS)} 階段'
    except ValueError:
        return '檢查中'


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
        from tkinter import ttk
        root = tk.Tk()
    except (ImportError, RuntimeError, OSError):
        return _console_prepare(task)
    except Exception as exc:
        if exc.__class__.__name__ == 'TclError':
            return _console_prepare(task)
        raise

    messages = queue.Queue()
    state = {'result': None, 'done': False, 'last_error': None}
    root.title('飄流幻境 RE · LaLa Launcher')
    root.configure(bg=_BG)
    root.geometry('520x286')
    root.minsize(480, 270)
    root.resizable(False, False)
    try:
        root.eval('tk::PlaceWindow . center')
    except tk.TclError:
        pass

    shell = tk.Frame(root, bg=_BG, padx=25, pady=22)
    shell.pack(fill='both', expand=True)
    tk.Label(shell, text='✦  WLRe : LaLa', font=('Arial', 20, 'bold'),
             bg=_BG, fg=_FG, anchor='w').pack(fill='x')
    tk.Label(shell, text='正在準備官方資源與遊戲資料',
             font=('Arial', 11), bg=_BG, fg=_MUTED, anchor='w').pack(
                 fill='x', pady=(5, 17))
    panel = tk.Frame(shell, bg=_PANEL, padx=15, pady=15)
    panel.pack(fill='x')
    stage = tk.StringVar(master=root, value='準備檢查')
    detail = tk.StringVar(master=root, value='正在初始化安全資源流程…')
    tk.Label(panel, textvariable=stage, font=('Arial', 10, 'bold'),
             bg=_PANEL, fg=_ACCENT, anchor='w').pack(fill='x')
    tk.Label(panel, textvariable=detail, font=('Arial', 11),
             bg=_PANEL, fg=_FG, anchor='w', wraplength=445).pack(
                 fill='x', pady=(8, 11))
    style = ttk.Style(root)
    style.configure('LaLa.Launcher.Horizontal.TProgressbar',
                    troughcolor='#293c50', background=_ACCENT,
                    bordercolor='#293c50', lightcolor=_ACCENT,
                    darkcolor=_ACCENT)
    progress = ttk.Progressbar(panel, mode='indeterminate',
                              style='LaLa.Launcher.Horizontal.TProgressbar')
    progress.pack(fill='x')
    progress.start(15)
    footer = tk.StringVar(master=root, value='版本與資源先行驗證，登入權限仍由主程式判定。')
    tk.Label(shell, textvariable=footer, font=('Arial', 9),
             bg=_BG, fg=_MUTED, anchor='w', wraplength=470).pack(
                 fill='x', pady=(13, 0))

    # Closing the window does not abandon a write or leave an untracked
    # downloader modifying the user's private cache.
    root.protocol('WM_DELETE_WINDOW',
                  lambda: footer.set('正在安全完成目前的資源步驟；結束後會進入 LaLa。'))

    def report(phase, info):
        if phase in STEP_LABELS:
            messages.put(('stage', phase, info))

    def worker():
        try:
            result = task(progress=report)
            messages.put(('done', result, None))
        except Exception as exc:
            messages.put(('error', None, type(exc).__name__))

    thread = threading.Thread(target=worker, name='lala-launcher-resource',
                              daemon=True)
    thread.start()

    def pump():
        while True:
            try:
                kind, arg, extra = messages.get_nowait()
            except queue.Empty:
                break
            if kind == 'stage':
                stage.set(_format_stage(arg))
                detail.set(progress_message(arg, extra))
                if arg == 'extract_failed':
                    state['last_error'] = progress_message(arg, extra)
                if arg == 'bundle_item' and isinstance(extra, dict):
                    done, total = extra.get('completed'), extra.get('total')
                    if (type(done) is int and type(total) is int
                            and 0 <= done <= total and total > 0):
                        progress.stop()
                        progress.configure(mode='determinate', maximum=total, value=done)
                elif progress.cget('mode') == 'determinate':
                    progress.configure(mode='indeterminate')
                    progress.start(15)
            else:
                state['done'] = True
                state['result'] = arg if kind == 'done' else {
                    'status': 'error', 'assets_ready': False,
                    'can_send_packets': False}
                if kind == 'error':
                    detail.set('資源準備未完成，仍維持原有登入限制')
                progress.stop()
                break
        if state['done']:
            receipt = state['result'] or {}
            if receipt.get('status') == 'review_required':
                stage.set('Launcher 資料準備已完成')
                detail.set('候選快取已建立或校驗完成，等待遊戲相容性審核。')
                footer.set('現在開啟 LaLa 主程式，由官方版本安全檢查決定登入。')
                root.after(700, root.quit)
            else:
                stage.set('Launcher 將繼續開啟 LaLa')
                detail.set(state['last_error'] or
                           '候選資源未完成；主程式仍會獨立檢查官方遊戲版本。')
                footer.set('候選資料未啟用；原有登入安全檢查仍有效。')
                root.after(1100, root.quit)
        else:
            root.after(80, pump)

    root.after(80, pump)
    try:
        root.mainloop()
    finally:
        root.destroy()
        thread.join(timeout=1)
    return state['result']
