"""Reusable verified instance catalog widgets and create selection logic.

The same catalog UI serves normal dungeons and co-op; catalog data stays
read-only, and creating a room still requires the existing guarded dialog.
"""
import tkinter as tk
from tkinter import ttk


def build_instance_catalog(page, cooperative):
    """Preserve original widget identity, heights, layout and selection binding."""
        page.catalog_heading = ttk.Label(
            page.catalog_column, text="1262 官方副本清單（選擇後建立房間）",
            style='Muted.TLabel')
        page.catalog_heading.pack(anchor='w', pady=(0, 3))
        page.catalog_columns = ('id', 'name', 'level', 'players', 'time')
        catalog_host = ttk.Frame(page.catalog_column)
        catalog_host.pack(fill='both', expand=True, pady=(0, 4))
        page.catalog_table = ttk.Treeview(
            catalog_host, columns=page.catalog_columns,
            show='headings', selectmode='browse',
            height=6 if cooperative else 8)
        for field, title, width in (
            ('id', 'ID', 48), ('name', '官方中文名稱／版本', 210),
            ('level', '等級', 66), ('players', '人數', 76),
            ('time', '時間', 80)
        ):
            page.catalog_table.heading(field, text=title)
            page.catalog_table.column(field, width=width, anchor='w', stretch=True)
        scroll = ttk.Scrollbar(catalog_host, orient='vertical',
                               command=page.catalog_table.yview)
        page.catalog_table.configure(yscrollcommand=scroll.set)
        page.catalog_table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        for index, record in enumerate(page.catalog_records):
            variant = (' (版本 %s)' % record['variant']) if record['variant'] else ''
            members = ('%s～%s' % (record['min_members'], record['max_members'])
                       if record['max_members'] else '依活動')
            duration = ('%s 分' % record['time_minutes']
                        if record['time_minutes'] else '依活動')
            page.catalog_table.insert('', 'end', iid='catalog_%s' % index,
                values=(record['id'], record['name'] + variant,
                        record['min_level'] or '依活動', members, duration))
        page.catalog_detail = tk.StringVar(value='點選官方副本名稱可查看來源 ID 與獎勵資料筆數。')
        ttk.Label(page.catalog_column, textvariable=page.catalog_detail,
                  style='Muted.TLabel',wraplength=530).pack(fill='x', pady=(0, 5))
        page.catalog_table.bind('<<TreeviewSelect>>', page.on_catalog_selected)


class InstanceCatalogMixin:
    """Keep existing InstanceModePage catalog callbacks available by inheritance."""

    def on_catalog_selected(self, _event=None):
        selection = self.catalog_table.selection()
        if not selection:
            return
        index = int(selection[0].removeprefix('catalog_'))
        record = self.catalog_records[index]
        self._update_create_button()
        self.catalog_detail.set(
            '副本 ID %s｜場景 %s｜獎勵資料 %s 筆；是否可進入仍以伺服器為準' %
            (record['id'], record['map_id'], len(record['awards'])))

    def _selected_catalog(self):
        selected = self.catalog_table.selection()
        if not selected:
            return None
        try:
            index = int(selected[0].removeprefix('catalog_'))
            return self.catalog_records[index]
        except (ValueError, IndexError):
            return None

    def _update_create_button(self):
        record = self._selected_catalog()
        eligible = (self._creation_ready and record is not None
                    and record['kind'] in (1, 2))
        self.create_button.state(['!disabled'] if eligible else ['disabled'])
        if record is None:
            self.creation_hint.set('建立房間：請先點選官方副本清單的項目')
        elif record['kind'] not in (1, 2):
            self.creation_hint.set('此副本種類尚不支援建立房間')
        elif eligible:
            self.creation_hint.set('已選「%s」，可以建立公開／私人房間' % record['name'])
        else:
            reasons = self._creation_block_reasons
            reason = '；'.join(reasons[:2]) if reasons else '請等待伺服器同步並檢查角色狀態'
            if len(reasons) > 2:
                reason += '（另有 %d 項限制）' % (len(reasons) - 2)
            self.creation_hint.set('無法建立「%s」：%s' % (record['name'], reason))

