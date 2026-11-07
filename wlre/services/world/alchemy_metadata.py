"""Alchemy reads one verified ItemData version, never a legacy combat table."""
from collections.abc import Mapping


def _source():
    from wlre.services.world.dynamic_bundle_runtime import current_runtime
    runtime=current_runtime()
    identity=getattr(runtime,'catalog_identity',None)
    return (identity.key,runtime.items) if identity is not None else (None,{})


def _valid(row):
    return (type(row) is dict and type(row.get('stackable')) is bool
            and all(type(row.get(k)) is int for k in ('kind','special','restrict'))
            and type(row.get('spares')) is list and len(row['spares'])==5
            and all(type(v) is int for v in row['spares']))


class CurrentAlchemyMetadata(Mapping):
    def snapshot(self):
        key,rows=_source()
        return key,{str(k):v for k,v in rows.items() if _valid(v)}
    def __getitem__(self,key):
        try:ident=int(key)
        except (ValueError,TypeError):raise KeyError(key) from None
        _,rows=_source();row=rows.get(ident)
        if not _valid(row):raise KeyError(key)
        return row
    def __iter__(self):return iter(self.snapshot()[1])
    def __len__(self):return len(self.snapshot()[1])
