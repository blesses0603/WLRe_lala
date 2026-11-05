"""Select one verified official origin for an entire process.

No arbitrary URL, cross-origin redirect or automatic host fallback is allowed.
Both hosts were observed serving the same PC version metadata on 2026-11-05.
"""
import os

OFFICIAL_HOSTS = ('wlreftp.chinesegamer.net', 'wlreftpsrc.chinesegamer.net')


def selected_host(environ=None):
    environ = os.environ if environ is None else environ
    host = environ.get('WLRE_OFFICIAL_RESOURCE_HOST', OFFICIAL_HOSTS[0])
    if host not in OFFICIAL_HOSTS:
        raise ValueError('Unsupported official resource host')
    return host
