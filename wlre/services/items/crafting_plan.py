"""Local plan with unlimited entries and chunked batch submission; server acknowledgement owns every transition."""
from wlre.network.wire import ProtocolError


def validate_rows(rows):
    from wlre.services.items.crafting import RECIPES
    if not isinstance(rows,list):raise ProtocolError('自訂清單格式無效')
    result=[]
    for row in rows:
        if not isinstance(row,dict):raise ProtocolError('清單格式無效')
        sid=row.get('item_id');count=row.get('count')
        if type(sid) is not int or str(sid) not in RECIPES:raise ProtocolError('清單包含未知配方')
        r=RECIPES[str(sid)]
        if r.get('open_used',0) or r['design_id'] or r['time_id'] or r['limit_kind']:raise ProtocolError('此配方尚未開放或解鎖條件未同步')
        if type(count) is not int or count<1:raise ProtocolError('每項批數必須為正整數')
        result.append({'item_id':sid,'count':count})
    return result

class PlanMixin:
    def plan(self,state):
        return state.crafting.setdefault('local_plan',{'rows':[],'enabled':False,'sent':0,'revision':0,'status':'尚未啟動自訂清單'})

    def command(self,state,command,now=None):
        p=self.plan(state);action=command.get('action')
        if action=='plan_set':
            if p['enabled'] or (self.pending and self.pending.get('plan_item')):raise ProtocolError('請先暫停清單並等待目前送出項目確認')
            rows=validate_rows(command.get('rows'))
            if command.get('revision')!=p['revision']:raise ProtocolError('清單已更新，請重新操作')
            p.update(rows=rows,revision=p['revision']+1,sent=0,status='自訂清單已更新');return []
        if action=='plan_start':
            if 'revision' in command and command['revision']!=p['revision']:raise ProtocolError('清單更新未確認，未啟動')
            if not p['rows']:raise ProtocolError('自訂清單為空')
            if state.crafting['uncertain']:raise ProtocolError('製作狀態不確定，請重新登入同步')
            if self.pending:raise ProtocolError('請等待目前製作操作確認')
            if state.battle.get('active') or state.event_flow.get('blocked') or state.alchemy.get('enabled') or state.alchemy.get('pending') or state.roaming.get('enabled') or state.auto_battle.get('enabled'):raise ProtocolError('請先停止其他自動功能並結束戰鬥／事件')
            p.update(enabled=True,status='自訂清單執行中');state.crafting['auto_continue']=True;state.crafting['status']=p['status'];return []
        if action=='plan_pause':
            p.update(enabled=False,status='清單已暫停；已送入伺服器的項目保留');state.crafting['auto_continue']=False;state.crafting['status']=p['status'];return []
        if action in ('pause','stop_auto','delete','up','down'):
            p.update(enabled=False,status='清單已暫停')
        if action=='add' and p['enabled']:raise ProtocolError('自訂清單執行中，請先暫停再手動加入')
        return self._server_command(state,command,now)

    def observe(self,event,state,now=None):
        old=self.pending
        self._server_observe(event,state,now)
        p=self.plan(state)
        if old and old.get('plan_item') and self.pending is None and event['type']!='craft_failed':
            if p['rows'] and p['rows'][0]==old['plan_item']:
                remaining=p['rows'][0]['count']-old.get('plan_count',old['plan_item']['count'])
                if remaining>0:p['rows'][0]['count']=remaining
                else:p['rows'].pop(0)
                p['sent']+=1;p['revision']+=1
                p['status']='已確認送入伺服器；等待下一空位'
        if event['type'] in ('craft_failed','craft_paused'):p.update(enabled=False,status=state.crafting['status'])

    def tick(self,state,now=None):
        from wlre.services.items.crafting import tools
        p=self.plan(state);c=state.crafting
        # Completion and exact output confirmation always precede another submission.
        packets=self._server_tick(state,now)
        if c['uncertain']:
            p.update(enabled=False,status=c['status']);return packets
        if packets or self.pending or not p['enabled']:return packets
        if state.battle.get('active') or state.event_flow.get('blocked'):return []
        if self.wait_output:
            if self.wait_output['received']<self.wait_output['required']:
                if not c['auto_continue']:p.update(enabled=False,status=c['status'])
                return []
            self.wait_output=None;self.next_start=False
        c['auto_continue']=True
        try:
            # Start existing work first, then fill remaining native slots while running.
            if c['queue'] and not c['running']:
                return self._server_command(state,{'action':'start'},now)
            if not p['rows']:
                p.update(enabled=False,status='清單已全部送入；伺服器排程繼續製作')
                if not c['queue']:c['auto_continue']=False
                return []
            cap=5 if 39050 in tools(state) else 3
            if len(c['queue'])>=cap:
                p['status']='等待伺服器排程空位';return []
            row=p['rows'][0]
            if any(r['item_id']==row['item_id'] for r in c['queue'].values()) and 39814 not in tools(state):
                p['status']='等待相同物品完成後再加入';return []
            batch=min(row['count'],255)
            packets=self._server_command(state,{'action':'add','item_id':row['item_id'],'count':batch},now)
            self.pending['plan_item']=dict(row);self.pending['plan_count']=batch;p['status']='正在送入，等待排程與材料確認';return packets
        except (ProtocolError,ValueError,KeyError) as exc:
            p.update(enabled=False,status=str(exc));c.update(auto_continue=False,status='自訂清單暫停：'+str(exc));return []
