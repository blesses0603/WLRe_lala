"""A stable facade whose operations can pin one activated combat snapshot."""
from collections.abc import Mapping
from contextvars import ContextVar
from functools import wraps

_pinned=ContextVar('combat_catalog_snapshot',default=None)


def _source():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    return getattr(current_runtime(),'combat_catalog',None)


class CurrentCombatCatalog(Mapping):
    def snapshot(self):
        value=_pinned.get()
        if value is None:value=_source()
        return value if value is not None else dict(skills={},keys={},items={},npcs={},characters=[],element_weights={})
    def __getitem__(self,key):return self.snapshot()[key]
    def __iter__(self):return iter(self.snapshot())
    def __len__(self):return len(self.snapshot())


def one_catalog(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        if _pinned.get() is not None:return function(*args,**kwargs)
        token=_pinned.set(CurrentCombatCatalog().snapshot())
        try:return function(*args,**kwargs)
        finally:_pinned.reset(token)
    return wrapped


def source_token():
    value=_source()
    return id(value) if value is not None else None
