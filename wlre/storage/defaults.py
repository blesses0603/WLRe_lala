"""Code-owned non-credential connection settings from the owner's capture."""
from wlre.paths import RESOURCE_ROOT  # Retained for no-seed compatibility probes.
from wlre.network.wire import ProtocolError


def load_default_profile():
    from copy import deepcopy
    from wlre.configuration import DEFAULT_PROFILE
    profile = deepcopy(DEFAULT_PROFILE)
    allowed = {'rx_xor','tx_xor','platform','language','verification_endpoint','game_endpoint',
               'capture_sha256','observed_packets','evidence'}
    if set(profile) - allowed:
        raise ProtocolError('default profile contains unsupported fields')
    for key in ('verification_endpoint','game_endpoint'):
        endpoint = profile[key]
        if set(endpoint) != {'host','port'} or not endpoint['host'] or not 1 <= endpoint['port'] <= 65535:
            raise ProtocolError('invalid default endpoint')
    for key in ('rx_xor','tx_xor','platform','language'):
        if type(profile[key]) is not int or not 0 <= profile[key] <= 255:
            raise ProtocolError('invalid default protocol setting')
    return profile
