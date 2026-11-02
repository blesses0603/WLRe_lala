"""Retired candidate ZIP bridge; official sources must be independently verified."""

class FormalBridgeError(ValueError):
    """Legacy candidate ZIP promotion is disabled."""

def inspect_launcher_candidate(*args, **kwargs):
    raise FormalBridgeError('Legacy candidate ZIP bridge is retired')

def inspect_formal_bridge(*args, **kwargs):
    raise FormalBridgeError('Legacy candidate ZIP bridge is retired')

def promote_reviewed_archives(*args, **kwargs):
    raise FormalBridgeError('Legacy candidate ZIP promotion is disabled')
