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
        self.battle_invalid_count=0;self.battle_invalid_logged=None
        self.ai_status_logged={}
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

    def battle_attribute_invalid(self, value):
        """Rate-limited, numeric-only evidence for a discarded S51-1 update."""
        if not isinstance(value, dict) or value.get('type') != 'battle_attribute_invalid':
            return False
        size, tail = value.get('payload_bytes'), value.get('trailing_bytes')
        if (type(value.get('main')) is not int or value['main'] != 51 or
                type(value.get('sub')) is not int or value['sub'] != 1 or
                type(size) is not int or not 0 <= size <= 65533 or
                type(tail) is not int or not 1 <= tail <= 6 or tail != size % 7):
            return False
        self.battle_invalid_count += 1
        now = time.monotonic()
        if self.battle_invalid_logged is not None and now - self.battle_invalid_logged < 60:
            return False
        self.battle_invalid_logged = now
        self.logger.info(
            'protocol_warning packet_main=51 packet_sub=1 reason=invalid_record_length '
            'payload_bytes=%d complete_records=%d trailing_bytes=%d count=%d',
            size, size // 7, tail, self.battle_invalid_count)
        return True

    def auto_battle_status(self, value):
        """Rate-limited, allowlisted AI state, without roles, skills or commands."""
        allowed = ('disabled', 'armed', 'paused', 'waiting', 'submitted',
                   'blocked', 'healing', 'waiting_heal', 'maintenance')
        if (not isinstance(value, dict) or value.get('type') != 'auto_battle_status'
                or value.get('status') not in allowed
                or type(value.get('enabled')) is not bool
                or type(value.get('battle_active')) is not bool):
            return False
        style, round_number, living = (
            value.get('battle_war_style'), value.get('battle_round'),
            value.get('owned_living'))
        if (style is not None and (type(style) is not int or not 0 <= style <= 255)
                or round_number is not None and
                (type(round_number) is not int or not 0 <= round_number <= 65535)
                or type(living) is not int or not 0 <= living <= 32):
            return False
        status = value['status']
        signature = (status, bool(value['enabled']), bool(value['battle_active']),
                     style, bool(round_number), living)
        now = time.monotonic()
        previous = self.ai_status_logged.get(signature)
        if previous is not None and now - previous < 60:
            return False
        if len(self.ai_status_logged) >= 32:
            self.ai_status_logged.clear()
        self.ai_status_logged[signature] = now
        self.logger.info(
            'auto_battle state=%s enabled=%d battle_active=%d war_style=%s '
            'round=%s owned_living=%d',
            status, value['enabled'], value['battle_active'],
            style if style is not None else 'none',
            round_number if round_number is not None else 'none', living)
        return True

    def post_battle_trace(self, value):
        """Log only allowlisted continuation stages, never packet text or IDs."""
        if not isinstance(value, dict) or value.get('type') != 'post_battle_trace':
            return False
        phase = value.get('phase')
        if phase not in ('scheduled', 'sent', 'completed'):
            return False
        style = value.get('war_style')
        delay = value.get('delay_seconds')
        known = value.get('fight_count_known')
        if (style is not None and (type(style) is not int or not 0 <= style <= 255)
                or delay is not None and
                (type(delay) not in (int, float) or delay not in (2.5, 5.0))
                or type(known) is not bool):
            return False
        self.logger.info('post_battle phase=%s war_style=%s delay_s=%s fight_count_known=%d',
                         phase, style if style is not None else 'none',
                         delay if delay is not None else 'none', known)
        return True

    def dropped(self,count):self.logger.info('display_events_skipped=%d',count)

    def close(self):
        for handler in list(self.logger.handlers):handler.close();self.logger.removeHandler(handler)
