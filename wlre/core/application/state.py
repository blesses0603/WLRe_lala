"""只保存不可變功能投影；不取代網路單寫入的遊戲 State。"""
from dataclasses import dataclass
from types import MappingProxyType

from wlre.core.primitives import Owned, identifier, require_immutable


@dataclass(frozen=True)
class Projection:
    revision: int
    value: object


class StateManager(Owned):
    def __init__(self):
        super().__init__()
        self._projections = {}
        self._closed = False

    def replace(self, name, value, *, revision):
        self.assert_owner()
        if self._closed:
            raise RuntimeError('projection_store_closed')
        identifier(name)
        if type(revision) is not int or revision < 0:
            raise ValueError('invalid_projection_revision')
        require_immutable(value)
        previous = self._projections.get(name)
        if previous is not None and revision <= previous.revision:
            raise ValueError('stale_projection_rejected')
        self._projections[name] = Projection(revision, value)

    def snapshot(self):
        self.assert_owner()
        return MappingProxyType(dict(self._projections))

    def close(self):
        self.assert_owner()
        self._closed = True
        self._projections.clear()
