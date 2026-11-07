"""Actual application/UI entry smoke in an existing seed-isolated workspace."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def _desktop_startup_ready(app, observations, online):
    """Wait for the worker AND its Tk receipt; never infer success from a window."""
    if not app._version_worker_done.is_set():
        return False
    if not app._startup_prepared.is_set() or not observations.get('launcher_completed'):
        raise AssertionError('Resource preparation did not complete through the monitored entry')
    if app.version_gate_state == 'checking':
        return False  # The main-thread poll has not consumed the official result yet.
    result = app._version_gate_result
    if not isinstance(result, dict):
        raise AssertionError('Official verification returned no terminal result')
    from wlre.ui.version_gate_controller import _is_verified_login_result
    verified = _is_verified_login_result(result)
    observations['official_result'] = {
        key: result.get(key) for key in ('status', 'blocked', 'database_comparison',
                                         'database_verified', 'login_allowed')}
    observations['official_login_verified'] = verified
    observations['startup_checks_completed'] = True
    receipt = observations.get('launcher_result')
    if not isinstance(receipt, dict) or receipt.get('status') not in (
            'verified_official', 'downloaded_unparsed', 'skipped'):
        raise AssertionError('Resource preparation failed; see launcher_result/launcher_error')
    if online and receipt.get('status') == 'skipped':
        raise AssertionError('Online resource preparation was unexpectedly skipped')
    if online and not verified:
        raise AssertionError('Official verification did not pass; see official_result')
    if not online and result.get('blocked') is not True:
        raise AssertionError('Offline smoke unexpectedly allowed official login')
    return True


def check(workspace,platform,online=False):
    workspace=Path(workspace).resolve()
    if (workspace/'source/wlre/resources/resource_catalog_seed.sqlite3').exists():raise ValueError('Seed is not isolated')
    if not (workspace/'isolation.json').is_file():raise ValueError('Not an isolation workspace')
    attempts=[];connections=[];legacy_accesses=[]
    forbidden_names={"resource_catalog_seed.sqlite3","navigation_data.zip","graph_origins.json","stage_coordinates.json"}
    from urllib.parse import urlsplit
    import socket
    proxies=set()
    proxy=os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    if online and proxy:
        u=urlsplit(proxy)
        proxies={(r[4][0],r[4][1]) for r in socket.getaddrinfo(u.hostname,u.port or 80,type=socket.SOCK_STREAM)}
    def audit(event,args):
        if event in ('open','sqlite3.connect') and args and isinstance(args[0],(str,bytes,os.PathLike)):
            name=os.fsdecode(args[0])
            if name.startswith('file:'):
                from urllib.request import url2pathname
                name=url2pathname(urlsplit(name).path)
            if Path(name).name in forbidden_names:
                legacy_accesses.append(Path(name).name)
                raise PermissionError('Cold-start smoke forbids retired navigation seed reads')
        if event=='urllib.Request':
            url=urlsplit(args[0])
            if online and url.scheme=='https' and url.hostname in ('wlreftpsrc.chinesegamer.net','wlreftp.chinesegamer.net','cgdl.chinesegamer.net','api.github.com'):
                return
            attempts.append(dict(event=event,host=url.hostname))
            raise PermissionError('Cold-start smoke blocked request')
        if event=='socket.connect':
            target=args[1]
            if online and isinstance(target,tuple) and (target[1]==443 or target[:2] in proxies):
                connections.append('https_transport');return
            attempts.append(dict(event=event,host=None));raise PermissionError('Cold-start smoke blocked socket')
    sys.addaudithook(audit)
    if platform=='desktop':
        from unittest.mock import patch
        import tkinter as tk
        import WLRE_Client
        from wlre.ui import gui, version_gate_controller
        from wlre.ui.official_navigation_preview import OfficialNavigationPreview
        errors=[];observations={};real_app=gui.App
        def build(root):
            root.report_callback_exception=lambda *args:errors.append(str(args))
            app=real_app(root)
            deadline=time.monotonic()+(420 if online else 30)
            def exercise():
                try:
                    app.show_main();root.update_idletasks()
                    observations['dashboard_mapped']=bool(app.overview_panel.winfo_ismapped())
                    dialogs=[]
                    def preview(*args, **kwargs):
                        result=OfficialNavigationPreview(*args, **kwargs);dialogs.append(result);return result
                    with patch('wlre.ui.official_navigation_preview.OfficialNavigationPreview',side_effect=preview):
                        app.open_navigation()
                    if len(dialogs)!=1:raise AssertionError('Missing independent official preview')
                    from wlre.services.world.dynamic_bundle_runtime import current_runtime
                    runtime=current_runtime()
                    observations['runtime_catalog_key']=runtime.catalog_identity.key if runtime is not None else None
                    if runtime is None:
                        dialogs[0].run(False)
                        if not dialogs[0].validation_error:raise AssertionError('Cold runtime unexpectedly available')
                        observations['preview_safe_stop']=dialogs[0].validation_error
                    else:
                        observations['runtime_stages']=len(runtime.stages)
                    dialogs[0].close()
                except Exception as error:errors.append(type(error).__name__+': '+str(error))
                finally:app.close()
            def wait_for_startup():
                try:
                    if time.monotonic()>deadline:
                        raise TimeoutError('Resource preparation/official verification did not complete')
                    if not _desktop_startup_ready(app,observations,online):
                        root.after(50,wait_for_startup)
                        return
                except Exception as error:
                    errors.append(type(error).__name__+': '+str(error))
                    app.close()
                    return
                exercise()
            root.after(100,wait_for_startup)
            return app
        # App imported this callable by value. Patch its actual lookup site,
        # not launcher_catalog, which no longer owns the desktop entry point.
        real_prepare=version_gate_controller.prepare_on_launch
        phases=[]
        observations['launcher_phases']=phases
        def launch(**kwargs):
            progress=kwargs.get('progress')
            def record(phase,details):
                phases.append(phase)
                if progress:progress(phase,details)
            kwargs['progress']=record
            try:
                result=real_prepare(**kwargs)
                observations['launcher_result']=result
                return result
            except Exception as error:
                observations['launcher_error']=type(error).__name__
                raise
            finally:
                observations['launcher_completed']=True
        with patch.object(gui,'App',side_effect=build), patch.object(version_gate_controller,'prepare_on_launch',side_effect=launch):
            code=WLRE_Client.main()
        if code or errors or not observations.get('startup_checks_completed') or not observations.get('dashboard_mapped'):
            failure=dict(platform='desktop',status='failed',returncode=code,errors=errors,
                         observations=observations,online_bootstrap=online,
                         actual_game_login=False,can_send_packets=False)
            (workspace/'cold-start.json').write_text(json.dumps(failure,indent=2))
            raise AssertionError(failure)
    else:
        import main
        from kivy.clock import Clock
        from types import SimpleNamespace
        from android_app.navigation_preview_ui import open_navigation_preview
        app=main.LaLaApp();errors=[];observations={}
        def exercise(dt):
            try:
                observations['login_root_built']=app.root is not None
                panel=app._build_verification_view()
                observations['verification_widgets_built']=panel is not None
                popup=open_navigation_preview(SimpleNamespace(state={}))
                buttons=[w for w in popup.walk() if getattr(w,'text',None)=='從資料庫預覽']
                if len(buttons)!=1:raise AssertionError('Preview button unavailable')
                buttons[0].dispatch('on_release')
                observations['preview_opened']=True
                observations['sessions']=len(app.manager.sessions)
                popup.dismiss()
            except Exception as error:errors.append(type(error).__name__+': '+str(error))
            finally:app.stop()
        Clock.schedule_once(exercise,.3);app.run()
        if errors or not observations.get('login_root_built') or observations.get('sessions')!=0:raise AssertionError((errors,observations))
    if legacy_accesses:raise AssertionError('Unexpected retired navigation read: '+str(legacy_accesses))
    if any(x['event']=='socket.connect' for x in attempts):raise AssertionError('Unexpected socket connection attempt')
    return dict(platform=platform,observations=observations,blocked_metadata_requests=attempts,https_transport_connections=len(connections),online_bootstrap=online,seed_present=False,legacy_navigation_reads=0,
                actual_game_login=False,can_send_packets=False,
                scope='Actual application host entry and UI smoke; native Android service/device and live gameplay not tested.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--online',action='store_true');p.add_argument('--platform',choices=('desktop','android'),required=True);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args();workspace=a.workspace.resolve()
    if a.worker:
        result=check(workspace,a.platform,a.online);(workspace/'cold-start.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return
    if not (workspace/'isolation.json').is_file():raise ValueError('Not an isolation workspace')
    target=workspace/'source/tools/check_isolated_application.py';shutil.copyfile(__file__,target)
    data=workspace/'app-cold'
    if data.exists():raise ValueError('Use an untested workspace for a real cold start')
    data.mkdir()
    env={**os.environ,'LOCALAPPDATA':str(data),'KIVY_HOME':str(data/'kivy'),'PYTHONPATH':str(workspace/'source'),
         'WLRE_DISABLE_AUTO_CATALOG':'1','PYTHONDONTWRITEBYTECODE':'1','KIVY_NO_ARGS':'1'}
    command=[sys.executable,'-B',str(target),'--worker','--workspace',str(workspace),'--platform',a.platform]
    if a.online:
        env.pop('WLRE_DISABLE_AUTO_CATALOG',None);command.append('--online')
    subprocess.run(command,cwd=workspace/'source',env=env,timeout=480 if a.online else 60,check=True)


if __name__=='__main__':main()
