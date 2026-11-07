"""Two synthetic material rows for receipt/UI fixtures, not a game catalog."""
import unittest
from unittest.mock import patch


def rows():
    return {sid:dict(kind=1,special=0,restrict=0,spares=[1,0,0,0,0],stackable=True,item_w=1,item_h=1)
            for sid in (10001,10031)}


def install():
    fixture=patch('wlre.services.world.alchemy_metadata._source',side_effect=lambda:('synthetic-alchemy',rows()))
    fixture.start();unittest.addModuleCleanup(fixture.stop)
