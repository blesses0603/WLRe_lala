"""Numeric UI health metrics only: no accounts, packets, messages or tracebacks."""
import logging,os,time,traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Diagnostics:
    def __init__(self,base=None):
        self.logger=logging.Logger('wlre-health');self.logger.propagate=False
        self.last=0;self.errors=0;self.last_connection=None;self.connection_logged=None;self.last_error=None;self.error_logged=None
        root=Path(base) if base is not None else Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.config')/'WLRE_LaLa'/'diagnostics'
        self.path=root/f'health-{os.getpid()}.log'
        try:
            root.mkdir(parents=True,exist_ok=True)
            handler=RotatingFileHandler(self.path,maxBytes=1024*1024,backupCount=2,encoding='utf8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self.logger.addHandler(handler)
        except OSError:pass

    def poll(self,processed,backlog,milliseconds,background):
        now=time.monotonic()
        if now-self.last<5:return
        self.last=now
        self.logger.info('processed=%d backlog=%d ui_ms=%.2f background=%d errors=%d',processed,backlog,milliseconds,bool(background),self.errors)

    def error(self,exc_type=None,exc_value=None,tb=None):
        self.errors+=1
        frames=traceback.extract_tb(tb) if tb is not None else []
        # Do not log exception messages, source text, locals, or user directory paths.
        locations=' > '.join(f'{Path(f.filename).name}:{f.lineno}:{f.name}' for f in frames[-6:])
        kind=exc_type.__name__ if exc_type is not None else 'unknown'
        signature=(kind,locations);now=time.monotonic()
        if signature==self.last_error and self.error_logged is not None and now-self.error_logged<60:return False
        self.last_error=signature;self.error_logged=now
        self.logger.info('ui_callback_error count=%d type=%s frames=%s',self.errors,kind,locations)
        return True

    def connection(self,value):
        now=time.monotonic();key=(value.get('status'),value.get('reason'),value.get('errno'))
        if key==self.last_connection and self.connection_logged is not None and now-self.connection_logged<300:return
        self.last_connection=key;self.connection_logged=now
        # Fixed enums and numeric values only; no packet contents or login data.
        status=value.get('status') if value.get('status') in ('waiting','receiving','quiet','closed') else 'unknown'
        reason=value.get('reason') if value.get('reason') in ('server_closed','network_error','client_error','stopped','duration') else 'none'
        self.logger.info('connection=%s reason=%s age_s=%.1f packets=%d errno=%s keepalive=%d',
            status,reason,float(value.get('age',0)),int(value.get('packets',0)),
            value.get('errno') if isinstance(value.get('errno'),int) else 'none',bool(value.get('keepalive')))

    def dropped(self,count):self.logger.info('display_events_skipped=%d',count)

    def close(self):
        for handler in list(self.logger.handlers):handler.close();self.logger.removeHandler(handler)
