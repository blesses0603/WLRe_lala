"""Desktop front end. Opt-in login memory is separate from exported connection settings."""
import json
import queue
import threading
import time
from collections import deque
import tkinter as tk
from wlre import __version__
from tkinter import filedialog, messagebox
from wlre.ui.theme import install as install_theme
from wlre.network.client import run_client
from wlre.storage.defaults import load_default_profile
from wlre.storage import account_settings,server_lines
from wlre.core.diagnostics import Diagnostics
from wlre.ui.event_queue import DisplayQueue
from wlre.ui.session_bridge import SessionBridge
from wlre.ui.connection_status import ConnectionStatus
from wlre.ui.feature_windows import WINDOWS
from wlre.ui.window_layout import center_on_main
from wlre.services.world.map_names import map_label
from wlre.services.battle.battle_commands import owned_units, slot
from wlre.services.world.display_position import current_position
from wlre.services.world.roaming import summary as roaming_summary
from wlre.services.battle.auto_battle import summary as ai_summary
from wlre.ui.resource_view import ResourceView
from wlre.ui.attribute_points_ui import AttributePointWindow
from wlre.core.event_log import lines as local_event_lines, chinese, PHASES
from wlre.services.world.movement_display import movement_summary


from wlre.ui.dashboard_builder import build_dashboard
from wlre.ui.login_controller import LoginController
from wlre.ui.account_controller import AccountController
from wlre.ui.version_gate_controller import VersionGateController


class App(LoginController,AccountController,VersionGateController):
    def __init__(self, root):
        self.root=root
        self._ui_thread=threading.get_ident()
        self._closing=False
        self.diagnostics=Diagnostics()
        root.bind('<Destroy>',lambda e:self.diagnostics.close() if e.widget is root else None,add='+')
        original_exception=root.report_callback_exception
        def report_exception(*args):
            if self.diagnostics.error(*args): original_exception(*args)
        root.report_callback_exception=report_exception
        self._pending_display=None;self._last_display=0
        self._background_logs=deque(maxlen=500)
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
        self.events,self.commands=DisplayQueue(),queue.Queue()
        self.stop_event=threading.Event()
        self.worker=None
        self.live_active=False
        self.profile=None
        self._settings_key=None
        self.snapshot={}
        self.navigation_windows=[]
        self.resource_windows=[]
        self.attribute_window=None
        self.role_map={}
        self.map_target_scene=None
        self.last_movement_check=None
        self.initialize_login()
        self.initialize_version_gate()
        self.connection_monitor=ConnectionStatus()
        self.connection_status=tk.StringVar(value='尚未連線')
        self.status=tk.StringVar(value='載入設定中…')
        self.world=tk.StringVar(value='尚未收到角色位置。')
        self.world_compact=tk.StringVar(value='尚未收到角色位置')
        self.movement_status=tk.StringVar(value='尚無移動要求。')
        build_dashboard(self)
        try:
            self.set_profile(load_default_profile())
            self.status.set('已載入預設連線設定。請登入並選角，進入遊戲後自動開啟主頁。')
        except (OSError,ValueError,KeyError,TypeError):
            self.status.set('連線設定無法讀取，請載入設定或匯入登入封包。')
        self.load_saved_login()
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.show_login()
        root.after(1,self.start_version_check)
        root.after(50,self.poll)

    def assert_ui_thread(self):
        if threading.get_ident()!=self._ui_thread:raise RuntimeError("UI changes must run on the Tk thread")

    def dialog_parent(self):
        if self.login_window is not None and self.login_window.winfo_exists():
            return self.login_window
        return self.root


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
        if self.entered_world and self.background_window():
            self._background_logs.append(text);return
        self.log.configure(state='normal')
        self.log.insert('end',chinese(text)+'\n')
        count=int(self.log.index('end-1c').split('.')[0])
        if count>500:self.log.delete('1.0',f'{count-499}.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def background(self, function):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('處理中','請先中斷目前的工作。',parent=self.root)
            return False
        events=self.events
        def work():
            try: function()
            except Exception as exc:
                # Network errors before verification and after session cleanup also need a trace.
                self.diagnostics.worker_error(type(exc),exc.__traceback__)
                events.put(('error',str(exc)))
            finally: events.put(('finished',None))
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
        self.assert_ui_thread()
        if not self.can_login_after_version_check():return
        if not self.profile:
            messagebox.showinfo('尚無設定','請先匯入登入封包或載入連線設定。',parent=self.dialog_parent());return
        if self.worker and self.worker.is_alive():return
        account,password=self.account.get(),self.password.get()
        if not account or not password:
            messagebox.showinfo('登入','請輸入帳號與密碼。',parent=self.dialog_parent());return
        try:port=int(self.port.get())
        except ValueError:return
        host,profile=self.host.get().strip(),dict(self.profile)
        try:self.activate_account_settings(host,port,account)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            messagebox.showerror('帳號設定','設定無法載入，未覆寫原檔。'+str(exc),parent=self.dialog_parent());return
        if not self.save_saved_login():return
        self.password.set('')
        self.entered_world=False
        self.hide_all_features()
        self.update_role_choices([])
        self.connection_monitor.reset()
        self.connection_status.set('正在連線與驗證帳號…')
        self.status.set('正在連線與驗證帳號…')
        self.connect_button.configure(state='disabled')
        self.stop_event=threading.Event();self.commands=queue.Queue();self.snapshot={}
        self.events=DisplayQueue()
        bridge=SessionBridge(self.events)
        stop_event,commands=self.stop_event,self.commands
        self.chat_panel.reset();self._background_logs.clear()
        self._pending_display=None;self._last_display=0
        self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled')
        self.efficiency_panel.update_state({})
        self.companion_panel.render({})
        self.expedition_panel.render({})
        self.instance_panel.render({}, live=False)
        self.overview_panel.update_state({})
        self.live_active=True
        def work():
            try:
                run_client(host,port,profile,bridge.receive,
                           account=account,password=password,verify_first=True,duration=None,
                           stop_event=stop_event,commands=commands,
                           on_state=bridge.snapshot,snapshot_interval=0.1,tcp_keepalive=True)
            finally:
                bridge.finished()
        if not self.background(work):self.live_active=False

    def receive_event(self, event):
        self.events.put(('health' if event.get('type')=='connection_health' else 'event',event))

    def send(self, command):
        if not self.live_active or not self.worker or not self.worker.is_alive():
            messagebox.showinfo('尚未連線','請先登入後再操作。',parent=self.root)
            return False
        self.commands.put(command)
        return True

    def select_role(self):
        index=self.role_map.get(self.role_choice.get())
        if index:self.send({'type':'select_role','index':index})

    def open_feature(self,key):
        """Single non-modal window per feature, centered on the main dashboard."""
        self.assert_ui_thread()
        window=self.feature_windows[key]
        if not window.winfo_exists():
            return
        center_on_main(window,self.root,*WINDOWS[key][1:])
        window.deiconify()
        window.lift()
        window.focus_set()
        panel=getattr(self,{
            'party':'party_panel','companion':'companion_panel',
            'expedition':'expedition_panel','instance':'instance_panel',
            'alchemy':'alchemy_panel','crafting':'crafting_panel',
            'efficiency':'efficiency_panel'}[key])
        if key=='instance':
            panel.render(self.snapshot,live=self.live_active)
        elif key=='efficiency':
            panel.update_state(self.snapshot)
        elif hasattr(panel,'render'):
            panel.render(self.snapshot)

    def hide_feature(self,key):
        self.assert_ui_thread()
        window=getattr(self,'feature_windows',{}).get(key)
        if window is not None and window.winfo_exists():
            window.withdraw()

    def hide_all_features(self):
        for key in tuple(getattr(self,'feature_windows',{})):
            self.hide_feature(key)

    def open_instances(self):
        self.open_feature('instance')

    def hide_instances(self):
        self.hide_feature('instance')

    def open_resources(self):
        self.resource_windows.append(ResourceView(self))

    def open_attributes(self):
        view=self.attribute_window
        if view is not None and view.window.winfo_exists():
            view.window.lift()
            view.window.focus_force()
        else:
            self.attribute_window=AttributePointWindow(self)

    def start_roaming(self):
        self.send({'type':'start_roaming'})

    def walk(self):
        if self.map_target_scene is not None and self.snapshot.get('player',{}).get('scene')!=self.map_target_scene:
            messagebox.showinfo('地圖不同','此目的地來自另一張預覽地圖，請重新選點。',parent=self.root);return
        try:self.send({'type':'walk','x':int(self.x.get()),'y':int(self.y.get()),
                       'scene':self.snapshot.get('player',{}).get('scene')})
        except ValueError:messagebox.showinfo('座標','X、Y 請輸入整數。',parent=self.root)

    def refresh_selected(self):
        if self.snapshot and hasattr(self,'home_map'):self.render(self.snapshot)

    def background_window(self):
        try:
            if self.root.state() in ('iconic','withdrawn'):return True
            # ttk popdown widgets exist in Tcl but not Tkinter's widget map.
            # focus_displayof() resolves that map and raises KeyError('popdown').
            return not bool(self.root.tk.call('focus','-displayof',self.root._w))
        except tk.TclError:return True

    def render(self, state):
        self.snapshot=state
        self.chat_panel.update_names(state)
        self.efficiency_panel.state=state;self.overview_panel.state=state
        if self.efficiency_panel.winfo_ismapped():self.efficiency_panel.update_state(state)
        if self.overview_panel.winfo_ismapped():self.overview_panel.update_state(state)
        if self.companion_panel.winfo_ismapped():self.companion_panel.render(state)
        self.expedition_panel.render(state)
        self.instance_panel.render(state, live=self.live_active)
        if self.party_panel.winfo_ismapped():self.party_panel.render(state)
        else:
            requests=sum(v.get('status')=='pending' for v in state.get('party',{}).get('requests',{}).values())
            badge=f'組隊（{requests}）' if requests else '組隊'
            launcher=self.feature_launchers['party']
            if self.left_tabs.tab(launcher,'text')!=badge:
                self.left_tabs.tab(launcher,text=badge)
        if self.party_guard_panel.winfo_ismapped():self.party_guard_panel.update_state(state)
        if self.alchemy_panel.winfo_ismapped():self.alchemy_panel.render(state)
        self.crafting_panel.render(state)
        remaining_resources=[]
        for view in self.resource_windows:
            try:
                if view.window.winfo_exists():view.set_state(state);remaining_resources.append(view)
            except tk.TclError:pass
        self.resource_windows=remaining_resources
        if self.attribute_window is not None and self.attribute_window.window.winfo_exists():
            self.attribute_window.render(state)
        self.ai_status.set(ai_summary(state.get('auto_battle',{})))
        self.roaming_status.set(roaming_summary(state.get('roaming',{})))
        self.home_map.set_state(state)
        check=state.get('movement_check')
        local=state.get('local_movement')
        progress=''
        if local:
            label={'running':'步行中','finished':'路徑處理完成','stopped':'已停止移動'}.get(local['status'],local['status'])
            progress=f"{label}｜座標 ({round(local['x'])}, {round(local['y'])})\n"
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
            displayed=current_position(state)
            if displayed:
                text=f"{player['name']}｜{map_label(displayed['scene'])}｜座標 ({displayed['x']}, {displayed['y']})"
                self.world.set(text)
            else:self.world.set(f"{player['name']}｜{map_label(player['scene'])}｜位置待更新")
        else:self.world.set('尚未收到角色位置')
        if player and displayed:
            self.world_compact.set(f"{player['name']}｜{map_label(displayed['scene'])}｜座標 {displayed['x']}, {displayed['y']}")
        elif player:
            self.world_compact.set(f"{player['name']}｜{map_label(player['scene'])}｜位置待更新")
        else:self.world_compact.set('尚未收到角色位置')
        phase=PHASES.get(state['phase'],'角色狀態待更新')
        flow=state.get('event_flow',{})
        event_status='｜事件尚未結束 '+str(flow.get('last_source')) if flow.get('blocked') else ''
        self.status.set(chinese(phase+f"｜戰鬥 {state['battle_count']} 場／回合 {battle.get('round',0)}"+event_status))
        self.refresh_battle_selection()

    def poll(self):
        self.drain_version_checks()
        failed=False
        try:
            App._poll_once(self)
        except Exception as exc:
            failed=True
            if hasattr(self,'_pending_display'):self._pending_display=None
            try:self.status.set('畫面更新異常，已記錄診斷；將繼續更新連線狀態')
            except Exception:pass
            try:self.root.report_callback_exception(type(exc),exc,exc.__traceback__)
            except Exception:pass
        finally:
            if not getattr(self,'_closing',False):
                try:
                    if hasattr(self,'connection_monitor'):
                        self.connection_status.set(self.connection_monitor.text(bool(self.worker and self.worker.is_alive())))
                except Exception:pass
                try:
                    if self.root.winfo_exists():
                        self.root.after(1000 if failed else 10 if not self.events.empty() else 50,self.poll)
                except tk.TclError:pass

    def _poll_once(self):
        if hasattr(self.events, 'cleanup'):
            removed = self.events.cleanup()
            if removed is not None and hasattr(self, 'diagnostics'):
                self.diagnostics.logger.info('periodic_cleanup display_events_removed=%d', removed)
        latest=None
        status_override=None
        session_finished=False
        started=time.perf_counter()
        deadline=started+0.008
        processed=0
        for _ in range(500):
            if time.perf_counter()>=deadline:break
            try:kind,data=self.events.get_nowait()
            except queue.Empty:break
            processed+=1
            if kind=='health':
                self.connection_monitor.update(data)
                if hasattr(self,'diagnostics'): self.diagnostics.connection(data)
            elif kind=='event' and data.get('type') == 'periodic_cleanup':
                if hasattr(self, 'diagnostics'):
                    self.diagnostics.logger.info('periodic_cleanup positions_removed=%d', data['positions_removed'])
            elif kind=='event' and data.get('type') == 'battle_attribute_invalid':
                if hasattr(self, 'diagnostics'): self.diagnostics.battle_attribute_invalid(data)
            elif kind=='event' and data.get('type') == 'post_battle_trace':
                if hasattr(self, 'diagnostics'): self.diagnostics.post_battle_trace(data)
            elif kind=='event' and data.get('type') == 'coop_state_trace':
                if hasattr(self, 'diagnostics'): self.diagnostics.coop_state_trace(data)
            elif kind=='event' and data.get('type') == 'maintenance_trace':
                if hasattr(self, 'diagnostics'): self.diagnostics.maintenance_trace(data)
            elif kind=='session_finished':session_finished=True
            elif kind=='state':latest=data
            elif kind=='error':
                self.chat_panel.finish_pending()
                self.write('錯誤：'+data);status_override=data
            elif kind=='message':self.write(data);status_override=data
            elif kind=='event':
                event=data;event_kind=event['type']
                if event_kind=='auto_battle_status' and hasattr(self,'diagnostics'):
                    self.diagnostics.auto_battle_status(event)
                context=latest if latest is not None else self.snapshot
                self.chat_panel.handle_event(event,context)
                if (event_kind=='command_rejected' and event.get('command_type')=='allocate_points'
                        and self.attribute_window is not None and self.attribute_window.window.winfo_exists()):
                    self.attribute_window.rejected(event.get('error', '伺服器要求失敗'))
                if event_kind=='command_rejected' and event.get('command_type')=='craft':self.crafting_panel.status.set(event['error'])
                if event_kind=='command_rejected' and event.get('command_type') in ('start_expedition','stop_expedition'):
                    self.expedition_panel.status.set(event['error'])
                if event_kind.startswith('chat_'):continue
                if event_kind=='connection_closed':status_override='連線已關閉'
                for line in local_event_lines(event,context):self.write(line)
        if hasattr(self,'diagnostics'):
            if latest:self._pending_display=latest
            background=self.background_window()
            now=time.monotonic()
            if not background:
                if self._background_logs:
                    lines='\n'.join(self._background_logs);self._background_logs.clear();self.write(lines)
                if self.chat_panel.display_dirty:self.chat_panel.redraw()
            if self._pending_display and (not background or now-self._last_display>=0.5):
                self.render(self._pending_display);self._pending_display=None;self._last_display=now
            self.diagnostics.poll(processed,self.events.qsize(),(time.perf_counter()-started)*1000,background)
        elif latest:self.render(latest)
        if status_override:self.status.set(chinese(status_override))
        if session_finished:
            self.hide_all_features()
            self.live_active=False
            self.password.set('')
            self.update_role_choices([])
            self.show_login()
            # Do not restore a stale role list when reopening after disconnect.
            self.update_role_choices([])
            self._set_login_gate_button()
            self.start_version_check()
        elif latest and self.live_active and latest.get('phase')=='world_ready' and latest.get('player'):
            if not self.entered_world:self.show_main()
        if hasattr(self.events,'take_dropped'):
            dropped=self.events.take_dropped()
            if dropped and hasattr(self,'diagnostics'):self.diagnostics.dropped(dropped)

    def stop(self):
        self.stop_event.set()
        self.status.set('正在中斷連線…')

    def close(self):
        self._closing=True
        self.stop_event.set();self.password.set('');self.diagnostics.close();self.root.destroy()


def main():
    root=tk.Tk();App(root);root.mainloop()


if __name__=='__main__':main()
