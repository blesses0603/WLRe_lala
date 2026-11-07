"""Small synthetic official-runtime shapes; never copied game content."""
from types import SimpleNamespace


def runtime():
    choice={'index':1,'form_kind':1,'link_number':1,'items':[
        {'id':1,'text_id':50063,'database_kind':1,'kind':1},
        {'id':2,'text_id':10001,'database_kind':1,'kind':3},
        {'id':3,'text_id':10002,'database_kind':1,'kind':3}]}
    def shop(index,kind):
        return {'index':index,'form_kind':kind,'link_number':0,'items':[
            {'id':1,'text_id':32297,'database_kind':2,'kind':3}]}
    return SimpleNamespace(revision=1296,
        npc_index=SimpleNamespace(scenes={'10000':[{'index':1,'npc_id':321,'x':1,'y':1,
                    'event_count':1,'event_ids':[1],'buy_kind':0}]}),
        interact_index=SimpleNamespace(scenes={10000:{1:choice},10080:{6:shop(6,2),7:shop(7,3)}}),
        talks={50063:'fixture question',10001:'fixture yes',10002:'fixture no'},
        texts={1:'fixture text'},items={})
