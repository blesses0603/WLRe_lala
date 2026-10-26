"""Known authoritative values only; no invented damage formula or HP baseline."""
from dataclasses import dataclass, field, fields
from contextlib import contextmanager
import threading
from wlre.core.state_ownership import FIELDS, guarded, plain
from wlre.core.state_events import dispatch_local
from wlre.services.world.obstacle_scope import affects_navigation
from wlre.services.social.guild import apply_guild
from wlre.services.items.recovery import apply_recovery
from wlre.services.items.combat_resources import apply_live
from wlre.services.battle.party import party_defaults, apply_party
from wlre.services.items.alchemy import defaults as alchemy_defaults
from wlre.services.world.npc_shop_evidence import defaults as shop_evidence_defaults, observe as observe_shop_evidence
from wlre.core.efficiency import defaults as efficiency_defaults, observe as observe_efficiency
from wlre.core.activity import apply_activity
from wlre.services.items.crafting import defaults as craft_defaults, room_defaults, apply_crafting
from wlre.services.world.tent import defaults as tent_defaults, apply_tent
from wlre.services.items.room_storage import defaults as storage_defaults, apply_storage
from wlre.services.expedition import defaults as expedition_defaults, apply_expedition
from wlre.services.instances import defaults as instance_defaults, apply_instances
from wlre.services.battle.attribute_points import defaults as points_defaults, apply_event as apply_points_event


POSITION_CACHE_LIMIT = 2048


@dataclass
class State:
    maintenance: dict = field(default_factory=lambda:{'pending':None,'uncertain':False,'checking':False,'status':'尚未執行戰後修理／整理','completed':0})
    potion_storage: dict = field(default_factory=dict)
    room_storage: dict = field(default_factory=storage_defaults)
    guild: dict = field(default_factory=dict)
    activities: dict = field(default_factory=dict)
    crafting: dict = field(default_factory=craft_defaults)
    furniture: dict = field(default_factory=room_defaults)
    tent: dict = field(default_factory=tent_defaults)
    efficiency: dict = field(default_factory=efficiency_defaults)
    phase: str = "disconnected"
    attributes: dict = field(default_factory=dict)
    attribute_allocation: dict = field(default_factory=points_defaults)
    positions: dict = field(default_factory=dict)
    battle: dict = field(default_factory=lambda: {"actions": 0, "winner_side": None})
    packet_count: int = 0
    unimplemented_count: int = 0
    roles: list = field(default_factory=list)
    player: dict = field(default_factory=dict)
    initial_data_complete: bool = False
    battle_units: dict = field(default_factory=dict)
    battle_count: int = 0
    navigation: dict = field(default_factory=lambda: {'scene':None,'revision':0,
                               'stale':False,'runtime_geometry_verified':False,'reasons':[]})
    location: dict = field(default_factory=lambda: {'confirmed':None,'confirmed_is_current':False,
                                 'requested_destination':None,'server_destination':None})

    event_flow: dict = field(default_factory=lambda:{'blocked':False,'awaiting_response':False,
                                'last_source':None,'requests_sent':0})
    npc_dialogue: dict = field(default_factory=lambda:{'active':False,'phase':'idle'})
    shop_evidence: dict = field(default_factory=shop_evidence_defaults)
    gold: dict = field(default_factory=lambda:{
        'ready':False,'reliable':False,'amount':None,'revision':0,'source':None})
    inventory: dict = field(default_factory=lambda:{'ready':False,'reliable':False,'items':{},'reserved':{},'revision':0,'use_failed':False})
    knowledge: dict = field(default_factory=lambda:{'player':{'ready':False,'skills':{},'stats':{}},'companions':{},'companions_ready':False,'active_npc_id':None})
    auto_battle: dict = field(default_factory=lambda:{'enabled':False,'status':'disabled','reason':''})
    roaming: dict = field(default_factory=lambda:{'enabled':False,'status':'disabled','reason':''})
    portal_travel: dict = field(default_factory=dict)
    local_movement: dict | None = None
    movement_check: dict | None = None

    party: dict = field(default_factory=party_defaults)
    alchemy: dict = field(default_factory=alchemy_defaults)
    expedition: dict = field(default_factory=expedition_defaults)
    instances: dict = field(default_factory=instance_defaults)

    def __post_init__(self):
        object.__setattr__(self,'_writer',threading.get_ident())
        object.__setattr__(self,'_scope',None)
        for value in fields(self):setattr(self,value.name,getattr(self,value.name))

    def assert_writer(self,field=None):
        if threading.get_ident()!=self._writer:
            raise RuntimeError('State may only be accessed by its owning network thread; use snapshots and commands')
        if field and self._scope is not None and field not in FIELDS[self._scope]:
            raise RuntimeError(f'{self._scope} cannot mutate State.{field}')

    def __setattr__(self,name,value):
        if hasattr(self,'_writer') and not name.startswith('_'):
            self.assert_writer(name)
            value=guarded(value,lambda:self.assert_writer(name))
        object.__setattr__(self,name,value)

    @contextmanager
    def editing(self,owner):
        self.assert_writer()
        if owner not in FIELDS:raise ValueError(owner)
        previous=self._scope;object.__setattr__(self,'_scope',owner)
        try:yield self
        finally:object.__setattr__(self,'_scope',previous)

    def __deepcopy__(self,memo):
        self.assert_writer()
        return type(self)(**self.snapshot())

    def remember_position(self,role_id,x,y):
        # Observed remote positions are a cache, not a lifetime travel history.
        # Authoritative local location remains separately in self.location.
        key=str(role_id);own=str(self.player.get('role_id'))
        self.positions.pop(key,None);self.positions[key]=[x,y]
        while len(self.positions)>POSITION_CACHE_LIMIT:
            oldest=next(iter(self.positions))
            if oldest==own:
                self.positions[own]=self.positions.pop(own)
                oldest=next(iter(self.positions))
            self.positions.pop(oldest)

    def clear_position_history(self):
        own = str(self.player.get('role_id'))
        removed = len(self.positions) - int(own in self.positions)
        current = self.positions.get(own)
        self.positions.clear()
        if current is not None: self.positions[own] = current
        return removed

    def wait_for_position(self):
        target=self.location.get('requested_destination') or self.location.get('server_destination')
        if self.local_movement and self.local_movement.get('status') in ('running','finished'):
            target=self.local_movement['target']
        self.movement_check={'status':'waiting','target':dict(target),
                             'role_id':self.player.get('role_id'),'confirmation':None} if target else None

    def confirm_location(self, scene, x, y, source):
        check=self.movement_check
        if (check and check['status'] in ('waiting','different_position')
                and check.get('role_id') is not None
                and check['role_id']==self.player.get('role_id')):
            target=check['target']
            status=('scene_changed' if target['scene']!=scene else
                    'matched' if (target['x'],target['y'])==(x,y) else 'different_position')
            self.movement_check={**check,'status':status,
                'confirmation':{'scene':scene,'x':x,'y':y,'source':source,'packet_number':self.packet_count}}
        self.location={'confirmed':{'scene':scene,'x':x,'y':y,'source':source,
                                    'packet_number':self.packet_count},
                       'confirmed_is_current':True,'requested_destination':None,'server_destination':None}

    def apply(self, event):
        self.assert_writer()
        self.packet_count += 1
        apply_recovery(self,event)
        apply_guild(self,event)
        apply_activity(self,event)
        apply_crafting(self,event)
        apply_storage(self,event)
        apply_live(self,event)
        apply_points_event(self,event)
        apply_party(self,event)
        apply_expedition(self,event)
        apply_instances(self,event)
        dispatch_local(self, event, affects_navigation=affects_navigation)
        apply_tent(self,event)
        observe_shop_evidence(self,event)
        observe_efficiency(self,event)

    def snapshot(self):
        self.assert_writer()
        return {value.name:plain(getattr(self,value.name)) for value in fields(self)}
