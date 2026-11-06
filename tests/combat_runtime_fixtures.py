"""Small synthetic catalog for inventory/receipt tests; no bundled game table."""
import unittest
from unittest.mock import patch


def rows():
    items={str(i):dict(name=f'測試物品{i}',kind=1,special=0,restrict=0,fit_type=0,skill_link=0,attributes=[])
           for i in (10000,10001,10031,22001,32001,34104,34014,34068,34144,34026,25000,50000,50001,40000,40001)}
    items['34104'].update(kind=25,special=130)
    items['22001']['fit_type']=1
    items['25000']['fit_type']=11
    items['50000']['restrict']=16;items['50001']['restrict']=144
    items['34144']['name']='5倍經驗聖水';items['34026']['name']='測試夢守'
    items['34014'].update(name='桃太郎飯糰',attributes=[dict(kind=64,effect=0,value=105)])
    items['34068']['attributes']=[dict(kind=64,effect=0,value=108)]
    for ident,attr in ((40000,25),(40001,26)):
        items[str(ident)].update(kind=23,attributes=[dict(kind=attr,effect=0,value=200)])
    return dict(items=items,skills={},keys={},npcs={},characters=[],element_weights={})


def install():
    fixture=patch('wlre.services.items.live_combat_catalog._source',side_effect=rows)
    fixture.start();unittest.addModuleCleanup(fixture.stop)
