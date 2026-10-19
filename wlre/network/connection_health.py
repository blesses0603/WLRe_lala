"""Transport evidence only; silence is uncertain, never proof of logout."""
import socket
import time
from wlre.core.diagnostics import safe_exception_location

QUIET_AFTER = 120


def configure_keepalive(connection):
    """Use OS TCP probes, not invented game packets. Unsupported tuning is optional."""
    try: connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except (AttributeError, OSError): return False
    tuned = False
    for name, value in (('TCP_KEEPIDLE', 60), ('TCP_KEEPINTVL', 15), ('TCP_KEEPCNT', 4)):
        option = getattr(socket, name, None)
        if option is not None:
            try:
                connection.setsockopt(socket.IPPROTO_TCP, option, value)
                if name == 'TCP_KEEPIDLE': tuned = True
            except OSError: pass
    if not tuned and hasattr(socket, 'SIO_KEEPALIVE_VALS'):
        try: connection.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 60000, 15000))
        except (AttributeError, OSError): pass
    return True


class ConnectionHealth:
    def __init__(self, emit, clock=time.monotonic, wall=time.time, quiet_after=QUIET_AFTER, interval=1):
        self.emit, self.clock, self.wall = emit, clock, wall
        self.started = clock(); self.last_packet = None; self.last_received_at = None
        self.last_emit = None; self.packets = 0; self.quiet_after = quiet_after; self.interval = interval
        self.keepalive = False; self.closed = False

    def received(self):
        self.last_packet = self.clock(); self.last_received_at = self.wall(); self.packets += 1

    def publish(self, force=False, reason=None, error=None):
        now = self.clock()
        if not force and self.last_emit is not None and now-self.last_emit < self.interval: return
        self.last_emit = now
        age = max(0, now-(self.last_packet if self.last_packet is not None else self.started))
        status = ('closed' if self.closed else 'quiet' if age >= self.quiet_after else
                  'receiving' if self.last_packet is not None else 'waiting')
        event=dict(type='connection_health', status=status, age=age,
            last_received_at=self.last_received_at, packets=self.packets, keepalive=self.keepalive,
            reason=reason, error_type=type(error).__name__ if error is not None else None,
            errno=getattr(error, 'errno', None))
        if self.closed and error is not None:
            # A code location is useful for client_error; exception text and locals are private.
            event['error_type'],event['error_frames']=safe_exception_location(
                type(error),error.__traceback__)
        self.emit(event)

    def close(self, reason, error=None):
        self.closed = True
        self.publish(force=True, reason=reason, error=error)
