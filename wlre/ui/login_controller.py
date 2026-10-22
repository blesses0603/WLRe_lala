"""Tk-thread login, remembered identities, server selection and role UI."""
import tkinter as tk
from wlre.ui.window_layout import configure_dialog
from wlre.ui.layout import heading
from wlre.ui.theme import group as LabelFrame
from tkinter import ttk, messagebox
from wlre.storage import login_memory
from wlre.storage import server_lines

class LoginController:
    def initialize_login(self):
        self.host,self.account,self.password=(tk.StringVar() for _ in range(3))
        self.port=tk.StringVar(value='16988')
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
        configure_dialog(window,900,630)
        window.resizable(False,False)
        window.protocol('WM_DELETE_WINDOW',self.close_login)
        self.login_tab=ttk.Frame(window,padding=12)
        self.login_tab.pack(fill='both',expand=True)
        heading(self.login_tab,'登入與選角','選擇帳號與分流，登入後再選取角色。')
        version_row=ttk.Frame(self.login_tab)
        version_row.pack(fill='x',pady=(0,6))
        ttk.Label(version_row,textvariable=self.version_gate_text,wraplength=580,
                  style='Muted.TLabel',justify='left').pack(side='left',fill='x',expand=True)
        ttk.Button(version_row,text='重新檢查',command=self.start_version_check,
                   padding=(3,2)).pack(side='right',padx=(4,0))
        ttk.Button(version_row,text='遊戲目錄',command=self.choose_version_folder,
                   padding=(3,2)).pack(side='right',padx=(4,0))
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
        self.connect_button=ttk.Button(login,text='登入',command=self.connect)
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
        ttk.Label(self.login_tab,textvariable=self.connection_status,wraplength=620).pack(fill='x')
        ttk.Label(self.login_tab,text='選角後等待世界資料同步完成，將自動開啟主頁。',style='Muted.TLabel').pack(anchor='w')
        self.update_role_choices(self.snapshot.get('roles',[]))
        self._set_login_gate_button()
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
        if not self.live_active and self.account.get():
            try:self.activate_account_settings(self.host.get(),int(self.port.get()),self.account.get())
            except (OSError,ValueError,TypeError,KeyError):self.status.set('帳號偏好設定無法讀取，請檢查設定檔。')
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


