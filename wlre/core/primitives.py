"""新核心共用限制；不依賴既有遊戲 State、GUI 或平台 API。"""
from __future__ import annotations

import math
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from threading import get_ident

_IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')


def identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError('invalid_core_identifier')
    return value


class Owned:
    """只有建立物件的執行緒可以使用擁有者 API。"""

    def __init__(self):
        self._owner = get_ident()

    def assert_owner(self):
        if get_ident() != self._owner:
            raise RuntimeError('core_thread_ownership_violation')


def require_immutable(value):
    """拒絕可變資料及任意物件；限制深度、節點數及單值大小。"""
    remaining = 8192
    bytes_remaining = 1024 * 1024

    def check(item, depth):
        nonlocal remaining, bytes_remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError('core_value_too_complex')
        if item is None or type(item) in (bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) in (str, bytes):
            bytes_remaining -= len(item.encode('utf-8')) if type(item) is str else len(item)
            if bytes_remaining < 0:
                raise ValueError('core_value_too_large')
            return
        if isinstance(item, Enum):
            check(item.value, depth + 1)
            return
        if type(item) in (tuple, frozenset):
            for child in item:
                check(child, depth + 1)
            return
        if (not isinstance(item, type) and is_dataclass(item)
                and item.__dataclass_params__.frozen):
            for field in fields(item):
                check(getattr(item, field.name), depth + 1)
            return
        raise TypeError('core_value_must_be_immutable')

    check(value, 0)
