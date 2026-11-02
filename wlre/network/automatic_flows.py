"""Continue explicit session goals through the existing guarded commands.

No answer, recipe, target room, purchase, role or allocation is guessed here.
State and all packet sends remain on the owning network thread.
"""
import time
from wlre.network.wire import ProtocolError
from wlre.services.world.dynamic_bundle_runtime import current_catalog_token
from wlre.services.world.npc_catalog import NPCIndex

OPERATIONS=('create','join','leave','standby','start','enter','claim','cancel')


class AutomaticFlows:
    def __init__(self):
        self.goals={}
        self.attempted=set()
        self.next_tick=0

    def note(self,state,scope,text):
        state.automation={**state.automation,scope:text,'status':text}

    def remember(self,command,state,now=None):
        """Called only after a requested command has passed all its guards."""
        now=time.monotonic() if now is None else now
        kind=command.get('type');action=command.get('action')
        if kind in ('instance_create','instance_join','tent') or kind=='craft' and action=='add':
            self.goals.pop('npc',None)
        if kind in ('walk','portal_walk','portal_direct','start_roaming','stop_walk','stop_roaming','npc_start'):
            self.goals.pop('npc',None)
        if kind in ('npc_start','npc_choose'):
            state.npc_dialogue={**state.npc_dialogue,'auto_continue':state.automation['enabled'],
                                'auto_role':state.player.get('role_id'),'auto_token':current_catalog_token()}
        if kind=='npc_approach' and state.automation['enabled']:
            self.goals['npc']={'scene':command['scene'],'npc_index':command['npc_index'],
                'npc_id':command['npc_id'],'role':state.player.get('role_id'),
                'token':current_catalog_token(),'due':now+300,
                'path_id':(state.local_movement or {}).get('route_id')}
            self.note(state,'npc','前往 NPC，抵達後自動互動')
        if kind in ('instance_create','instance_join') and state.automation['enabled']:
            self.goals['room']={'mode':command['mode'],'role':state.player.get('role_id'),
                'token':current_catalog_token(),'room':command.get('room_id',command.get('map_id')),
                'due':now+30,'bound':False,'reward_auto':True}
            self.attempted.clear()
            self.note(state,'room','等待房間確認後自動接續')
        if kind=='instance_auto_reward' and 'room' in self.goals:
            self.goals['room']['reward_auto']=command['enabled']
        if kind in ('instance_leave','instance_reward_cancel') or (
                kind=='instance_coop_standby' and command.get('standby') is False):
            self.goals.pop('room',None)
        if kind=='craft' and action in ('pause','stop_auto','plan_pause','delete','up','down'):
            self.goals.pop('craft',None)
        if kind=='craft' and action=='add' and state.automation['enabled']:
            self.goals['craft']={'role':state.player.get('role_id'),
                'token':current_catalog_token(),'due':now+30}
            self.note(state,'craft','等待排程與材料確認後自動開始')

    def set_enabled(self,state,enabled):
        if type(enabled) is not bool:raise ProtocolError('自動流程設定必須為布林值')
        state.automation={**state.automation,'enabled':enabled}
        if not enabled:
            self.goals.clear();self.attempted.clear()
            state.npc_dialogue={**state.npc_dialogue,'auto_continue':False}
            # Stop future continuation, never fabricate cancellation of in-flight work.
            state.crafting['auto_continue']=False
            if state.crafting.get('local_plan'):
                state.crafting['local_plan']['enabled']=False
            state.instances['coop']['auto_claim_enabled']=False
            self.note(state,'status','已暫停自動流程；已送出的要求仍等待伺服器確認')
        else:self.note(state,'status','已啟用；下次指定目標後自動接續')
        return []

    def clear(self,state):
        self.goals.clear();self.attempted.clear()
        state.npc_dialogue={**state.npc_dialogue,'auto_continue':False}
        self.note(state,'status','連線結束，自動流程已停止')

    def observe(self,event,state):
        kind=event.get('type')
        if kind in ('craft_failed','craft_paused'):
            self.goals.pop('craft',None)
            self.note(state,'craft',state.crafting.get('status','製作已停止'))
        if kind=='event_end' and state.npc_dialogue.get('auto_continue'):
            self.note(state,'npc','NPC 事件已由伺服器確認結束')
        elif kind=='event_rejected' and state.npc_dialogue.get('auto_continue'):
            self.note(state,'npc','伺服器拒絕 NPC 事件，停止接續：'+event.get('reason',''))

    def _valid(self,goal,state):
        return (goal['role']==state.player.get('role_id')
                and goal['token']==current_catalog_token())

    def tick(self,logic,state,now=None):
        now=time.monotonic() if now is None else now
        if not state.automation['enabled'] or state.phase!='world_ready' or not logic.world_acknowledged:
            return []
        if now<self.next_tick:return []
        self.next_tick=now+.35
        from wlre.network.commands import dispatch
        packets=[]
        # No conflicting action can start while a battle/server event owns the client.
        blocked=(state.battle.get('active') or state.event_flow.get('blocked')
                 or (state.battle.get('post_event') or {}).get('status') not in (None,'completed'))
        npc=self.goals.get('npc')
        if npc and not blocked:
            local=state.local_movement
            if (not self._valid(npc,state) or npc['scene']!=state.player.get('scene')
                    or now>=npc['due'] or (local or {}).get('route_id')!=npc['path_id']
                    or (local or {}).get('status')=='stopped' and (local or {}).get('reason')!='已在 NPC 附近'):
                self.goals.pop('npc',None);self.note(state,'npc','NPC 目標已失效，自動互動停止')
            elif not local or local.get('status')!='running':
                self.goals.pop('npc',None)  # One attempt; a server rejection never retries.
                try:
                    rows=NPCIndex().for_scene(npc['scene'])
                    row=next((r for r in rows if r['index']==npc['npc_index'] and r['npc_id']==npc['npc_id']),None)
                    if row is None:raise ProtocolError('NPC 身分已改變')
                    cmd={'type':'npc_start','confirmed':True,'scene':npc['scene'],
                         'npc_index':npc['npc_index'],'npc_id':npc['npc_id'],'x':row['x'],'y':row['y']}
                    packets=dispatch(logic,cmd,state)
                    state.npc_dialogue={**state.npc_dialogue,'auto_continue':True,
                                        'auto_role':npc['role'],'auto_token':npc['token']}
                    self.note(state,'npc','已自動互動，等待伺服器對話')
                except (ProtocolError,ValueError,OSError,EOFError,UnicodeError) as exc:
                    self.note(state,'npc','自動互動停止：'+str(exc))
                return packets
        info=state.npc_dialogue
        if info.get('active') and info.get('auto_continue'):
            if (info.get('scene')!=state.player.get('scene')
                    or info.get('auto_role')!=state.player.get('role_id')
                    or info.get('auto_token')!=current_catalog_token()):
                state.npc_dialogue={**info,'auto_continue':False}
                self.note(state,'npc','場景已改變，自動對話停止')
            elif (not state.battle.get('active') and info.get('phase') in ('talk','continue')
                  and (state.battle.get('post_event') or {}).get('status') in (None,'completed')):
                try:
                    packets=dispatch(logic,{'type':'npc_next'},state)
                    self.note(state,'npc','已自動接續對話，等待伺服器回覆')
                    return packets
                except ProtocolError as exc:self.note(state,'npc','等待自動對話：'+str(exc))
            elif info.get('phase')=='choice_unavailable':
                self.note(state,'npc','已顯示選項／商店，等待目標設定；不代選答案或商品')
            elif info.get('phase')=='effect_unavailable':
                self.note(state,'npc','事件效果尚未支援，自動接續停止')
        if blocked:return []
        craft=self.goals.get('craft')
        if craft:
            if not self._valid(craft,state) or state.crafting.get('uncertain') or now>=craft['due']:
                self.goals.pop('craft',None);self.note(state,'craft','製作目標失效或結果不明，停止接續')
            elif not logic.crafting.pending and not state.crafting.get('pending'):
                if not state.crafting.get('queue'):
                    self.goals.pop('craft',None);self.note(state,'craft','本次製作已無待開始排程')
                else:
                    try:
                        packets=dispatch(logic,{'type':'craft','action':'start'},state)
                        self.goals.pop('craft',None)
                        self.note(state,'craft','製作已自動開始／接續')
                        return packets
                    except ProtocolError as exc:self.note(state,'craft','等待自動製作：'+str(exc))
        room=self.goals.get('room')
        if room:
            mode=room['mode'];data=state.instances[mode];current=data.get('room') or {}
            if (not self._valid(room,state) or any(data.get(op+'_uncertain') for op in OPERATIONS)
                    or data.get('reward_uncertain')):
                self.goals.pop('room',None);self.note(state,'room','副本目標失效或結果不明，停止自動接續')
            elif not current:
                if room['bound'] or now>=room['due']:
                    self.goals.pop('room',None);self.note(state,'room','房間已結束或尚未確認，停止接續')
            elif room['room'] is not None and current.get('room_id')!=room['room']:
                self.goals.pop('room',None);self.note(state,'room','房間身分已變更，停止接續')
            else:
                if (data.get('create_pending') is not None or data.get('join_pending') is not None
                        or not any(m.get('role_id')==state.player.get('role_id')
                                   for m in data.get('members') or ())):
                    self.note(state,'room','等待伺服器確認房間與本人成員身分')
                    return []
                room.update(room=current.get('room_id'),bound=True)
                if mode=='coop' and room['reward_auto'] and 'reward' not in self.attempted:
                    try:
                        dispatch(logic,{'type':'instance_auto_reward','mode':'coop','enabled':True},state)
                        self.attempted.add('reward')
                    except ProtocolError as exc:self.note(state,'room','等待免費領獎設定：'+str(exc))
                pending=any(data.get(op+'_pending') is not None for op in OPERATIONS)
                kind=None
                if not pending:
                    if mode=='main' and data.get('phase')=='started':kind='instance_enter'
                    elif data.get('phase')=='waiting' and current.get('host_id',
                            (data.get('members') or [{}])[0].get('role_id'))==state.player.get('role_id'):
                        if mode=='main':kind='instance_start'
                        elif current.get('standby') is False:kind='instance_coop_standby'
                if kind and kind not in self.attempted:
                    cmd={'type':kind,'mode':mode}
                    if mode=='coop':cmd['standby']=True
                    try:
                        packets=dispatch(logic,cmd,state)
                        self.attempted.add(kind)
                        self.note(state,'room','已自動接續副本，等待伺服器確認')
                        return packets
                    except ProtocolError as exc:self.note(state,'room','等待副本接續：'+str(exc))
        return []
