"""Validate queued UI command envelopes before dispatch on the network thread.

Individual command validators continue to own game-specific argument checks.
Only public type metadata is used for rejection logs: never echo credentials
or arbitrary payloads back into error text.
"""
from collections.abc import Mapping
from wlre.network.wire import ProtocolError


def validate_command(command):
    if not isinstance(command, Mapping):
        raise ProtocolError('指令格式錯誤：預期含有 type 的資料物件')
    name = command.get('type')
    if not isinstance(name, str) or not name or len(name) > 64:
        raise ProtocolError('指令格式錯誤：type 必須是有效的指令名稱')
    return name


def rejected_command_type(command):
    """A bounded, nonsecret name suitable for user-visible diagnostics."""
    if not isinstance(command, Mapping):
        return 'invalid'
    name = command.get('type')
    if isinstance(name, str) and name.isascii() and len(name) <= 64 and name.replace('_', '').isalnum():
        return name
    return 'invalid'
