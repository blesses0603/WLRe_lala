"""Reviewed ItemData.CanOverlap from official 1.3.23 Lua, never a legacy table.

ItemData/Define/Function fingerprints and field evidence are documented in
OFFICIAL_CLIENT_LUA_DECODING and the stack-rule migration report. Only the
fingerprint-pinned ItemData parser activates this derived field.
"""
from collections.abc import Mapping


def can_overlap(item_id, row):
    fields=('fit_type','kind','special','available_time','limited_time','use_count','flags2')
    if type(item_id) is not int or not 1<=item_id<=65535:
        raise ValueError('Invalid stack rule item identity')
    if any(type(row.get(k)) is not int or not 0<=row[k]<=65535 for k in fields):
        raise ValueError('Missing reviewed stack rule fields')
    attributes=row.get('attributes')
    if type(attributes) is not list or len(attributes)!=2 or any(
            type(a) is not dict or type(a.get('kind')) is not int or not 0<=a['kind']<=65535 for a in attributes):
        raise ValueError('Missing reviewed item attributes')
    fit=row['fit_type']
    if fit==10 or item_id in (34106,34152,34163,34164,34168,34180):return False
    if 0<fit<7 or fit==11:return False  # Equip / sacred object
    if row['kind'] in (39,58):return False  # Traffic and giant traffic
    if fit==9:return False  # IsEggItem returns 1, 2, or 255 for every Special item.
    if (0<fit<8 or fit in (10,11)) and row['available_time']>0:return False
    if (0<fit<9 or fit in (10,11)) and (row['limited_time']>0 or row['flags2']&1):return False
    if row['special']==151 and (attributes[0]['kind'] in (25,26) or item_id in (34298,34299)):return False
    if row['special']==130 and row['use_count']>1:return False
    if row['kind']==76:return False
    return True


class CurrentStackRules(Mapping):
    """Stable compatibility facade; every access uses the activated version."""
    @staticmethod
    def _items():
        from wlre.services.world.dynamic_bundle_runtime import current_runtime
        runtime=current_runtime()
        return getattr(runtime,'items',{}) if runtime is not None else {}
    def snapshot(self):
        return {str(k):v['stackable'] for k,v in self._items().items() if type(v.get('stackable')) is bool}
    def __getitem__(self,key):
        try:ident=int(key)
        except (TypeError,ValueError):raise KeyError(key) from None
        row=self._items().get(ident,{})
        value=row.get('stackable')
        if type(value) is not bool:raise KeyError(key)
        return value
    def __iter__(self):
        return iter(tuple(str(k) for k,v in self._items().items() if type(v.get('stackable')) is bool))
    def __len__(self):
        return sum(type(v.get('stackable')) is bool for v in self._items().values())
