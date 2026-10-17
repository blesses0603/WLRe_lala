"""Desktop front end. Opt-in login memory is separate from exported connection settings."""
import json
import queue
import threading
import time
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.rounded_notebook import RoundedNotebook
from wlre import __version__
from wlre.ui.theme import group as LabelFrame
from tkinter import ttk, filedialog, messagebox
from wlre.ui.theme import install as install_theme
from wlre.network.client import run_client
from wlre.storage.defaults import load_default_profile
from wlre.services.world.map_names import map_label
from wlre.ui.battle_view import BattleView
from wlre.services.battle.battle_commands import owned_units, slot
from wlre.services.world.display_position import current_position
from wlre.ui.home_map import HomeMap
from wlre.services.world.roaming import summary as roaming_summary
from wlre.services.battle.auto_battle import defaults as ai_defaults, summary as ai_summary
from wlre.ui.auto_battle_ui import open_settings
from wlre.ui.resource_view import ResourceView
from wlre.ui.services_ui import PartyPanel, AlchemyPanel
from wlre.ui.chat_ui import ChatPanel
from wlre.core.event_log import lines as local_event_lines, chinese, PHASES
from wlre.ui.efficiency_ui import EfficiencyPanel
from wlre.ui.overview_ui import OverviewPanel
from wlre.ui.dashboard_layout import DashboardLayout
from wlre.ui.crafting_ui import CraftingPanel
from wlre.services.world.movement_display import movement_summary
from wlre.services.battle import party_guard;from wlre.storage import login_memory;from wlre.storage import server_lines
from wlre.ui.party_guard_ui import PartyGuardPanel


class App:
    def __init__(self, root):
        self.root=root
        root.withdraw()
        self.login_window=None
        self.entered_world=False
        root.title(f'飄流Re:LaLa  =By赤寧= · {__version__}')
        # Keep the main dashboard at the fixed supported window size.
        width,height=1280,800
        root.geometry(f'{width}x{height}+{max(0,(root.winfo_screenwidth()-width)//2)}+{max(0,(root.winfo_screenheight()-height)//2)}')
        root.minsize(width,height)
        root.maxsize(width,height)
        root.resizable(False,False)
        self.theme=install_theme(root)
        self.events,self.commands=queue.Queue(),queue.Queue()
        self.stop_event=threading.Event()
        self.worker=None
        self.live_active=False
        self.profile=None
        self.snapshot={}
        self.navigation_windows=[]
        self.resource_windows=[]
        self.role_map={}
        self.map_target_scene=None
        self.last_movement_check=None
        self.host,self.account,self.password=(tk.StringVar() for _ in range(3))
        self.port=tk.StringVar(value='16988')
        self.verify=tk.BooleanVar(value=True)
        self.server_line=tk.StringVar(value=server_lines.CUSTOM)
        self.server_group=tk.StringVar()
        self.line_display=tk.StringVar()
        self._selected_line_id=0;self._line_endpoint=None;self.line_choices={server_lines.CUSTOM:None}
        try:self.line_catalog=server_lines.load()
        except (OSError,ValueError,TypeError):self.line_catalog=[]
        self.remember_account=tk.BooleanVar(value=False)
        self.remember_password=tk.BooleanVar(value=False)
        self._login_memory_key=None;self._loaded_identity=None
        self._memory_restoring=False;self._password_autofilled=False;self.saved_accounts={}
        for var in (self.host,self.port,self.account):var.trace_add('write',self.login_identity_changed)
        self.password.trace_add('write',self.login_password_changed)
        self.status=tk.StringVar(value='載入設定中…')
        self.world=tk.StringVar(value='尚未收到本機角色位置。')
        self.world_compact=tk.StringVar(value='尚未收到角色位置')
        self.movement_status=tk.StringVar(value='尚無移動要求。')
        self.layout=DashboardLayout(root,self)
        self.position_summary=self.layout.position
        self.main_tab=self.layout.content
        left_panel=self.layout.left
        right=self.layout.right
        self.left_panel=left_panel
        self.chat_panel=ChatPanel(left_panel,self,height=205)
        self.chat_panel.pack(side='bottom',fill='x',pady=(8,0))
        left_tabs=RoundedNotebook(left_panel)
        self.left_tabs=left_tabs
        left_tabs.pack(fill='both',expand=True)
        overview=ttk.Frame(left_tabs,padding=(0,4))
        left_tabs.add(overview,text='主頁')
        self.overview_panel=OverviewPanel(overview,self)
        self.overview_panel.pack(fill='both',expand=True)
        left_outer=ttk.Frame(left_tabs)
        left_tabs.add(left_outer,text='戰鬥/徘徊')
        self.battle_page=left_outer
        battle=LabelFrame(left_outer,text='戰場',padding=8)
        battle.pack(fill='both',expand=True)
        tabs=RoundedNotebook(battle)
        tabs.pack(fill='both',expand=True)
        self.battle_tabs=tabs
        self.formation=BattleView(tabs,self.pick_battle_unit)
        tabs.add(self.formation,text='戰場陣形')
        self.priority_target=None
        self.battle_selection_key=None
        controls=ttk.Frame(tabs)
        tabs.add(controls,text='自動徘徊')
        ai_page=ttk.Frame(tabs)
        tabs.add(ai_page,text='AI')
        self.ai_page=ai_page
        self.roam_page=controls
        # Map double-click navigation keeps its destination internally.
        self.x,self.y=tk.StringVar(),tk.StringVar()
        for var in (self.x,self.y):var.trace_add('write',lambda *args:setattr(self,'map_target_scene',None))
        ai=LabelFrame(ai_page,text='Lua 規則自動戰鬥',padding=8)
        ai.pack(fill='x',pady=(10,0))
        self.ai_settings=ai_defaults()
        self.party_guard_load_error=''
        try:self.ai_settings['party_guard']=party_guard.load()
        except (OSError,ValueError,TypeError) as exc:self.party_guard_load_error=str(exc)
        self.ai_status=tk.StringVar(value='已停止；啟動後每回合自動為角色與夥伴下令。')
        ttk.Button(ai,text='包包／特技',command=self.open_resources).grid(row=0,column=3,padx=5)
        ttk.Button(ai,text='AI設定',command=lambda:open_settings(self)).grid(row=0,column=0,padx=(0,5))
        ttk.Button(ai,text='啟動AI',command=lambda:self.send({'type':'start_auto_battle','settings':self.ai_settings})).grid(row=0,column=1,padx=5)
        ttk.Button(ai,text='停止AI',command=lambda:self.send({'type':'stop_auto_battle'})).grid(row=0,column=2,padx=5)
        ttk.Label(ai,textvariable=self.ai_status,wraplength=510).grid(row=1,column=0,columnspan=3,sticky='w',pady=(7,0))
        self.party_guard_panel=PartyGuardPanel(ai_page,self)
        self.party_guard_panel.pack(fill='x',pady=(6,0))
        if self.party_guard_load_error:self.party_guard_panel.note.set('名單讀取失敗，未啟用：'+self.party_guard_load_error)
        roam=LabelFrame(controls,text='自動徘徊',padding=8)
        roam.pack(fill='x',pady=(10,0))
        self.roaming_status=tk.StringVar(value='原版四點循環：左下、左上、右下、右上。')
        ttk.Button(roam,text='開始／重新定位',command=self.start_roaming).grid(row=0,column=0,padx=4)
        ttk.Button(roam,text='停止',command=lambda:self.send({'type':'stop_roaming'})).grid(row=0,column=1)
        ttk.Label(roam,textvariable=self.roaming_status,wraplength=580).grid(row=1,column=0,columnspan=2,sticky='w',pady=(7,0))
        ttk.Label(roam,text='依 Lua 固定偏移四點循環；遇戰暫停，戰後續走。隊員跟隨隊長。',wraplength=580).grid(row=2,column=0,columnspan=2,sticky='w',pady=(5,0))
        self.party_panel=PartyPanel(left_tabs,self)
        left_tabs.add(self.party_panel,text='組隊')
        self.alchemy_panel=AlchemyPanel(left_tabs,self)
        left_tabs.add(self.alchemy_panel,text='自動煉金')
        self.crafting_panel=CraftingPanel(left_tabs,self)
        left_tabs.add(self.crafting_panel,text='家具製作')
        self.efficiency_panel=EfficiencyPanel(left_tabs,self)
        left_tabs.add(self.efficiency_panel,text='經驗效率')
        self.overview_panel.update_state({})
        self.logs_frame=LabelFrame(right,text='事件紀錄',padding=6,height=205)
        self.logs_frame.pack(side='bottom',fill='x',pady=(8,0))
        self.logs_frame.pack_propagate(False)
        self.home_map=HomeMap(right,self.pick_map_destination,self.open_navigation,on_move=self.walk,on_portal=lambda portal_id:self.send({'type':'portal_direct','portal_id':portal_id}),show_status=False,compact=True)
        self.home_map.pack(fill='both',expand=True)
        logs=self.logs_frame
        self.log=tk.Text(logs,height=5,state='disabled',wrap='word',font=('Microsoft JhengHei UI',-16),background='#142638',foreground='#eff7ff',insertbackground='#eff7ff',relief='flat')
        logscroll=ttk.Scrollbar(logs,orient='vertical',command=self.log.yview)
        self.log.configure(yscrollcommand=logscroll.set)
        logscroll.pack(side='right',fill='y')
        self.log.pack(side='left',fill='both',expand=True)
        try:
            self.set_profile(load_default_profile())
            self.status.set('已載入預設連線設定。請登入並選角，進入遊戲後自動開啟主頁。')
        except (OSError,ValueError,KeyError,TypeError):
            self.status.set('連線設定無法讀取，請載入設定或匯入登入封包。')
        self.load_saved_login()
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.show_login()
        root.after(50,self.poll)

    def dialog_parent(self):
        if self.login_window is not None and self.login_window.winfo_exists():
            return self.login_window
        return self.root

    def show_login(self):
        self.restore_remembered_password()
        if self.login_window is not None and self.login_window.winfo_exists():
            self.login_window.deiconify()
            self.login_window.lift()
            self.login_window.focus_set()
            return
        window=tk.Toplevel(self.root)
        self.login_window=window
        window.title('飄流Re:LaLa  =By赤寧= · 登入／選角')
        configure_dialog(window,900,580)
        window.resizable(False,False)
        window.protocol('WM_DELETE_WINDOW',self.close_login)
        self.login_tab=ttk.Frame(window,padding=12)
        self.login_tab.pack(fill='both',expand=True)
        connection_tools=ttk.Frame(self.login_tab)
        connection_tools.pack(fill='x',pady=(0,6))
        for text,callback in [('載入設定',self.load_profile),
                              ('儲存設定',self.save_profile)]:
            ttk.Button(connection_tools,text=text,command=callback).pack(side='left',padx=3)
        ttk.Label(connection_tools,text='帳號清單').pack(side='left',padx=(8,4))
        self.saved_account_choice=ttk.Combobox(connection_tools,state='readonly',width=24)
        self.saved_account_choice.pack(side='left',fill='x',expand=True,padx=(0,4))
        self.saved_account_choice.bind('<<ComboboxSelected>>',self.select_saved_login)
        ttk.Button(connection_tools,text='新增',command=self.new_saved_login).pack(side='right')
        self.refresh_saved_accounts()
        login=LabelFrame(self.login_tab,text='帳號登入',padding=8)
        login.pack(fill='x')
        for col in range(4):login.columnconfigure(col,weight=1)
        ttk.Label(login,text='伺服器').grid(row=0,column=0,sticky='w',padx=3)
        self.server_choice=ttk.Combobox(login,textvariable=self.server_group,state='readonly',width=12)
        self.server_choice.grid(row=0,column=1,sticky='ew',padx=3)
        self.server_choice.bind('<<ComboboxSelected>>',self.select_server_group)
        ttk.Label(login,text='分流選擇').grid(row=0,column=2,sticky='w',padx=3)
        self.line_choice=ttk.Combobox(login,textvariable=self.line_display,state='readonly',width=12)
        self.line_choice.grid(row=0,column=3,sticky='ew',padx=3)
        self.line_choice.bind('<<ComboboxSelected>>',self.select_display_line)
        self.refresh_server_lines()
        for label,var,row,col,span in [('帳號',self.account,1,0,2),('密碼',self.password,1,2,2)]:
            ttk.Label(login,text=label).grid(row=row,column=col,columnspan=span,sticky='w',padx=3,pady=(3,2))
            ttk.Entry(login,textvariable=var,width=10,show='*' if label=='密碼' else '').grid(row=row+1,column=col,columnspan=span,sticky='ew',padx=3)
        ttk.Checkbutton(login,text='記住帳號',variable=self.remember_account,command=lambda:self.remember_login_changed('account')).grid(row=3,column=0,sticky='w',pady=(6,0))
        ttk.Checkbutton(login,text='記住密碼',variable=self.remember_password,command=lambda:self.remember_login_changed('password')).grid(row=3,column=1,sticky='w',pady=(6,0))
        ttk.Button(login,text='儲存此組',command=lambda:self.save_saved_login(explicit=True)).grid(row=3,column=2,sticky='ew',padx=3,pady=(6,0))
        ttk.Button(login,text='刪除此組',command=self.delete_saved_login).grid(row=3,column=3,sticky='ew',padx=3,pady=(6,0))
        ttk.Checkbutton(login,text='先驗證帳號，再登入',variable=self.verify).grid(row=4,column=0,columnspan=2,sticky='w',pady=(10,0))
        self.connect_button=ttk.Button(login,text='驗證並登入',command=self.connect)
        self.connect_button.grid(row=4,column=2,sticky='ew',padx=3,pady=(10,0))
        ttk.Button(login,text='中斷',command=self.stop).grid(row=4,column=3,sticky='ew',padx=3,pady=(10,0))
        choices=LabelFrame(self.login_tab,text='選擇角色',padding=8)
        choices.pack(fill='x',pady=6)
        row=ttk.Frame(choices)
        row.pack(fill='x')
        self.role_choice=ttk.Combobox(row,state='readonly',width=28)
        self.role_choice.pack(side='left',fill='x',expand=True,padx=(0,8))
        ttk.Button(row,text='選角進入',command=self.select_role).pack(side='right')
        ttk.Label(self.login_tab,textvariable=self.status,wraplength=620).pack(fill='x',pady=8)
        ttk.Label(self.login_tab,text='選角後等待世界資料同步完成，將自動開啟主頁。',style='Muted.TLabel').pack(anchor='w')
        self.update_role_choices(self.snapshot.get('roles',[]))
        self.connect_button.configure(state='disabled' if self.live_active else 'normal')
        window.lift()
        window.focus_set()

    def refresh_server_lines(self):
        choices={server_lines.CUSTOM:None}
        for row in self.line_catalog:choices[row['name']]=dict(row)
        try:
            for record in login_memory.list_entries():
                if record['line_id']:
                    label=record['line_name'] or f"分流 {record['line_id']}"
                    candidate={'id':record['line_id'],'name':label,'host':record['host'],'port':record['port']}
                    if label not in choices:choices[label]=candidate
        except (OSError,ValueError):pass
        self.line_choices=choices
        self.sync_server_menus()

    @staticmethod
    def line_group(line):
        return {1:'地球',2:'水星'}.get(line['id']//100,'自訂') if line else '自訂'

    def sync_server_menus(self):
        line=self.line_choices.get(self.server_line.get())
        if line is None:line=server_lines.for_endpoint(self.line_catalog,self.host.get(),int(self.port.get()))
        group=self.line_group(line)
        self.server_group.set(group)
        groups=['地球','水星']
        if group=='自訂':groups.append(group)
        self.server_choice.configure(values=groups)
        self.refresh_group_lines(group)
        label=next((label for label,row in self.display_lines.items() if row and line and row['id']==line['id'] and row['host']==line['host'] and row['port']==line['port']),server_lines.CUSTOM)
        self.line_display.set(label)

    def refresh_group_lines(self,group):
        self.display_lines={}
        for row in self.line_choices.values():
            if row and self.line_group(row)==group:
                label=f"{row['id']%100}線"
                if label in self.display_lines:label=f"{label}（已儲存：{row['name']}）"
                self.display_lines[label]=row
        if group=='自訂':self.display_lines[server_lines.CUSTOM]=None
        self.line_choice.configure(values=list(self.display_lines))

    def select_server_group(self,event=None):
        self.refresh_group_lines(self.server_group.get())
        if self.display_lines:
            self.line_display.set(next(iter(self.display_lines)))
            self.select_display_line()

    def select_display_line(self,event=None):
        line=self.display_lines.get(self.line_display.get())
        self.server_line.set(line['name'] if line else server_lines.CUSTOM)
        self.select_server_line()

    def select_server_line(self,event=None):
        line=self.line_choices.get(self.server_line.get())
        self._selected_line_id=line['id'] if line else 0
        if line:
            self._memory_restoring=True
            try:
                self.host.set(line['host']);self.port.set(str(line['port']))
                self._line_endpoint=(line['host'],str(line['port']))
            finally:self._memory_restoring=False
        self.login_identity_changed()
        if hasattr(self,'server_choice'):self.sync_server_menus()

    def login_password_changed(self,*args):
        if not self._memory_restoring:self._password_autofilled=False

    def login_identity_changed(self,*args):
        if self._memory_restoring:return
        if self._selected_line_id and self._line_endpoint!=(self.host.get().strip(),self.port.get()):
            self._selected_line_id=0;self.server_line.set(server_lines.CUSTOM)
        current=(self.host.get().strip(),self.port.get(),self.account.get(),self._selected_line_id)
        if self._loaded_identity and current!=self._loaded_identity:
            if self._password_autofilled:self.password.set('')
            self._password_autofilled=False;self._login_memory_key=None
            if hasattr(self,'saved_account_choice'):self.saved_account_choice.set('未儲存的新帳號')

    def refresh_saved_accounts(self):
        try:entries=login_memory.list_entries()
        except (OSError,ValueError):entries=[]
        self.saved_accounts={f"{r['account']}｜{r['line_name'] or server_lines.CUSTOM} @ {r['host']}:{r['port']}":r['key'] for r in entries}
        if hasattr(self,'saved_account_choice') and self.saved_account_choice.winfo_exists():
            self.saved_account_choice.configure(values=list(self.saved_accounts))
            label=next((label for label,key in self.saved_accounts.items() if key==self._login_memory_key),'選擇已記住的帳號')
            self.saved_account_choice.set(label)

    def load_saved_login(self,key=None):
        try:
            record=login_memory.load(key)
            if record is None:return
            self._memory_restoring=True
            try:
                self._selected_line_id=record['line_id'];self.server_line.set(record['line_name'] or server_lines.CUSTOM)
                self._line_endpoint=(record['host'],str(record['port']))
                self.host.set(record['host']);self.port.set(str(record['port']));self.account.set(record['account'])
                self.password.set(record['password'])
                self.remember_account.set(True);self.remember_password.set(record['remember_password'])
                self._login_memory_key=record['key']
                self._loaded_identity=(record['host'],str(record['port']),record['account'],record['line_id'])
                self._password_autofilled=bool(record['password'])
            finally:self._memory_restoring=False
            self.status.set('已帶入記住的帳號；密碼無法解密，請重新輸入。' if record['password_error'] else '已帶入記住的登入資料，請按登入。')
        except (OSError,ValueError):self.status.set('記住的登入資料無法讀取；請手動輸入。')
        self.refresh_saved_accounts()
        if hasattr(self,'line_choice'):self.refresh_server_lines()

    def restore_remembered_password(self):
        if self.live_active or self.password.get() or not self.remember_password.get() or not self._login_memory_key:return
        try:
            record=login_memory.load(self._login_memory_key)
            if record and (record['host'],str(record['port']),record['account'],record['line_id'])==(self.host.get().strip(),self.port.get(),self.account.get(),self._selected_line_id):
                self._memory_restoring=True
                try:self.password.set(record['password']);self._password_autofilled=bool(record['password'])
                finally:self._memory_restoring=False
        except (OSError,ValueError):pass

    def select_saved_login(self,event=None):
        key=self.saved_accounts.get(self.saved_account_choice.get())
        if not key:return
        try:login_memory.select(key)
        except (OSError,ValueError) as exc:
            messagebox.showerror('帳號清單',str(exc),parent=self.dialog_parent());return
        self.load_saved_login(key)

    def new_saved_login(self):
        self._memory_restoring=True
        try:
            self._login_memory_key=None;self._loaded_identity=None;self._password_autofilled=False
            self.account.set('');self.password.set('');self.remember_account.set(True);self.remember_password.set(False)
        finally:self._memory_restoring=False
        self.saved_account_choice.set('未儲存的新帳號')
        self.status.set('請輸入新帳號；勾選記住密碼後可按「儲存此組」。')

    def save_saved_login(self,explicit=False):
        if explicit:self.remember_account.set(True)
        if not self.remember_account.get() and not self._login_memory_key:return True
        try:
            key=login_memory.save(self.host.get().strip(),int(self.port.get()),self.account.get(),self.password.get(),self.remember_account.get(),self.remember_password.get(),line_id=self._selected_line_id,line_name=self.server_line.get())
            self._login_memory_key=key
            self._loaded_identity=(self.host.get().strip(),self.port.get(),self.account.get(),self._selected_line_id) if key else None
        except (OSError,ValueError) as exc:
            messagebox.showerror('記住登入資料',str(exc),parent=self.dialog_parent());return False
        self.refresh_saved_accounts()
        if explicit:self.status.set('此組帳號已儲存。')
        return True

    def delete_saved_login(self):
        if not self._login_memory_key:
            messagebox.showinfo('帳號清單','請先選擇要刪除的已儲存帳號。',parent=self.dialog_parent());return
        try:login_memory.delete(self._login_memory_key)
        except (OSError,ValueError) as exc:
            messagebox.showerror('帳號清單',str(exc),parent=self.dialog_parent());return
        self.new_saved_login();self.remember_account.set(False)
        self.refresh_saved_accounts();self.status.set('已刪除此組帳號及已記住的密碼。')

    def remember_login_changed(self,which):
        try:
            if not self.remember_account.get() and which=='account':
                if self._login_memory_key:login_memory.delete(self._login_memory_key)
                self._login_memory_key=None;self.remember_password.set(False)
                if self._password_autofilled:self.password.set('')
            elif self.remember_password.get() and which=='password':self.remember_account.set(True)
            elif which=='password' and self._login_memory_key:
                login_memory.forget_password(self._login_memory_key)
                if self._password_autofilled:self.password.set('')
        except (OSError,ValueError) as exc:
            self.remember_account.set(bool(self._login_memory_key))
            try:
                entry=next((r for r in login_memory.list_entries() if r['key']==self._login_memory_key),{})
                self.remember_password.set(bool(entry.get('remember_password')))
            except (OSError,ValueError):pass
            messagebox.showerror('記住登入資料',str(exc),parent=self.dialog_parent())
        self.refresh_saved_accounts()

    def close_login(self):
        if not self.entered_world:
            self.close()
            return
        self.login_window.destroy()
        self.login_window=None

    def update_role_choices(self, roles):
        self.role_map={f"{r['index']} · {r['name']} · Lv.{r['level']}":r['index'] for r in roles}
        if self.login_window is not None and self.login_window.winfo_exists():
            values=list(self.role_map)
            selected=self.role_choice.get()
            self.role_choice['values']=values
            if selected not in self.role_map:
                if values:self.role_choice.current(0)
                else:self.role_choice.set('')

    def show_main(self):
        self.entered_world=True
        if self.login_window is not None:
            self.login_window.destroy()
            self.login_window=None
        self.root.deiconify()
        self.root.lift()
        self.root.focus_set()


    def refresh_battle_selection(self):
        state=self.snapshot
        selection_key=(state.get('battle_count'),state.get('player',{}).get('role_id'))
        if selection_key!=self.battle_selection_key:
            self.priority_target=None
            self.battle_selection_key=selection_key
        roster=owned_units(state,False)
        enemies=[u for u in state.get('battle_units',{}).values() if u.get('hp',0)>0 and not u.get('exited')
                 and roster and (u['col']>2)!=(roster[0]['col']>2)]
        if self.priority_target not in {slot(u) for u in enemies}:self.priority_target=None
        self.formation.set_state(state,None,self.priority_target)

    def pick_battle_unit(self,selected_slot,owned):
        if not owned:
            self.priority_target=selected_slot
            self.refresh_battle_selection()

    def pick_map_destination(self,scene,x,y):
        current=self.snapshot.get('player',{}).get('scene')
        if current is not None and current!=scene:
            self.status.set('目前預覽地圖與角色所在不同，請切回角色地圖再選點。')
            return False
        self.x.set(str(x));self.y.set(str(y))
        self.map_target_scene=scene
        self.status.set(f'{map_label(scene)}｜已選目的地 ({x}, {y})；雙擊小地圖即可開始移動。')
        return True

    def open_navigation(self):
        try:
            from wlre.ui.navigation_gui import NavigationWindow
            viewer = NavigationWindow(self.root, self.home_map.selected_id, on_route=self.home_map.set_route)
            viewer.update_live_state(self.snapshot)
            self.navigation_windows.append(viewer)
        except (OSError,ValueError,KeyError) as exc:
            messagebox.showerror('導航資料無法載入',str(exc),parent=self.root)

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end',chinese(text)+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 500: self.log.delete('1.0','101.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def background(self, function):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('處理中','請先中斷目前的工作。',parent=self.root)
            return False
        def work():
            try: function()
            except Exception as exc: self.events.put(('error',str(exc)))
            finally: self.events.put(('finished',None))
        self.worker=threading.Thread(target=work,daemon=True)
        self.worker.start()
        return True

    def set_profile(self, profile):
        for key in ('rx_xor','tx_xor','platform','language','game_endpoint'):
            if key not in profile: raise ValueError('連線設定缺少必要欄位：'+key)
        endpoint=profile['game_endpoint']
        if not isinstance(endpoint.get('host'),str) or not 1 <= int(endpoint['port']) <= 65535:
            raise ValueError('伺服器設定不正確')
        self.profile=profile
        self.host.set(endpoint['host']);self.port.set(str(endpoint['port']))
        line=server_lines.for_endpoint(self.line_catalog,endpoint['host'],int(endpoint['port']))
        self._selected_line_id=line['id'] if line else 0
        self._line_endpoint=(endpoint['host'],str(endpoint['port']))
        self.server_line.set(line['name'] if line else server_lines.CUSTOM)
        if hasattr(self,'line_choice'):self.refresh_server_lines()
        self.status.set('連線設定已載入；可手動輸入或選擇已記住的帳號。')

    def load_profile(self):
        path=filedialog.askopenfilename(parent=self.dialog_parent(),filetypes=[('連線設定','*.json')])
        if not path:return
        try:
            with open(path,encoding='utf-8-sig') as f:self.set_profile(json.load(f))
        except (OSError,ValueError,KeyError,TypeError) as exc:messagebox.showerror('設定錯誤',str(exc),parent=self.dialog_parent())

    def save_profile(self):
        if not self.profile:return
        path=filedialog.asksaveasfilename(parent=self.dialog_parent(),defaultextension='.json',initialfile='connection_profile.json',filetypes=[('連線設定','*.json')])
        if path:
            # Explicit allowlist: account/password can never enter settings.
            fields=('rx_xor','tx_xor','platform','language','verification_endpoint','game_endpoint','capture_sha256','observed_packets','evidence')
            try:
                with open(path,'w',encoding='utf-8') as f:json.dump({k:self.profile[k] for k in fields if k in self.profile},f,ensure_ascii=False,indent=2)
            except OSError as exc:messagebox.showerror('儲存失敗',str(exc),parent=self.dialog_parent())

    def connect(self):
        if not self.profile:
            messagebox.showinfo('尚無設定','請先匯入登入封包或載入連線設定。',parent=self.dialog_parent());return
        if self.worker and self.worker.is_alive():return
        account,password=self.account.get(),self.password.get()
        if not account or not password:
            messagebox.showinfo('登入','請輸入帳號與密碼。',parent=self.dialog_parent());return
        try:port=int(self.port.get())
        except ValueError:return
        host,profile,verify=self.host.get().strip(),dict(self.profile),self.verify.get()
        if not self.save_saved_login():return
        self.password.set('')
        self.entered_world=False
        self.update_role_choices([])
        self.status.set('正在連線與驗證帳號…')
        self.connect_button.configure(state='disabled')
        self.stop_event=threading.Event();self.commands=queue.Queue();self.snapshot={}
        self.chat_panel.reset()
        self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled')
        self.efficiency_panel.update_state({})
        self.overview_panel.update_state({})
        def work():
            self.live_active=True
            try:
                run_client(host,port,profile,lambda e:self.events.put(('event',e)),
                           account=account,password=password,verify_first=verify,duration=None,
                           stop_event=self.stop_event,commands=self.commands,
                           on_state=lambda s:self.events.put(('state',s)),snapshot_interval=0.1)
            finally:
                self.live_active=False
                self.events.put(('session_finished',None))
        self.background(work)

    def send(self, command):
        if not self.live_active or not self.worker or not self.worker.is_alive():
            messagebox.showinfo('尚未連線','請先登入後再操作。',parent=self.root);return
        self.commands.put(command)

    def select_role(self):
        index=self.role_map.get(self.role_choice.get())
        if index:self.send({'type':'select_role','index':index})

    def open_resources(self):
        self.resource_windows.append(ResourceView(self))

    def start_roaming(self):
        self.send({'type':'start_roaming'})

    def walk(self):
        if self.map_target_scene is not None and self.snapshot.get('player',{}).get('scene')!=self.map_target_scene:
            messagebox.showinfo('地圖不同','此目的地來自另一張預覽地圖，請重新選點。',parent=self.root);return
        try:self.send({'type':'walk','x':int(self.x.get()),'y':int(self.y.get()),
                       'scene':self.snapshot.get('player',{}).get('scene')})
        except ValueError:messagebox.showinfo('座標','X、Y 請輸入整數。',parent=self.root)

    def render(self, state):
        self.snapshot=state
        self.chat_panel.update_names(state)
        self.efficiency_panel.update_state(state)
        self.overview_panel.update_state(state)
        self.party_panel.render(state)
        self.party_guard_panel.update_state(state)
        self.alchemy_panel.render(state)
        self.crafting_panel.render(state)
        remaining_resources=[]
        for view in self.resource_windows:
            try:
                if view.window.winfo_exists():view.set_state(state);remaining_resources.append(view)
            except tk.TclError:pass
        self.resource_windows=remaining_resources
        self.ai_status.set(ai_summary(state.get('auto_battle',{})))
        self.roaming_status.set(roaming_summary(state.get('roaming',{})))
        self.home_map.set_state(state)
        check=state.get('movement_check')
        local=state.get('local_movement')
        progress=''
        if local:
            label={'running':'步行中','finished':'本機路徑已走完','stopped':'已停止同步'}.get(local['status'],local['status'])
            progress=f"{label}｜推算 ({round(local['x'])}, {round(local['y'])})｜已同步 {local['steps_sent']} 次｜{local['reason']}\n"
        self.movement_status.set(progress+(movement_summary(check) or '尚無移動要求。'))
        if check!=self.last_movement_check:
            if check:self.write(movement_summary(check))
            self.last_movement_check=check
        remaining=[]
        for viewer in self.navigation_windows:
            try:
                if viewer.window.winfo_exists():
                    viewer.update_live_state(state)
                    remaining.append(viewer)
            except tk.TclError:pass
        self.navigation_windows=remaining
        self.update_role_choices(state['roles'])
        player=state['player'];battle=state['battle']
        if player:
            location=state.get('location',{})
            fix=location.get('confirmed')
            displayed=current_position(state)
            if displayed:
                text=f"{player['name']}｜{map_label(displayed['scene'])}｜{displayed['label']} ({displayed['x']}, {displayed['y']})"
                if displayed['kind']=='local_report':
                    text+=f"｜末次伺服器確認 ({fix['x']}, {fix['y']}) {fix['source']}"
                    target=state['local_movement']['target']
                    text+=f"｜目的地 ({target['x']}, {target['y']})"
                else:
                    text+=' '+displayed.get('source','')
                    targets=[x for x in (location.get('requested_destination'),location.get('server_destination')) if x]
                    target=max(targets,key=lambda x:x.get('packet_number',0)) if targets else None
                    if target:text+=f"｜同步/通知座標 ({target['x']}, {target['y']})，非抵達確認"
                self.world.set(text)
            else:self.world.set(f"{player['name']}｜{map_label(player['scene'])}｜沒有可顯示的本機位置")
        else:self.world.set('世界資料：此連線尚無本機角色確認座標')
        if player and displayed:
            self.world_compact.set(f"{player['name']}｜{map_label(displayed['scene'])}｜座標 {displayed['x']}, {displayed['y']}｜{displayed['label']}")
        elif player:
            self.world_compact.set(f"{player['name']}｜{map_label(player['scene'])}｜位置待同步")
        else:self.world_compact.set('尚未收到角色位置')
        phase=PHASES.get(state['phase'],'角色狀態待更新')
        flow=state.get('event_flow',{})
        event_status='｜事件尚未結束 '+str(flow.get('last_source')) if flow.get('blocked') else ''
        self.status.set(chinese(phase+f"｜戰鬥 {state['battle_count']} 場／回合 {battle.get('round',0)}"+event_status))
        self.refresh_battle_selection()

    def poll(self):
        latest=None
        status_override=None
        session_finished=False
        deadline=time.perf_counter()+0.008
        for _ in range(500):
            if time.perf_counter()>=deadline:break
            try:kind,data=self.events.get_nowait()
            except queue.Empty:break
            if kind=='session_finished':session_finished=True
            elif kind=='state':latest=data
            elif kind=='error':
                self.chat_panel.finish_pending()
                self.write('錯誤：'+data);status_override=data
            elif kind=='message':self.write(data);status_override=data
            elif kind=='event':
                event=data;event_kind=event['type']
                context=latest if latest is not None else self.snapshot
                self.chat_panel.handle_event(event,context)
                if event_kind=='command_rejected' and event.get('command_type')=='craft':self.crafting_panel.status.set(event['error'])
                if event_kind.startswith('chat_'):continue
                if event_kind=='connection_closed':status_override='連線已關閉'
                for line in local_event_lines(event,context):self.write(line)
        if latest:self.render(latest)
        if status_override:self.status.set(chinese(status_override))
        if session_finished:
            self.password.set('')
            self.update_role_choices([])
            self.show_login()
            # Do not restore a stale role list when reopening after disconnect.
            self.update_role_choices([])
            self.connect_button.configure(state='normal')
        elif latest and self.live_active and latest.get('phase')=='world_ready' and latest.get('player'):
            if not self.entered_world:self.show_main()
        self.root.after(10 if not self.events.empty() else 50,self.poll)

    def stop(self):
        self.stop_event.set()
        self.status.set('正在中斷連線…')

    def close(self):
        self.stop_event.set();self.password.set('');self.root.destroy()


def main():
    root=tk.Tk();App(root);root.mainloop()


if __name__=='__main__':main()
