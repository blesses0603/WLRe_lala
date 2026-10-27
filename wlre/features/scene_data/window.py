"""官方場景欄位唯讀頁；不建立背景工作、計時器或遊戲指令。"""
import re
import tkinter as tk
from tkinter import ttk

from wlre.resources_runtime.official.contracts import ResourceStatus
from wlre.ui.resource_lifetime import install_root_lifetime
from wlre.ui.window_layout import configure_dialog

FIELD_LABELS = {
    'name': '場景名稱', 'model_manifest': '模型資產索引', 'map_dimensions': '地圖尺寸定義',
    'model_content': '模型內容', 'map_image': '地圖圖像', 'coordinate_mapping': '座標轉換',
    'teleport_destination': '傳點目的地與條件', 'walkable_grid': '官方掃描網格',
    'dynamic_obstacles': '即時動態障礙',
}
STATUS_LABELS = {ResourceStatus.VALID: '已核對', ResourceStatus.UNKNOWN: '尚未驗證',
                 ResourceStatus.MISSING: '未提供', ResourceStatus.INVALID: '資料不符',
                 ResourceStatus.UNSUPPORTED: '尚未支援'}
PHASE_LABELS = {
    'idle': '尚未查詢官方場景資料', 'refreshing': '正在核對官方資料…',
    'current': '本次資料已核對；各欄位缺口請見下表',
    'failed': '官方資料更新失敗；先前快取不視為目前資料',
    'cancel_requested': '正在取消更新…', 'cancelled': '更新已取消；目前沒有可用查詢',
}
FAILURE_LABELS = {
    'official_resource_gaps': '必要官方資產缺失或格式尚未支援',
    'official_resource_incompatible': '官方資料結構與已支援格式不符',
    'official_resource_extract_failed': '官方資產容器或內容無法通過驗證',
    'official_versions_changed_during_refresh': '更新期間官方版本已改變，請重新核對',
    'official_manifest_changed_during_refresh': '更新期間官方資產清單已改變，請重新核對',
    'official_bundle_cache_changed': '資產快取完整性已改變，請重新核對',
    'official_manifest_cache_changed': '資產清單快取完整性已改變，請重新核對',
}
PAGE_SIZE = 100


class SceneDataWindow(tk.Toplevel):
    def __init__(self, parent, controller, *, exe_version=''):
        super().__init__(parent)
        install_root_lifetime(self._root())
        self.controller = controller
        self.title('官方場景資料 · 唯讀核對')
        self._glass_background_dim = 0.79
        configure_dialog(self, 1000, 660)
        self._rows, self._filtered, self._page = (), (), 0
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)
        self.phase = tk.StringVar(self, value=PHASE_LABELS['idle'])
        self.source = tk.StringVar(self, value='尚未確認版本與來源；不會自動讀取舊版資料')
        ttk.Label(body, textvariable=self.phase, style='Heading.TLabel').pack(fill='x')
        ttk.Label(body, textvariable=self.source, wraplength=940).pack(fill='x', pady=(4, 8))
        controls = ttk.Frame(body)
        controls.pack(fill='x')
        ttk.Label(controls, text='官方客戶端版本').pack(side='left')
        self.exe_version = tk.StringVar(self, value=exe_version)
        self.version_entry = ttk.Entry(controls, textvariable=self.exe_version, width=12)
        self.version_entry.pack(side='left', padx=6)
        self.refresh_button = ttk.Button(controls, text='核對官方資料', command=self.refresh)
        self.refresh_button.pack(side='left')
        self.cancel_button = ttk.Button(controls, text='取消更新', command=controller.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=6)
        ttk.Label(controls, text='搜尋').pack(side='left', padx=(12, 4))
        self.search = tk.StringVar(self)
        entry = ttk.Entry(controls, textvariable=self.search, width=20)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<KeyRelease>', lambda event: self.filter_rows())
        self.summary = tk.StringVar(self, value='')
        ttk.Label(body, textvariable=self.summary, wraplength=940).pack(fill='x', pady=8)
        table = ttk.Frame(body)
        self.tree = ttk.Treeview(table, columns=('id', 'name', 'dimensions', 'model', 'status'),
                                 show='headings', height=8, selectmode='browse')
        for key, label, width in zip(('id', 'name', 'dimensions', 'model', 'status'),
                                    ('場景 ID', '官方名稱', '尺寸定義', '模型 ID', '圖像／導航資料'),
                                    (85, 240, 150, 100, 330), strict=True):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=width, stretch=False)
        bar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        # 即使沒有安裝主題，仍不允許使用者拖動欄位分隔線。
        self.tree.bind('<Button-1>', self._lock_separator, add='+')
        self.tree.bind('<Double-Button-1>', self._lock_separator, add='+')
        pages = ttk.Frame(body)
        self.previous = ttk.Button(pages, text='上一頁', command=lambda: self.turn(-1))
        self.previous.pack(side='left')
        self.page_text = tk.StringVar(self, value='0 筆')
        ttk.Label(pages, textvariable=self.page_text).pack(side='left', padx=12)
        self.next = ttk.Button(pages, text='下一頁', command=lambda: self.turn(1))
        self.next.pack(side='left')
        self.detail = tk.StringVar(self, value='選取場景查看各欄位的核對狀態')
        self.detail_label = ttk.Label(body, textvariable=self.detail, wraplength=940, justify='left')
        self.footer_label = ttk.Label(
            body, text='目前僅核對名稱、資產索引與尺寸；圖像、傳點與導航另行驗證。',
            style='Muted.TLabel', wraplength=940)
        # 固定操作／詳情先保留空間，表格承接其餘高度，避免較矮螢幕截掉頁尾。
        self.footer_label.pack(side='bottom', fill='x')
        self.detail_label.pack(side='bottom', fill='x', pady=5)
        pages.pack(side='bottom', fill='x', pady=5)
        table.pack(fill='both', expand=True)
        self._show_page()

    def _lock_separator(self, event):
        if self.tree.identify_region(event.x, event.y) == 'separator':
            return 'break'
        return None

    def refresh(self):
        version = self.exe_version.get().strip()
        if not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', version):
            self.phase.set('請輸入完整官方客戶端版本，例如主程式版本檢測顯示的版本')
            return
        try:
            self.controller.refresh(version)
        except (ValueError, RuntimeError):
            self.phase.set('目前無法開始查詢，請等待現有工作完成後重試')

    def render(self, status, service):
        active = (status.phase in ('refreshing', 'cancel_requested') or status.workers > 0
                  or getattr(status, 'notification_pending', False))
        self.refresh_button.configure(state='disabled' if active else 'normal')
        self.version_entry.configure(state='disabled' if active else 'normal')
        self.cancel_button.configure(state='normal' if active else 'disabled')
        self.phase.set(PHASE_LABELS.get(status.phase, '資料服務不可用'))
        if status.phase == 'failed':
            reason = FAILURE_LABELS.get(getattr(status, 'code', ''), '官方連線、讀取或完整性檢查未完成')
            self.phase.set(f'{reason}；先前快取不視為目前資料')
        if service is None:
            self._rows = ()
            self.source.set('目前沒有已核對資料；舊快取只供診斷，不作為目前官方資料')
            self.summary.set('')
        else:
            self._rows = service.scene_assessments()
            versions = service.versions
            self.source.set(f'客戶端 {versions.observed_exe_version}｜資料 {versions.data_version}\n'
                            f'DataPackage {versions.data_package_version}｜MainPackage {versions.main_package_version}\n'
                            f'核對時間 {service.validated_at}')
            summary = service.scene_field_summary()
            self.summary.set(f"場景 {summary['scene_count']} 筆｜名稱已核對 {summary['label_ready_count']} 筆｜"
                             f"新管線圖像驗收 {summary['map_ready_count']} 筆｜導航驗收 {summary['navigation_ready_count']} 筆")
        self.filter_rows()

    def filter_rows(self):
        query = self.search.get().strip().casefold()
        self._filtered = tuple(row for row in self._rows if not query or
                               query in str(row.scene_id) or query in (row.name or '').casefold())
        self._page = 0
        self._show_page()

    def turn(self, delta):
        last = max(0, (len(self._filtered) - 1) // PAGE_SIZE)
        self._page = min(last, max(0, self._page + delta))
        self._show_page()

    def _show_page(self):
        self.tree.delete(*self.tree.get_children())
        start = self._page * PAGE_SIZE
        for row in self._filtered[start:start + PAGE_SIZE]:
            self.tree.insert('', 'end', iid=str(row.scene_id), values=(
                row.scene_id, row.name or '名稱未提供', f'{row.map_width} × {row.map_height}',
                row.model_id, '尚有資料缺口' if not row.map_ready else '僅供唯讀顯示'))
        count = len(self._filtered)
        self.page_text.set(f'{start + 1 if count else 0}–{min(start + PAGE_SIZE, count)}／{count} 筆')
        self.previous.configure(state='normal' if self._page else 'disabled')
        self.next.configure(state='normal' if start + PAGE_SIZE < count else 'disabled')
        self.detail.set('選取場景查看各欄位的核對狀態')

    def select(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        row = next(row for row in self._filtered if str(row.scene_id) == selection[0])
        labels = []
        for field in row.fields:
            label = STATUS_LABELS[field.status]
            if field.status is ResourceStatus.VALID and field.field == 'model_manifest':
                label = '僅資產索引已核對'
            labels.append(f'{FIELD_LABELS[field.field]}：{label}')
        self.detail.set(f'場景 {row.scene_id}｜{row.name or "名稱未提供"}\n' +
                        '\n'.join('　｜　'.join(labels[index:index + 3]) for index in range(0, len(labels), 3)))
