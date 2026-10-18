"""Known authoritative values only; no invented damage formula or HP baseline."""
from dataclasses import dataclass, field, asdict
from wlre.services.world.obstacle_scope import affects_navigation
from wlre.services.social.guild import apply_guild
from wlre.services.items.recovery import apply_recovery
from wlre.services.items.combat_resources import apply_live
from wlre.services.battle.party import party_defaults, apply_party
from wlre.services.items.alchemy import defaults as alchemy_defaults
from wlre.core.efficiency import defaults as efficiency_defaults, observe as observe_efficiency
from wlre.core.activity import apply_activity
from wlre.services.items.crafting import defaults as craft_defaults, room_defaults, apply_crafting
from wlre.services.expedition import defaults as expedition_defaults, apply_expedition


POSITION_CACHE_LIMIT = 2048


@dataclass
class State:
    potion_storage: dict = field(default_factory=dict)
    guild: dict = field(default_factory=dict)
    activities: dict = field(default_factory=dict)
    crafting: dict = field(default_factory=craft_defaults)
    furniture: dict = field(default_factory=room_defaults)
    efficiency: dict = field(default_factory=efficiency_defaults)
    phase: str = "disconnected"
    attributes: dict = field(default_factory=dict)
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
        self.packet_count += 1
        kind = event["type"]
        apply_recovery(self,event)
        apply_guild(self,event)
        apply_activity(self,event)
        apply_crafting(self,event)
        apply_live(self,event)
        apply_party(self,event)
        apply_expedition(self,event)
        if kind == "login_result":
            self.phase = "authenticated" if event["result"] == 0 else "login_failed"
        elif kind == "role_list_available":
            self.phase = "role_selection"
            self.roles = event.get("roles", [])
        elif kind == 'movement_stop':
            self.event_flow={**self.event_flow,'blocked':True,'last_source':f"S6-2 kind={event['kind']}"}
        elif kind == 'event_active':
            self.event_flow={**self.event_flow,'blocked':True,'awaiting_response':False,
                             'last_source':f"S20-{event['sub']}（事件處理尚未完成）"}
        elif kind == 'event_continue_permission':
            self.event_flow={**self.event_flow,'blocked':True,'awaiting_response':False,
                             'last_source':f"S20-{event['sub']}"}
        elif kind == 'event_end':
            self.event_flow={**self.event_flow,'blocked':False,'awaiting_response':False,'last_source':'S20-8'}
        elif kind == "world_player":
            self.player = event["player"]
            self.positions.clear()
            self.remember_position(self.player["role_id"],self.player["x"],self.player["y"])
            self.phase = "world_received"
            self.confirm_location(self.player['scene'],self.player['x'],self.player['y'],'S3-1')
            self.navigation = {'scene':self.player['scene'],'revision':self.navigation['revision']+1,
                               'stale':False,'runtime_geometry_verified':False,'reasons':[]}
        elif kind == 'position_snapshot':
            if event['role_id']==self.player.get('role_id'):
                same_scene=event['scene']==self.player.get('scene')
                previous_navigation=self.navigation
                if not same_scene:self.positions.clear()
                self.player.update(scene=event['scene'],x=event['x'],y=event['y'])
                self.remember_position(event['role_id'],event['x'],event['y'])
                self.confirm_location(event['scene'],event['x'],event['y'],event['source'])
                # Same-map repositioning may also change floor or dynamic objects.
                self.navigation={'scene':event['scene'],'revision':previous_navigation['revision']+1,
                    'stale':previous_navigation.get('stale',False) if same_scene else False,
                    'runtime_geometry_verified':False,
                    'reasons':previous_navigation.get('reasons',[]) if same_scene else []}
            else:
                self.remember_position(event['role_id'],event['x'],event['y'])
        elif kind == 'movement_request':
            self.location['requested_destination']={'x':event['x'],'y':event['y'],
                        'scene':self.player.get('scene'),'source':'C6-1','packet_number':self.packet_count}
            self.location['confirmed_is_current']=False
            self.wait_for_position()
        elif kind == 'navigation_geometry_change' and affects_navigation(event,self.player.get('scene')):
            self.navigation['stale'] = True
            self.navigation['revision'] += 1
            self.navigation['reasons'] = (self.navigation['reasons']+[event['reason']])[-10:]
        elif kind == "initial_data_complete":
            self.initial_data_complete = True
        elif kind in ("battle_start", "battle_units"):
            if kind == "battle_start":
                self.battle_count += 1
                self.battle_units.clear()
                self.battle = {"actions": 0, "winner_side": None, "round": 0,
                               "stage": event["stage"], "fight_number": event["fight_number"], "active": True, "commands": {}}
            for unit in event["units"]:
                self.battle_units[f"{unit['col']}:{unit['row']}"] = dict(unit)
        elif kind == "battle_attribute_set":
            for value in event["values"]:
                unit = self.battle_units.get(f"{value['col']}:{value['row']}")
                if unit is not None:
                    unit.setdefault("attributes", {})[str(value["kind"])] = value["value"]
                    if value["kind"] == 25: unit["hp"] = value["value"]
                    elif value["kind"] == 26: unit["sp"] = value["value"]
        elif kind == "round_start":
            if self.battle.get("round") != event["round"]:
                self.battle["commands"] = {}
            self.battle["round"] = event["round"]
        elif kind == "battle_unit_exit":
            unit = self.battle_units.get(f"{event['col']}:{event['row']}")
            if unit is not None:
                unit["exited"] = True
                if unit.get('pid')==self.player.get('role_id'):self.battle['active']=False
        elif kind == "fight_exit" and event["role_id"] == self.player.get("role_id"):
            self.battle["active"] = False
        elif kind == "attribute_set":
            # Protocol 8 values are replacements, not deltas. Preserve param
            # because skill/skill-EXP updates use it as a separate namespace.
            entity = self.attributes.setdefault(event["entity"], {})
            key = f"{event['kind']}:{event['parameter']}"
            entity[key] = event["value"]
        elif kind == "walk":
            self.remember_position(event["role_id"],event["x"],event["y"])
            if event['role_id']==self.player.get('role_id'):
                self.location['server_destination']={'x':event['x'],'y':event['y'],
                        'scene':self.player.get('scene'),'source':'S6-1','packet_number':self.packet_count}
                self.location['confirmed_is_current']=False
                self.wait_for_position()
        elif kind == 'nearby_leave' and event['role_id']!=self.player.get('role_id'):
            self.positions.pop(str(event['role_id']),None)
        elif kind == "battle_command_sent":
            self.battle.setdefault("commands", {})[f"{event['col']}:{event['row']}"] = {**event, "status":"sent"}
        elif kind == "attack_result":
            self.battle["actions"] += len(event["actions"])
            self.battle["last_actions"] = event["actions"]
            for action in event["actions"]:
                entry=self.battle.get("commands",{}).get(f"{action['col']}:{action['row']}")
                if entry:entry["status"]="resolved"
            # 50-1 alone lacks slot-to-role mapping, shield state and initial HP.
            # Keep reported changes; do not incorrectly subtract from role HP.
        elif kind == "war_style":
            self.battle["war_style"] = event["value"]
        elif kind == "winner":
            self.battle["winner_side"] = event["side"]
            self.battle["active"] = False
        elif kind == "unimplemented":
            self.unimplemented_count += 1

        observe_efficiency(self,event)

    def snapshot(self):
        return asdict(self)
