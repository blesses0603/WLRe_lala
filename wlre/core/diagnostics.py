"""Numeric UI health metrics only: no accounts, packets, messages or tracebacks."""
import logging,os,time
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Diagnostics:
    def __init__(self,base=None):
        self.logger=logging.Logger('wlre-health');self.logger.propagate=False
        self.last=0;self.errors=0
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

    def error(self):
        self.errors+=1
        self.logger.info('ui_callback_error count=%d',self.errors)

    def close(self):
        for handler in list(self.logger.handlers):handler.close();self.logger.removeHandler(handler)
