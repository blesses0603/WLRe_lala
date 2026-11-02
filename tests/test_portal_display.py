"""Minimap presentation hides unknown points and collapses destinations only."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from wlre.services.world.portals import marked_portals
from wlre.services.world.portal_dedup_1275 import collapse_portal_destinations


def portal(index=1, destination=60000, **changes):
    row={'source_revision':1286,'scene':58001,'index':index,
         'id':f'1286:58001:{index}','name':'往 北島－北','kind':'door',
         'official_name':'往 北島－北','display_destination_label':'北島－北',
         'destination':destination,'destination_verified':True,
         'direct_eligible':True,'direct_door_index':index,
         'coordinate_valid':True,'x':200,'y':300}
    return {**row,**changes}


class PortalDisplayTests(unittest.TestCase):
    def setUp(self):self.projection=SimpleNamespace(packet_to_pixel=lambda x,y:(x,y))

    def test_same_destination_has_one_stable_usable_representative(self):
        blocked=portal(1,direct_eligible=False)
        high=portal(9,x=400);chosen=portal(3,x=600)
        rows=[blocked,high,chosen];before=deepcopy(rows)
        result=collapse_portal_destinations(marked_portals(rows,self.projection))
        self.assertEqual(result,[chosen]);self.assertIs(result[0],chosen)
        self.assertEqual(rows,before)
        self.assertEqual(result[0]['direct_door_index'],3)
        self.assertEqual(collapse_portal_destinations(list(reversed(rows))),[chosen])

    def test_same_label_or_position_does_not_merge_different_destinations(self):
        first=portal(1);second=portal(2,destination=60001)
        self.assertEqual(collapse_portal_destinations([first,second]),[first,second])
        other=portal(3,scene=60002)
        self.assertEqual(collapse_portal_destinations([first,other]),[first,other])

    def test_unknown_destinations_hidden_in_every_official_revision(self):
        for revision in (1275,'1275',1286,'1286',1290):
            row=portal(source_revision=revision,destination_verified=False,destination=None)
            with self.subTest(revision=revision):self.assertEqual(marked_portals([row],self.projection),[])

    def test_unlabeled_offscreen_or_missing_points_are_hidden(self):
        for change in ({'official_name':None,'display_destination_label':None},
                       {'official_name':' ','display_destination_label':'\t'},
                       {'official_name':None,'display_destination_label':'場景 60000（名稱未取得）',
                        'display_destination_name_known':False},
                       {'coordinate_valid':False},{'x':2000}):
            with self.subTest(change=change):
                self.assertEqual(marked_portals([portal(**change)],self.projection),[])
        self.assertEqual(marked_portals([portal()],None),[])

    def test_named_reference_requires_known_destination_and_keeps_original_privileges(self):
        row=portal(destination=None,destination_verified=False,direct_eligible=False,
                   reference_destination_scene_id=60000,reference_destination_defined=True)
        self.assertEqual(marked_portals([row],self.projection),[row])
        self.assertFalse(collapse_portal_destinations([row])[0]['direct_eligible'])
        row['reference_destination_defined']=False
        self.assertEqual(marked_portals([row],self.projection),[])

    def test_hidden_marker_needs_defined_destination_and_never_becomes_a_door(self):
        row=portal(index='H1',kind='link',destination=None,destination_verified=False,
                   direct_eligible=False,direct_door_index=None,
                   hidden_destination_scene_id=60000,hidden_destination_defined=True)
        ready=portal(7)
        self.assertEqual(collapse_portal_destinations(marked_portals([row,ready],self.projection)),[ready])
        row['hidden_destination_defined']=False
        self.assertEqual(marked_portals([row],self.projection),[])

    def test_invalid_destination_ids_do_not_become_display_groups(self):
        for target in (None,0,-1,65536,True,'60000'):
            with self.subTest(target=target):
                self.assertEqual(marked_portals([portal(destination=target)],self.projection),[])


if __name__=='__main__':unittest.main()
