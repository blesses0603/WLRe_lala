"""Privacy-safe runtime diagnostics: counters and code locations, never exception text."""
from collections import deque
from wlre.storage.paths import data_root as user_data_root
import logging,os,time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def safe_exception_location(exc_type, tb):
    """Return only the exception class and the last six code locations.

    Do not format the exception or inspect frame locals, source lines, or payloads.
    """
    kind = getattr(exc_type, '__name__', 'unknown')
    frames = deque(maxlen=6)
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(f'{Path(code.co_filename).name}:{tb.tb_lineno}:{code.co_name}')
        tb = tb.tb_next
    return kind, ' > '.join(frames) if frames else 'none'


class Diagnostics:
    def __init__(self,base=None):
        self.logger=logging.Logger('wlre-health');self.logger.propagate=False
        self.last=0;self.errors=0;self.worker_errors=0
        self.last_connection=None;self.connection_logged=None;self.last_error=None;self.error_logged=None
        root=Path(base) if base is not None else user_data_root()/'diagnostics'
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
        kind,locations=safe_exception_location(exc_type,tb)
        signature=(kind,locations);now=time.monotonic()
        if signature==self.last_error and self.error_logged is not None and now-self.error_logged<60:return False
        self.last_error=signature;self.error_logged=now
        self.logger.info('ui_callback_error count=%d type=%s frames=%s',self.errors,kind,locations)
        return True

    def worker_error(self,exc_type=None,tb=None):
        """Catch failures before, during, or after a network session."""
        self.worker_errors+=1
        kind,locations=safe_exception_location(exc_type,tb)
        self.logger.info('worker_exception count=%d type=%s frames=%s',self.worker_errors,kind,locations)

    def connection(self,value):
        now=time.monotonic();key=(value.get('status'),value.get('reason'),value.get('errno'))
        if key==self.last_connection and self.connection_logged is not None and now-self.connection_logged<300:return
        self.last_connection=key;self.connection_logged=now
        status=value.get('status') if value.get('status') in ('waiting','receiving','quiet','closed') else 'unknown'
        reason=value.get('reason') if value.get('reason') in ('server_closed','network_error','client_error','stopped','duration') else 'none'
        self.logger.info('connection=%s reason=%s age_s=%.1f packets=%d errno=%s keepalive=%d',
            status,reason,float(value.get('age',0)),int(value.get('packets',0)),
            value.get('errno') if isinstance(value.get('errno'),int) else 'none',bool(value.get('keepalive')))
        # These fields are generated from traceback code objects, never from error strings.
        if status=='closed' and reason in ('client_error','network_error') and value.get('error_type'):
            # Never trust arbitrary event strings as log metadata.
            main, sub = value.get('packet_main'), value.get('packet_sub')
            stage = value.get('packet_stage')
            if (type(main) is int and 0 <= main <= 255 and
                    type(sub) is int and 0 <= sub <= 255 and
                    stage in ('decode', 'state_apply', 'event_handling')):
                self.logger.info('connection_exception type=%s frames=%s packet_main=%d packet_sub=%d packet_stage=%s',
                    value['error_type'],value.get('error_frames','none'),main,sub,stage)
            else:
                self.logger.info('connection_exception type=%s frames=%s',
                    value['error_type'],value.get('error_frames','none'))

    def dropped(self,count):self.logger.info('display_events_skipped=%d',count)

    def close(self):
        for handler in list(self.logger.handlers):handler.close();self.logger.removeHandler(handler)
