"""Build dashboard widgets in their original initialization order."""
import tkinter as tk
from tkinter import ttk
from wlre.ui.rounded_notebook import RoundedNotebook
from wlre.ui.dashboard_layout import DashboardLayout
from wlre.ui.chat_ui import ChatPanel
from wlre.ui.overview_ui import OverviewPanel
from wlre.services.battle.auto_battle import defaults as ai_defaults
from wlre.services.battle import party_guard
from wlre.ui.services_ui import PartyPanel, AlchemyPanel
from wlre.ui.companion_ui import CompanionPanel
from wlre.ui.expedition_ui import ExpeditionPanel
from wlre.ui.instance_ui import InstancePanel
from wlre.ui.party_guard_ui import PartyGuardPanel
from wlre.ui.crafting_ui import CraftingPanel
from wlre.ui.efficiency_ui import EfficiencyPanel
from wlre.ui.home_map import HomeMap
from wlre.ui.battle_view import BattleView

def build_dashboard(app):
    root=app.root
    app.layout=DashboardLayout(root,app)
    app.position_summary=app.layout.position
    app.main_tab=app.layout.content
    left_panel=app.layout.left
    right=app.layout.right
    app.left_panel=left_panel
    app.chat_panel=ChatPanel(left_panel,app,height=175)
    app.chat_panel.pack(side='bottom',fill='x',pady=(8,0))
    left_tabs=RoundedNotebook(left_panel,borderless=True,icons=True)
    app.left_tabs=left_tabs
    left_tabs.pack(fill='both',expand=True)
    overview=ttk.Frame(left_tabs,padding=6)
    left_tabs.add(overview,text='主頁')
    app.overview_panel=OverviewPanel(overview,app)
    app.overview_panel.pack(fill='both',expand=True)
    app.priority_target=None
    app.battle_selection_key=None
    # Map double-click navigation keeps its destination internally.
    app.x,app.y=tk.StringVar(),tk.StringVar()
    for var in (app.x,app.y):var.trace_add('write',lambda *args:setattr(app,'map_target_scene',None))
    app.ai_settings=ai_defaults()
    app.party_guard_load_error=''
    try:app.ai_settings['party_guard']=party_guard.load()
    except (OSError,ValueError,TypeError) as exc:app.party_guard_load_error=str(exc)
    app.ai_status=tk.StringVar(value='已停止')
    app.roaming_status=tk.StringVar(value='已停止')
    app.party_panel=PartyPanel(left_tabs,app)
    left_tabs.add(app.party_panel,text='組隊')
    app.companion_panel=CompanionPanel(left_tabs,app)
    left_tabs.add(app.companion_panel,text='夥伴出戰')
    app.expedition_panel=ExpeditionPanel(left_tabs,app)
    left_tabs.add(app.expedition_panel,text='遠征')
    # Sidebar '副本' opens a separate, fixed-size room management window.
    app.instance_launcher=ttk.Frame(left_tabs,padding=16)
    left_tabs.add(app.instance_launcher,text='副本')
    ttk.Label(app.instance_launcher,text='副本／協力管理',
              style='Heading.TLabel').pack(anchor='w',pady=(0,8))
    ttk.Label(app.instance_launcher,
              text='以獨立視窗查看副本清單、建立與加入房間。'
                   '不再受主畫面的聊天、地圖區裁切。',
              style='Muted.TLabel',wraplength=440).pack(
                  anchor='w',fill='x',pady=(0,12))
    app.open_instance_button=ttk.Button(
        app.instance_launcher,text='開啟副本／協力視窗',command=app.open_instances)
    app.open_instance_button.pack(anchor='w',pady=(0,8))
    app.instance_window=tk.Toplevel(root)
    app.instance_window.withdraw()
    app.instance_window.title('飄流Re:LaLa · 副本／協力房間管理')
    sw,sh=root.winfo_screenwidth(),root.winfo_screenheight()
    # Fit 720p without allowing users to resize the room-management window.
    width=min(1040,max(760,sw-80))
    height=min(600,max(480,sh-110))
    app.instance_window.geometry(
        f'{width}x{height}+{max(0,(sw-width)//2)}+{max(0,(sh-height)//2)}')
    app.instance_window.minsize(width,height)
    app.instance_window.maxsize(width,height)
    app.instance_window.resizable(False,False)
    app.instance_window.protocol('WM_DELETE_WINDOW',app.hide_instances)
    app.instance_panel=InstancePanel(app.instance_window,app)
    app.instance_panel.pack(fill='both',expand=True)
    app.party_guard_panel=PartyGuardPanel(app.party_panel.guard_host,app,compact=True)
    app.party_guard_panel.pack(fill='both',expand=True)
    if app.party_guard_load_error:app.party_guard_panel.note.set('名單讀取失敗，未啟用：'+app.party_guard_load_error)
    app.alchemy_panel=AlchemyPanel(left_tabs,app)
    left_tabs.add(app.alchemy_panel,text='煉金')
    app.crafting_panel=CraftingPanel(left_tabs,app)
    left_tabs.add(app.crafting_panel,text='製作')
    app.efficiency_panel=EfficiencyPanel(left_tabs,app)
    left_tabs.add(app.efficiency_panel,text='經驗效率',align='right')
    app.crafting_panel.configure(padding=6)
    for page in (overview,app.party_panel,app.companion_panel,app.expedition_panel,app.instance_launcher,app.alchemy_panel,app.crafting_panel,app.efficiency_panel):
        page._section_outline=True
    def _on_left_tab_changed(event):
        app.refresh_selected()
        if left_tabs.select()==str(app.instance_launcher):
            app.open_instances()
    left_tabs.bind('<<NotebookTabChanged>>',_on_left_tab_changed,add='+')
    app.overview_panel.update_state({})
    app.home_map=HomeMap(right,app.pick_map_destination,app.open_navigation,on_move=app.walk,on_portal=lambda portal_id:app.send({'type':'portal_direct','portal_id':portal_id}),show_status=False,compact=True)
    app.home_map.configure(width=380,height=320)
    app.home_map.grid(row=0,column=0,sticky='nw')
    app.home_map.grid_propagate(False)
    app.activity_tabs=RoundedNotebook(right)
    app.activity_tabs.grid(row=1,column=0,sticky='nsew',pady=(8,0))
    right.columnconfigure(0,weight=1);right.rowconfigure(1,weight=1)
    app.logs_frame=ttk.Frame(app.activity_tabs,padding=6)
    app.logs_frame._section_outline=True
    app.activity_tabs.add(app.logs_frame,text='事件紀錄')
    app.formation=BattleView(app.activity_tabs,app.pick_battle_unit)
    app.formation.configure(padding=6);app.formation._section_outline=True
    app.activity_tabs.add(app.formation,text='戰場陣形')
    app.activity_tabs.bind('<<NotebookTabChanged>>',lambda e:app.refresh_selected(),add='+')
    logs=app.logs_frame
    app.log=tk.Text(logs,height=5,state='disabled',wrap='word',font=('Microsoft JhengHei UI',-14),background='#142638',foreground='#eff7ff',insertbackground='#eff7ff',relief='flat')
    logscroll=ttk.Scrollbar(logs,orient='vertical',command=app.log.yview)
    app.log.configure(yscrollcommand=logscroll.set)
    logscroll.pack(side='right',fill='y')
    app.log.pack(side='left',fill='both',expand=True)
