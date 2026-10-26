"""P4: Session display-event coordination on the Tk thread.

Read worker-originated session mailbox messages, update UI projections and
diagnostics, and restore the login view at session completion. TCP, State,
command processing and the Tk scheduling loop retain their existing owners.
This method is inherited by App for backward-compatible callers.
"""
import queue
import time

from wlre.core.event_log import lines as local_event_lines, chinese


class SessionEventCoordinator:
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

