"""Single-writer state containers and explicit service mutation scopes.

Network State belongs to its creating thread. UI receives plain detached data.
Scopes restrict service writes to declared fields; nested service calls enter
that service's scope, making collaboration explicit without sharing ownership.
"""
import copy
from functools import wraps
import inspect

FIELDS={
    'expedition':frozenset(('expedition','inventory')),
    'alchemy':frozenset(('alchemy','inventory')),
    'crafting':frozenset(('crafting','inventory')),
    'tent':frozenset(('tent',)),
    'field_supply':frozenset(('inventory','potion_storage')),
    'maintenance':frozenset(('maintenance','inventory')),
    'auto_battle':frozenset(('auto_battle','inventory')),
    'roaming':frozenset(('roaming','local_movement')),
    'movement':frozenset(('local_movement','movement_check','location')),
    'portal_travel':frozenset(('portal_travel','event_flow')),
}


def writes(owner):
    if owner not in FIELDS:raise ValueError(owner)
    def decorate(function):
        position=list(inspect.signature(function).parameters).index('state')
        @wraps(function)
        def invoke(*args,**kwargs):
            state=args[position] if len(args)>position else kwargs['state']
            with state.editing(owner):return function(*args,**kwargs)
        return invoke
    return decorate


def plain(value):
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if isinstance(value,list):return [plain(v) for v in value]
    if isinstance(value,tuple):return tuple(plain(v) for v in value)
    return copy.deepcopy(value)


def guarded(value,check):
    if isinstance(value,dict):return OwnedDict(value,check)
    if isinstance(value,list):return OwnedList(value,check)
    if isinstance(value,tuple):return tuple(guarded(v,check) for v in value)
    return value


class OwnedDict(dict):
    def __init__(self,value,check):
        self._check=check
        dict.__init__(self,((k,guarded(v,check)) for k,v in value.items()))
    def __deepcopy__(self,memo):return plain(self)
    def __setitem__(self,key,value):self._check();dict.__setitem__(self,key,guarded(value,self._check))
    def __delitem__(self,key):self._check();dict.__delitem__(self,key)
    def clear(self):self._check();dict.clear(self)
    def pop(self,*args):self._check();return dict.pop(self,*args)
    def popitem(self):self._check();return dict.popitem(self)
    def update(self,*args,**kwargs):
        self._check()
        for k,v in dict(*args,**kwargs).items():self[k]=v
    def setdefault(self,key,default=None):
        if key not in self:self[key]=default
        return self[key]
    def __ior__(self,other):self.update(other);return self


class OwnedList(list):
    def __init__(self,value,check):self._check=check;list.__init__(self,(guarded(v,check) for v in value))
    def __deepcopy__(self,memo):return plain(self)
    def __setitem__(self,key,value):
        self._check();list.__setitem__(self,key,[guarded(v,self._check) for v in value] if isinstance(key,slice) else guarded(value,self._check))
    def __delitem__(self,key):self._check();list.__delitem__(self,key)
    def append(self,value):self._check();list.append(self,guarded(value,self._check))
    def extend(self,values):self._check();list.extend(self,[guarded(v,self._check) for v in values])
    def insert(self,index,value):self._check();list.insert(self,index,guarded(value,self._check))
    def pop(self,*args):self._check();return list.pop(self,*args)
    def remove(self,value):self._check();list.remove(self,value)
    def clear(self):self._check();list.clear(self)
    def reverse(self):self._check();list.reverse(self)
    def sort(self,*args,**kwargs):self._check();list.sort(self,*args,**kwargs)
    def __iadd__(self,values):self.extend(values);return self
    def __imul__(self,count):self._check();list.__imul__(self,count);return self
