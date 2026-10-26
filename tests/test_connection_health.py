import sys
import errno
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch
from wlre.network.connection_health import ConnectionHealth, configure_keepalive
from wlre.ui.connection_status import ConnectionStatus
from wlre.ui.event_queue import DisplayQueue
from wlre.core.diagnostics import Diagnostics


class Clock:
    def __init__(self): self.now=0; self.wall=1700000000
    def mono(self):return self.now
    def utc(self):return self.wall+self.now


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.events=[]
        self.health=ConnectionHealth(self.events.append,clock=self.clock.mono,wall=self.clock.utc)
    def test_silence_is_uncertain_and_resume_recovers_without_logout(self):
        self.health.publish();self.assertEqual(self.events[-1]['status'],'waiting')
        self.health.received();self.health.publish(force=True)
        self.assertEqual(self.events[-1]['status'],'receiving')
        self.clock.now=121;self.health.publish()
        self.assertEqual(self.events[-1]['status'],'quiet');self.assertFalse(self.health.closed)
        self.health.received();self.health.publish(force=True)
        self.assertEqual(self.events[-1]['status'],'receiving')
        self.assertEqual(self.events[-1]['age'],0)
    def test_simulated_twelve_hours_and_wall_clock_change(self):
        mailbox=DisplayQueue()
        self.health.emit=lambda e:mailbox.put(('health',e))
        for tick in range(0,43201,10):
            self.clock.now=tick;self.health.received();self.health.publish()
        self.assertEqual(mailbox.qsize(),1)
        self.assertEqual(mailbox.get_nowait()[1]['packets'],4321)
        self.clock.wall-=86400;self.clock.now+=10;self.health.publish()
        self.assertEqual(mailbox.get_nowait()[1]['age'],10)
        self.assertFalse(self.health.closed)
    def test_closed_reason_and_errno_without_exception_text(self):
        self.health.close('network_error',OSError(errno.ECONNRESET,'secret credentials'))
        event=self.events[-1]
        self.assertEqual(event['status'],'closed');self.assertEqual(event['errno'],errno.ECONNRESET)
        self.assertNotIn('secret',str(event))
    def test_client_error_contains_only_safe_code_locations(self):
        def fail():
            raise RuntimeError('password=fixture-secret, packet=secret-payload')
        try: fail()
        except RuntimeError as exc:
            self.health.close('client_error',exc)
        event=self.events[-1]
        self.assertEqual(event['error_type'],'RuntimeError')
        self.assertIn('test_connection_health.py:',event['error_frames'])
        self.assertNotIn('fixture-secret',str(event))
        self.assertNotIn('secret-payload',str(event))
        with tempfile.TemporaryDirectory() as directory:
            health_log=Diagnostics(directory)
            health_log.connection(event)
            health_log.close()
            text=health_log.path.read_text(encoding='utf8')
            self.assertIn('connection_exception type=RuntimeError',text)
            self.assertIn('test_connection_health.py:',text)
            self.assertNotIn('fixture-secret',text)
            self.assertNotIn('secret-payload',text)

    def test_packet_attribution_excludes_payload_and_untrusted_fields(self):
        def fail():
            raise ValueError('secret-account-content')
        try: fail()
        except ValueError as exc:
            self.health.close('client_error',exc,error_packet=(31,19),error_stage='decode')
        event=self.events[-1]
        self.assertEqual((event['packet_main'],event['packet_sub'],event['packet_stage']),
                         (31,19,'decode'))
        self.assertNotIn('secret-account-content',str(event))
        with tempfile.TemporaryDirectory() as directory:
            d=Diagnostics(directory);d.connection(event);d.close()
            logged=d.path.read_text(encoding='utf8')
            self.assertIn('packet_main=31 packet_sub=19 packet_stage=decode',logged)
            self.assertNotIn('secret-account-content',logged)

        # The handler must omit unknown/untrusted packet context.
        for bad in ((-1,19),(256,19),(True,19),('secret',19),(31,),None):
            with self.subTest(bad=bad):
                other=ConnectionHealth(self.events.append,clock=self.clock.mono,wall=self.clock.utc)
                try: fail()
                except ValueError as exc:
                    other.close('client_error',exc,error_packet=bad,error_stage='decode')
                self.assertNotIn('packet_main',self.events[-1])
        no_context=ConnectionHealth(self.events.append,clock=self.clock.mono,wall=self.clock.utc)
        no_context.close('server_closed',error_packet=(31,19),error_stage='decode')
        self.assertNotIn('packet_main',self.events[-1])

    def test_ui_ages_data_even_when_worker_stops_publishing(self):
        monitor=ConnectionStatus(clock=self.clock.mono)
        self.health.received();self.health.publish(force=True);monitor.update(self.events[-1])
        self.assertIn('伺服器有回應',monitor.text(True))
        self.clock.now=130
        self.assertIn('連線待確認',monitor.text(True))
        self.assertIn('130 秒前',monitor.text(True))
        self.assertIn('作業已停止',monitor.text(False))
        self.health.close('server_closed');monitor.update(self.events[-1])
        self.assertEqual(monitor.text(False),'伺服器已關閉連線')
    def test_bounded_display_queue_does_not_block_or_drop_terminal_status(self):
        q=DisplayQueue(limit=32)
        q.put(('event',{'type':'connection_closed'}));q.put(('session_finished',None))
        for i in range(100000):
            q.put(('state',{'packet_count':i}));q.put(('event',{'type':'walk','index':i}))
            q.put(('health',{'status':'quiet','age':i}))
        self.assertEqual(q.qsize(),36)
        self.assertEqual(q.get_nowait()[0],'health')
        self.assertEqual(q.get_nowait()[1]['packet_count'],99999)
        values=[]
        while not q.empty():values.append(q.get_nowait())
        self.assertIn(('session_finished',None),values)
        self.assertIn(('event',{'type':'connection_closed'}),values)
        self.assertEqual(q.take_dropped(),99968);self.assertEqual(q.take_dropped(),0)
        with self.assertRaises(queue.Empty):q.get_nowait()
    def test_keepalive_tolerates_os_without_interval_options(self):
        connection=Mock();connection.setsockopt.side_effect=[None,OSError(),OSError(),OSError()]
        self.assertTrue(configure_keepalive(connection))
        connection.setsockopt.side_effect=OSError()
        self.assertFalse(configure_keepalive(connection))
    def test_connection_log_records_numeric_evidence_only(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Diagnostics(directory)
            d.connection(dict(status='quiet',reason='secret password',age=121,packets=100,errno=None,keepalive=True))
            d.close();text=d.path.read_text(encoding='utf8')
            self.assertIn('connection=quiet',text);self.assertIn('age_s=121.0',text)
            self.assertNotIn('password',text)


class ClientHealthIntegration(unittest.TestCase):
    def test_network_silence_recovery_and_eof_reach_ui(self):
        from wlre.network.client import run_client
        from wlre.network.wire import Packet
        clock=Clock();events=[];snapshots=[];connection=Mock()
        connection.__enter__=Mock(return_value=connection);connection.__exit__=Mock(return_value=False)
        def recv(_):
            clock.now+=61
            if clock.now in (61,122):raise __import__('socket').timeout()
            if clock.now==183:return b'frame'
            return b''
        connection.recv.side_effect=recv
        parser=Mock();parser.feed.return_value=[Packet(63,5,b'')]
        factory=lambda emit:ConnectionHealth(emit,clock=clock.mono,wall=clock.utc)
        with patch('wlre.network.client.socket.create_connection',return_value=connection),patch('wlre.network.client.FrameDecoder',return_value=parser),patch('wlre.network.client.decode',return_value={'type':'heartbeat_request'}),patch('wlre.network.client.ConnectionHealth',side_effect=factory):
            state=run_client('fixture.invalid',1,{'rx_xor':0,'tx_xor':0},events.append,duration=None,on_state=snapshots.append,tcp_keepalive=True)
        statuses=[e['status'] for e in events if e['type']=='connection_health']
        self.assertIn('quiet',statuses);self.assertIn('receiving',statuses);self.assertEqual(statuses[-1],'closed')
        self.assertEqual(events[-1]['reason'],'server_closed')
        self.assertEqual(state.phase,'disconnected');self.assertEqual(snapshots[-1]['phase'],'disconnected')

    def test_uncaught_client_error_is_visible_to_diagnostics(self):
        from wlre.network.client import run_client
        connection=Mock()
        connection.__enter__=Mock(return_value=connection)
        connection.__exit__=Mock(return_value=False)
        connection.recv.side_effect=ValueError('fixture-password must never appear in logs')
        events=[]
        with patch('wlre.network.client.socket.create_connection',return_value=connection):
            with self.assertRaises(ValueError):
                run_client('fixture.invalid',1,{'rx_xor':0,'tx_xor':0},events.append,duration=None)
        terminal=[event for event in events if event.get('type')=='connection_health' and event['status']=='closed']
        self.assertEqual(len(terminal),1)
        self.assertEqual(terminal[0]['reason'],'client_error')
        self.assertEqual(terminal[0]['error_type'],'ValueError')
        self.assertIn('client.py:',terminal[0]['error_frames'])
        self.assertNotIn('fixture-password',str(terminal[0]))
        self.assertEqual(events[-1]['type'],'connection_closed')


    def test_truncated_expedition_update_reports_packet_number_instead_of_payload(self):
        from wlre.network.client import run_client
        from wlre.network.wire import Packet, encode, ProtocolError
        # The 1262 S31-19 packet requires 50 entries plus one Boolean.
        # Deliberately omit the Boolean and verify the failure is attributable.
        entries=b''.join(bytes((i,0,0)) for i in range(1,51))
        connection=Mock()
        connection.__enter__=Mock(return_value=connection)
        connection.__exit__=Mock(return_value=False)
        connection.recv.side_effect=[encode(Packet(31,19,entries),0)]
        events=[]
        with patch('wlre.network.client.socket.create_connection',return_value=connection):
            with self.assertRaises(ProtocolError):
                run_client('fixture.invalid',1,{'rx_xor':0,'tx_xor':0},events.append,duration=None)
        terminal=[e for e in events if e.get('status')=='closed' and e.get('type')=='connection_health']
        self.assertEqual(len(terminal),1)
        self.assertEqual(terminal[0]['reason'],'client_error')
        self.assertEqual((terminal[0]['packet_main'],terminal[0]['packet_sub'],terminal[0]['packet_stage']),
                         (31,19,'decode'))
        self.assertIn('expedition.py:',terminal[0]['error_frames'])
        self.assertNotIn('payload',str(terminal[0]))
        self.assertEqual(events[-1]['reason'],'client_error')

    def test_failed_state_apply_reports_own_stage_not_decode(self):
        from wlre.network.client import run_client
        from wlre.network.wire import Packet,encode
        from wlre.core.state import State
        connection=Mock()
        connection.__enter__=Mock(return_value=connection)
        connection.__exit__=Mock(return_value=False)
        connection.recv.side_effect=[encode(Packet(63,5),0)]
        events=[]
        with (patch('wlre.network.client.socket.create_connection',return_value=connection),
              patch.object(State,'apply',side_effect=ValueError('secret-state'))):
            with self.assertRaises(ValueError):
                run_client('fixture.invalid',1,{'rx_xor':0,'tx_xor':0},events.append,duration=None)
        terminal=[e for e in events if e.get('status')=='closed' and e.get('type')=='connection_health']
        self.assertEqual(len(terminal),1)
        self.assertEqual((terminal[0]['packet_main'],terminal[0]['packet_sub'],terminal[0]['packet_stage']),
                         (63,5,'state_apply'))
        self.assertNotIn('secret-state',str(terminal[0]))

class PollRecovery(unittest.TestCase):
    def test_callback_failure_does_not_end_polling_and_next_cycle_recovers(self):
        from collections import deque
        from types import SimpleNamespace
        from wlre.ui.gui import App
        events=queue.Queue();events.put(('state',{'value':1}))
        app=SimpleNamespace(events=events,diagnostics=Mock(),root=Mock(),poll=Mock(),
            status=Mock(),_pending_display=None,_last_display=0,_background_logs=deque(),
            background_window=Mock(return_value=False),chat_panel=SimpleNamespace(display_dirty=False),
            render=Mock(side_effect=RuntimeError('fixture error')),live_active=False)
        App.poll(app)
        app.root.report_callback_exception.assert_called_once()
        app.root.after.assert_called_with(1000,app.poll)
        self.assertIsNone(app._pending_display)
        app.render.side_effect=None;events.put(('state',{'value':2}))
        App.poll(app)
        self.assertEqual(app.render.call_args.args[0],{'value':2})
        app.root.after.assert_called_with(50,app.poll)
    def test_background_exception_written_to_health_log_without_message(self):
        from types import SimpleNamespace
        from wlre.ui.gui import App
        with tempfile.TemporaryDirectory() as directory:
            diagnostics=Diagnostics(directory)
            app=SimpleNamespace(worker=None,events=queue.Queue(),diagnostics=diagnostics)
            def failure_before_session():
                raise RuntimeError('login-password=fixture-secret')
            self.assertTrue(App.background(app,failure_before_session))
            app.worker.join(timeout=5)
            self.assertFalse(app.worker.is_alive())
            diagnostics.close()
            text=diagnostics.path.read_text(encoding='utf8')
            self.assertIn('worker_exception count=1 type=RuntimeError',text)
            self.assertIn('test_connection_health.py:',text)
            self.assertNotIn('fixture-secret',text)
            self.assertEqual(app.events.get_nowait()[0],'error')
            self.assertEqual(app.events.get_nowait()[0],'finished')

    def test_health_log_records_location_without_error_message(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Diagnostics(directory)
            try:raise RuntimeError('fixture-secret-password')
            except RuntimeError as exc:
                self.assertTrue(d.error(type(exc),exc,exc.__traceback__))
                self.assertFalse(d.error(type(exc),exc,exc.__traceback__))
            d.close();text=d.path.read_text(encoding='utf8')
            self.assertIn('RuntimeError',text);self.assertIn('test_connection_health.py',text)
            self.assertNotIn('fixture-secret',text);self.assertEqual(d.errors,2)


import os
@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt' or sys.platform == 'darwin','Requires Tk display')
class NativeFocusRegression(unittest.TestCase):
    def test_native_combobox_popdown_does_not_stop_background_detection(self):
        import tkinter as tk
        from tkinter import ttk
        from types import SimpleNamespace
        from wlre.ui.gui import App
        root=tk.Tk();self.addCleanup(root.destroy)
        combo=ttk.Combobox(root,values=['A','B']);combo.pack();root.update()
        root.tk.call('ttk::combobox::Post',str(combo));root.update()
        root.tk.call('focus','-force',str(combo)+'.popdown.f.l');root.update()
        self.assertIn('popdown',str(root.tk.call('focus','-displayof',root._w)))
        with self.assertRaises(KeyError):root.focus_displayof()
        self.assertFalse(App.background_window(SimpleNamespace(root=root)))
