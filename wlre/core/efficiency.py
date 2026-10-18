"""Local-only EXP_Monitor-style completed-battle efficiency, bounded history."""
import math,time
from functools import lru_cache
from wlre.core.event_log import owned

STAGES={0:'未轉生',1:'一轉',2:'二轉星脈'}

def defaults():return {'role_id':None,'rows':{},'pending':False,'dirty':[],'participants':[],'battles':0,'offline':False}

def need(level,degree):
    if degree==0:return math.floor(level**3.1+5+.5) # EXP_Monitor reference coefficients
    if degree==1:return math.floor(level**3.3+(50 if level<=150 else (level-150)**4.9)+.5)
    if degree==2:return 0 if level<=1 else math.floor((300+level)**2.6+max(0,level-49)**5.6+.5)
    return None

@lru_cache(maxsize=1200)
def cumulative(level,degree):
    # Preserve EXP_Monitor's level-one origin for comparable forecasts.
    return sum(need(n,degree) for n in range(2,level+1))

def progress(total,level,degree):
    if degree not in STAGES or not isinstance(level,int) or not 1<=level<=400:return None,None,None
    maximum={0:199,1:190,2:100}[degree]
    if level>maximum:return None,None,None
    if level==maximum:
        return (0,100.,0 if degree==1 else None) if total>=cumulative(level,degree) else (None,None,None)
    base=cumulative(level,degree);required=need(level+1,degree)
    if not base<=total<=base+required:return None,None,None
    return base+required-total,(total-base)/required*100,max(0,cumulative(190,1)-total) if degree==1 else None

def _row(state,key):
    eff=state.efficiency;stats=state.knowledge.get('player',{}).get('stats',{}) if key=='self' else state.knowledge.get('companions',{}).get(key.split(':')[1],{}).get('stats',{})
    if key=='self':name=state.player.get('name','玩家');identity=state.player.get('role_id')
    else:
        index=key.split(':')[1];profile=state.knowledge.get('companions',{}).get(index,{})
        identity=profile.get('npc_id')
        if identity is None:return None
        from wlre.services.items.combat_resources import CAT
        name=stats.get('name') or CAT['npcs'].get(str(identity),{}).get('name') or f'夥伴 #{index}'
    row=eff['rows'].get(key)
    if row is None or row.get('identity')!=identity:
        row={'identity':identity,'name':name,'exp':None,'level':None,'degree':None,'last_total':None,'last_gain':None,'earned':0,'count':0,'history':[],'first_time':None,'last_time':None}
        eff['rows'][key]=row
        # State wraps assigned dictionaries in OwnedDict. Continue updating
        # that authoritative instance, not the detached pre-wrap local dict.
        row=eff['rows'][key]
    row['name']=name
    # Confirmed level and degree always replace the previous inferred label.
    if stats.get('level') is not None:
        row['level']=stats['level']
        row.pop('level_inferred',None)
    if stats.get('degree') is not None:
        row['degree']=stats['degree']
        row.pop('degree_inferred',None)
    if stats.get('exp') is not None:row['exp']=stats['exp']
    if key!='self' and row['exp'] is not None:
        # Mounts may receive EXP without a refreshed fight-unit level. Keep the
        # server value separately; label any curve-derived level in the UI.
        if row['degree'] is None and row['level'] is not None:
            matches=[d for d in STAGES if progress(row['exp'],row['level'],d)[0] is not None]
            if len(matches)==1:row['degree']=matches[0];row['degree_inferred']=True
        if row['degree'] in STAGES and (row['level'] is None or progress(row['exp'],row['level'],row['degree'])[0] is None):
            maximum={0:199,1:190,2:100}[row['degree']]
            for level in range(1,maximum+1):
                if level==maximum or cumulative(level,row['degree'])<=row['exp']<cumulative(level+1,row['degree']):
                    row['level']=level;row['level_inferred']=True;break
    return row

def observe(state,event):
    eff=state.efficiency;pid=state.player.get('role_id');kind=event['type']
    if not pid:return
    if eff['role_id']!=pid:
        state.efficiency=defaults()
        # State guards each assigned dictionary by wrapping it. Always
        # continue through the authoritative instance after assignment.
        eff=state.efficiency
        eff['role_id']=pid
    now=event.get('_observed_at',time.monotonic())
    if not isinstance(now,(int,float)) or not math.isfinite(now):return
    eff['offline']=bool(event.get('_offline',eff['offline']))
    _row(state,'self')
    for index in state.knowledge.get('companions',{}):_row(state,'follow:'+index)
    for key in list(eff['rows']):
        if key!='self' and key.split(':')[1] not in state.knowledge.get('companions',{}):eff['rows'].pop(key)
    if kind=='battle_start':
        units=event['units']
        eff['pending']=any(owned(u,pid) for u in units)
        eff['dirty']=[]
        # Known participants have local role / companion-slot evidence.
        # Inactive companions must retain their confirmed historical rates.
        participants=set()
        if eff['pending']:
            for unit in units:
                if unit.get('pid')==pid:participants.add('self')
                index=unit.get('npc_index')
                if (unit.get('master_id')==pid and type(index) is int
                        and 1<=index<=255 and str(index) in state.knowledge.get('companions',{})):
                    participants.add('follow:'+str(index))
        eff['participants']=sorted(participants)
    key=None
    if kind=='attribute_set' and event.get('kind')==36 and event.get('parameter',0)==0:
        if event.get('entity')=='self':key='self'
        elif event.get('human_kind')==4:key=event['entity']
    if kind=='star_info':key='self'
    if key:
        row=_row(state,key)
        if row is not None:
            total=event['value'] if kind=='attribute_set' else event['exp'];row['exp']=total
            if eff['pending']:
                if key not in eff['dirty']:eff['dirty'].append(key)
            else:
                # Exclude quest rewards/out-of-battle corrections from next gain.
                row['last_total']=total
    if kind!='event_end' or not eff['pending']:return
    eff['pending']=False;eff['battles']+=1
    dirty=set(eff['dirty']);eff['dirty']=[]
    participants=set(eff.get('participants',()))
    eff['participants']=[]
    for key,row in eff['rows'].items():
        if key not in dirty:
            # Missing evidence is not a zero-EXP sample. Invalidate the
            # baseline only for units proven present in this battle.
            # Never wipe a different companion's confirmed 10/30 history.
            if key in participants:
                row['last_total']=None
                row['last_gain']=None
            continue
        total=row['exp'];last=row['last_total']
        if total is None:continue
        # A stage/identity change or backwards correction starts a fresh baseline.
        stage_changed=row.get('sample_degree') is not None and row['sample_degree']!=row['degree']
        if stage_changed or total<0 or (last is not None and total<last):
            row.update(last_total=None,last_gain=None,earned=0,count=0,history=[],first_time=None,last_time=None)
            last=None
        gain=total-last if last is not None and row['last_time'] is not None and now>row['last_time'] else None
        if gain is not None:
            row['earned']+=gain;row['count']+=1
        else:row['history']=[]
        if row['first_time'] is None:row['first_time']=now
        row.update(last_total=total,last_gain=gain,last_time=now,sample_degree=row['degree'])
        row['history']=(row['history']+[(row['earned'],now)])[-31:]

def rates(row):
    history=row['history'];result=[]
    seconds=(row['last_time']-row['first_time']) if row['last_time'] is not None and row['first_time'] is not None else 0
    result.append((row['earned']*60/seconds if seconds>0 and row['count'] else None,row['count']))
    for window in (10,30):
        samples=history[-(window+1):];count=len(samples)-1;seconds=samples[-1][1]-samples[0][1] if count>0 else 0
        result.append(((samples[-1][0]-samples[0][0])*60/seconds if seconds>0 else None,max(0,count)))
    return result

def duration(seconds):
    if seconds is None or not math.isfinite(seconds):return '等待統計'
    seconds=math.ceil(max(0,seconds));days,seconds=divmod(seconds,86400);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
    return (f'{days}天' if days else '')+(f'{hours}時' if hours else '')+(f'{minutes}分' if minutes else '')+f'{seconds}秒'

def forecast(remaining,rate,elapsed=0):
    if remaining is None:return '資料待同步'
    if remaining==0:return '已達標'
    if not rate or rate<=0:return '等待效率樣本'
    seconds=remaining/rate*60-elapsed
    return duration(seconds) if seconds>0 else '等待下場確認'
