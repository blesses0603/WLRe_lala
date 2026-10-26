"""Portal controls, navigation guards and review panel.

Original user confirmation/destination validation remain in the existing
feature callbacks, while underlying world services remain authoritative.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from wlre.paths import PROJECT_ROOT
from wlre.ui.window_layout import configure_dialog
from wlre.services.world.portal_policy import destination_problem
from wlre.services.world.portals import portal_map_pixel, portal_source_diagnostic


class PortalInteractionMixin:
    def update_portal_button(self):
        p=self.selected_portal
        enabled=bool(p and destination_problem(p,self.maps) is None and p.get('direct_eligible') and self.state.get('player',{}).get('scene')==self.selected_id and not self.state.get('battle',{}).get('active') and not self.state.get('event_flow',{}).get('blocked'))
        if p and p.get('source_revision') == 1275:
            enabled = enabled and portal_map_pixel(
                p, getattr(self, 'projection', None)) is not None
        label = ('手動確認換圖' if enabled and p.get('source_revision') == 1275
                 else '目的地待核對' if p and p.get('source_revision') == 1275
                 else '返回有圖地圖' if self.image is None else '直接嘗試換圖')
        if p and p.get('source_revision') == 1275 and not enabled and p.get('destination_verified'):
            if not p.get('coordinate_valid') or portal_map_pixel(p, getattr(self, 'projection', None)) is None:
                label = '點位待核對'
            elif not self.maps.has_image(p['destination']):
                label = '目的地無地圖'
            elif self.state.get('player',{}).get('scene') != self.selected_id:
                label = '非目前地圖'
            else:
                label = '目前無法換圖'
        self.portal_go.configure(state='normal' if enabled else 'disabled',
                                 text=label)

    def choose_portal(self,event=None):
        selected=self.portal_list.curselection()
        if not selected or selected[0]>=len(self.list_rows):return
        p=self.list_rows[selected[0]]
        self.select_portal(p)

    def select_portal(self,p):
        self.selected_npc=None
        self.npc_list.selection_clear(0,'end')
        self.selected_portal=p
        self.portal_list.selection_clear(0,'end')
        self.portal_list.selection_set(self.list_rows.index(p))
        self.portal_list.see(self.list_rows.index(p))
        self.portal_status.set(p['name']+'｜'+p.get('direct_note','尚未核對觸碰事件'))
        self.update_portal_button()
        if (p.get('source_revision') == 1275 and self.on_pick is not None):
            # Selecting a list row is NOT proof that Eve.NewDoor grid XY
            # can be used as a packet-space destination. Recheck projection
            # before updating the navigation target (never auto-move).
            point = portal_map_pixel(p, getattr(self, 'projection', None))
            if point is not None:
                self.on_pick(self.selected_id, p['x'], p['y'])
            elif not p.get('coordinate_valid'):
                self.portal_status.set(
                    p['name'] + '｜傳點位置尚未通過官方座標換算，'
                    '已停用選點與換圖')
            else:
                self.portal_status.set(
                    p['name'] + '｜轉換後位置超出目前小地圖範圍，'
                    '已停用選點')
        self.draw()

    def go_portal(self):
        if not self.selected_portal:return False
        try:
            if self.state.get('battle', {}).get('active'):
                raise ValueError('戰鬥中無法換圖。')
            if self.state.get('event_flow', {}).get('blocked'):
                raise ValueError('伺服器事件尚未結束，暫不能換圖。')
            problem=destination_problem(self.selected_portal,self.maps)
            if problem:raise ValueError(problem)
            self.portals.direct_target(self.selected_portal,self.state.get('player',{}).get('scene'))
            if (self.selected_portal.get('source_revision') == 1275
                    and hasattr(self, 'projection')
                    and portal_map_pixel(
                        self.selected_portal, self.projection) is None):
                raise ValueError('傳點座標未通過目前地圖投影校驗，禁止換圖。')
            if self.on_portal is None:
                raise ValueError('尚未接上本機角色的出口觸發功能。')
            self.on_portal(self.selected_portal['id'])
            return True
        except ValueError as exc:
            self.portal_status.set(str(exc));return False

    def show_audit(self):
        if self.audit_window and self.audit_window.winfo_exists():
            self.audit_window.lift();return
        if self.portals.data.get('source_revision') == 1275:
            # A 1262 historical review must never be presented as current
            # destination or trigger verification for 1275.
            win = tk.Toplevel(self)
            self.audit_window = win
            win.title('1275 官方門事件（位置預覽）')
            configure_dialog(win, 730, 460)
            win.resizable(False, False)
            ttk.Label(win, text='1275 Eve 門事件來源已核對。'
                      '僅三份同版官方表成功交叉匹配者可單次手動試傳；'
                      '其餘停用，實際換圖須以伺服器回覆為準，不引用 1262 舊報告。',
                      wraplength=680).pack(fill='x', padx=10, pady=8)
            status = portal_source_diagnostic(
                self.portals.data.get('portal_metadata_status'))
            ttk.Label(win, text='傳點名稱／位置資料：' + status,
                      wraplength=680).pack(fill='x', padx=10)
            ttk.Button(win, text='全場景核對', command=self.show_all_portal_coverage).pack(
                anchor='e', padx=10, pady=4)
            # Data-format recognition is NOT equivalent to official server
            # transfer validation. Display concise verified source evidence.
            schema_report = self.portals.data.get('portal_schema_report', {})
            if isinstance(schema_report, dict):
                formats = []
                for table in ('StageMapData_C', 'EveDoorLinks'):
                    report = schema_report.get(table)
                    if not isinstance(report, dict):
                        formats.append(table + '：來源未取得')
                    elif report.get('status') == 'recognized':
                        formats.append(table + '：結構相容')
                    else:
                        # Recognizer hints are fixed text; unknown reports get
                        # a generic message rather than exposing raw payloads.
                        hints = {
                            'scene_header_unrecognized': '場景標頭未辨識',
                            'scene_header_invalid': '場景標頭重複或編號無效',
                            'link_fields_unrecognized': '連線行方括號欄位不符',
                            'link_value_invalid': '座標或目的地欄位格式不符',
                            'encoding_invalid': 'UTF-16LE 編碼不符',
                            'record_length_mismatch': '表頭筆數與記錄長度不符',
                            'source_length_invalid': '來源長度或型別不符',
                            'value_out_of_range': '編號或座標超出範圍',
                        }
                        formats.append(table + '：' + hints.get(
                            report.get('reason_code'), '版型待重新核對'))
                ttk.Label(win, text='1262 欄位格式比對：' + '／'.join(formats),
                          wraplength=680).pack(fill='x', padx=10)
            if not self.portals.data.get('source_ready'):
                ttk.Label(win, text='1275 官方資源尚未完成安裝／校驗，請重新登入。',
                          wraplength=680).pack(fill='x', padx=10)
            frame = ttk.Frame(win)
            frame.pack(fill='both', expand=True, padx=10, pady=8)
            cols = ('index', 'x', 'y', 'status')
            tree = ttk.Treeview(frame, columns=cols, show='headings')
            for key, label, width in (
                ('index', '門事件索引', 110), ('x', 'X', 100),
                ('y', 'Y', 100), ('status', '驗證情況', 360),
            ):
                tree.heading(key, text=label)
                tree.column(key, width=width, anchor='w')
            scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            tree.pack(side='left', fill='both', expand=True)
            for row in self.portals.for_scene(self.selected_id):
                tree.insert('', 'end', values=(
                    row['index'], row['x'] if row['coordinate_valid'] else '無效',
                    row['y'] if row['coordinate_valid'] else '無效',
                    ('目的地：' + row['destination_label'] + '；可手動單次試傳，伺服器回覆為準'
                     if row.get('direct_eligible') else
                     '位置可參考；目的地與觸發未驗證')
                    if row['coordinate_valid'] else '座標未確認；禁止傳送'))
            return
        win=tk.Toplevel(self);self.audit_window=win
        win.title('地圖傳送點逐圖核對 · 1262');configure_dialog(win,1000,600);win.resizable(False,False)
        ttk.Label(win,text='已核對數量只代表門編號與觸碰事件有效，正式服是否允許遠距觸發仍待實測。').pack(fill='x',padx=10,pady=8)
        def open_report():
            import webbrowser
            webbrowser.open((PROJECT_ROOT/'docs/Portal_Review_1262.html').as_uri())
        ttk.Button(win,text='開啟完整逐筆核對報告',command=open_report).pack(anchor='e',padx=10,pady=(0,6))
        body=ttk.Frame(win);body.pack(fill='both',expand=True,padx=10)
        cols=('scene','name','count','normal','event','nav','status')
        tree=ttk.Treeview(body,columns=cols,show='headings')
        for c,label,w in zip(cols,('地圖ID','名稱','傳點數','一般出口','事件入口','可直接嘗試','核對結果'),(65,165,65,70,70,100,290)):
            tree.heading(c,text=label);tree.column(c,width=w,minwidth=45)
        bar=ttk.Scrollbar(body,orient='vertical',command=tree.yview);bar.pack(side='right',fill='y')
        tree.configure(yscrollcommand=bar.set);tree.pack(fill='both',expand=True)
        for row in self.portals.audit.values():
            tree.insert('', 'end',iid=str(row['scene']),values=(row['scene'],row['name'],row['count'],row['normal'],row['event'],row.get('direct_ready',0),row['status']))

    def show_all_portal_coverage(self):
        """Display every scene from the authenticated source audit, not UI filters."""
        report = self.portals.data.get('portal_coverage', {})
        win = tk.Toplevel(self)
        win.title('1275 全場景傳點核對')
        configure_dialog(win, 980, 620)
        ready = report.get('all_sources_available') is True
        text = (f"已核對 {report.get('scene_count', 0)} 個場景；"
                f"{report.get('unresolved_portals', 0)} 個一般傳點仍有來源對應缺口。"
                if ready else '官方門索引、名稱標記或連線來源不完整，尚不能宣稱全場景已核對。')
        if ready:
            text += (f"｜官方 EveDoorLinks 已解析 "
                     f"{report.get('official_link_reference_count', 0)} 筆"
                     f"（來源座標 {report.get('reference_source_xy_count', 0)}、"
                     f"目的地落點 {report.get('reference_arrival_xy_count', 0)} 筆已換算）。"
                     f"另有 {report.get('door_link_data_route_count', 0)} 筆"
                     f" DoorLinkData_C 獨立路線參考；"
                     f"隱藏傳點 {report.get('stage_hidden_marker_count', 0)} 筆，"
                     f"跨場景標記 {report.get('stage_cross_scene_marker_count', 0)} 筆；"
                     "皆不授權傳送。")
        ttk.Label(win, text=text, wraplength=930).pack(fill='x', padx=10, pady=8)
        detail = tk.StringVar(value='選擇場景查看所有門索引與未完成項目；此視窗不送出換圖指令。')
        ttk.Label(win, textvariable=detail, wraplength=930).pack(fill='x', padx=10, pady=4)
        body = ttk.Frame(win)
        body.pack(fill='both', expand=True, padx=10, pady=8)
        columns = ('scene', 'name', 'events', 'portals', 'gaps', 'source')
        table = ttk.Treeview(body, columns=columns, show='headings')
        for key, title, width in zip(columns,
                ('場景', '官方名稱', '門事件數', '一般傳點數', '待核對數', '來源'),
                (80, 260, 100, 110, 110, 210)):
            table.heading(key, text=title)
            table.column(key, width=width, stretch=False)
        bar = ttk.Scrollbar(body, orient='vertical', command=table.yview)
        bar.pack(side='right', fill='y')
        table.configure(yscrollcommand=bar.set)
        table.pack(fill='both', expand=True)
        reasons = {'duplicate_stage_marker': '重複標記索引', 'missing_stage_marker': '缺少標記',
                   'missing_eve_door': '缺少門事件', 'duplicate_eve_door': '重複門事件索引',
                   'missing_door_link': '缺少門連線', 'unknown_destination_scene': '目的場景不在官方表',
                   'position_unverified': '座標待核對', 'destination_unverified': '目的地待核對'}
        rows = {str(row['scene']): row for row in report.get('scenes', [])}
        for key, row in rows.items():
            name = self.portals.data.get('scene_names', {}).get(row['scene'], '名稱未取得')
            table.insert('', 'end', iid=key, values=(row['scene'], name, row['eve_doors'],
                row['ordinary_portals'], row['unresolved'],
                '官方場景表' if row['in_scene_table'] else '表外引用，待核對'))
        def selected(event=None):
            selection = table.selection()
            if not selection: return
            row = rows[selection[0]]
            parts = []
            for door in row['details']:
                labels = [reasons.get(reason, '來源待核對') for reason in door['issues']]
                if not labels:
                    labels = [{'hidden_portal': '隱藏傳點，獨立規則',
                               'event_container_only': '事件容器，未列為地圖出口',
                               'source_incomplete': '來源未齊'}.get(door['category'], '來源對應通過')]
                route_text = ''
                if door.get('reference_only'):
                    target = door.get('official_link_destination')
                    point = door.get('official_link_position')
                    arrival = door.get('official_arrival_position')
                    route_text = (f'｜官方連線：'
                                  f'{point if point is not None else "來源XY未校準"}'
                                  f' → {target} '
                                  f'{arrival if arrival is not None else "落點XY未校準"}'
                                  f'（僅供查閱）')
                parts.append(f"#{door['index']}：" + '／'.join(labels) + route_text)
            if row.get('hidden_stage_markers'):
                parts.append(
                    f"StageMap 隱藏傳點 {row['hidden_stage_markers']} 筆"
                    "（EvtID 是目的場景，不是普通門事件索引）")
            if row.get('cross_scene_stage_markers'):
                parts.append(
                    f"StageMap 跨場景標記 {row['cross_scene_stage_markers']} 筆"
                    "（須另核對目標場景事件）")
            extra = [link for link in self.portals.data.get('official_route_references', [])
                     if link.get('scene') == row['scene']]
            if extra:
                parts.append(f'DoorLinkData_C：另有 {len(extra)} 筆獨立場景路線，'
                             '不含門事件索引，不能直接傳送')
                for item in extra[:8]:
                    parts.append(
                        f"路線 {item['route_ordinal']}："
                        f"{(item['x'], item['y']) if item['position_verified'] else '來源XY待校準'}"
                        f" → {item['destination']} "
                        f"{(item['arrival_x'], item['arrival_y']) if item['arrival_verified'] else '落點XY待校準'}"
                        '（唯讀）')
            detail.set(('；'.join(parts[:24]) +
                        (f'；其餘 {len(parts)-24} 筆請由官方完整報表查閱'
                         if len(parts) > 24 else ''))
                       if parts else '此場景沒有門索引或傳點標記。')
        table.bind('<<TreeviewSelect>>', selected)
        return win

