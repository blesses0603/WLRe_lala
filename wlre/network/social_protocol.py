"""Team.lua / Protocols_013.lua and UIAlchemy.lua 1262 wire layouts."""
from wlre.network.wire import ProtocolError


def decode_social(packet,r,event):
    key=packet.main,packet.sub
    if packet.main==13:
        if packet.sub in (1,4,9):event.update(type={1:'team_application',4:'team_leave',9:'team_invite'}[packet.sub],role_id=r.u32())
        elif packet.sub in (3,10):event.update(type='team_answer',answer=r.u8(),role_id=r.u32(),answer_to='application' if packet.sub==3 else 'invite')
        elif packet.sub==5:event.update(type='team_join',leader_id=r.u32(),role_id=r.u32())
        elif packet.sub==6:
            teams=[]
            while r.remaining:
                leader=r.u32();count=r.u8()
                if not leader or count>3:raise ProtocolError('invalid team size')
                members=[leader]+[r.u32() for _ in range(count)]
                if len(set(members))!=len(members) or 0 in members:raise ProtocolError('invalid team members')
                teams.append({'leader_id':leader,'members':members})
            event.update(type='team_list',teams=teams)
        elif packet.sub==15:
            kind=r.u8()
            if kind==1:event.update(type='team_leader_offer',role_id=r.u32())
            elif kind==2:
                answer=r.u8();event.update(type='team_leader_answer',answer=answer)
                if answer==2:event['role_id']=r.u32()
            elif kind==3:event.update(type='team_new_leader',leader_id=r.u32(),old_leader_id=r.u32())
            else:return False
        elif packet.sub==16:event.update(type='team_notice',code=r.u8())
        else:return False
    elif key==(4,1):
        player={'role_id':r.u32(),'sex':r.u8(),'element':r.u8(),'level':r.u8(),'scene':r.u16(),'x':r.u16(),'y':r.u16()}
        r.take(3+8+2)
        for _ in range(r.u8()):r.take(6)
        player.update(degree=r.u8(),job=r.u8(),name=r.unicode8())
        r.take(8);r.unicode8();r.u16() # Private namecard fields are discarded.
        event.update(type='nearby_player',player=player)
    elif key==(1,1):event.update(type='nearby_leave',role_id=r.u32())
    elif key==(33,2):
        r.u8();r.u8();value=r.u8();r.u8()
        event.update(type='team_flag',enabled=value==1);r.take(r.remaining)
    elif key==(33,1):event.update(type='social_rejected',code=r.u8())
    elif key==(23,13):event.update(type='alchemy_result',item_id=r.u16(),count=r.u8())
    elif key==(23,120):
        value=r.u8();event.update(type='alchemy_space_error',code=value)
        if value==1:event['needed']=r.u8()
        r.take(r.remaining)
    else:return False
    return True
