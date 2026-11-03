"""StageMap-only exits use real doors, including server-decided Cairo-shaped exits."""
import os
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wlre.services.world.boundary_portals import boundary_portal_bindings
from wlre.services.world.portal_evidence_1275 import read_only_stage_portal_markers
from wlre.services.world.portal_dedup_1275 import collapse_portal_destinations
from wlre.services.world.portals import Portals, marked_portals
from wlre.services.world.portal_policy import destination_problem
from wlre.services.world.portal_travel import PortalTravel
from wlre.services.world.portal_coverage import audit_portal_coverage
from wlre.features.portals.panel import PortalInteractionMixin
from wlre.core.state import State
from wlre.network.wire import ProtocolError


def marker(*rows):
    return struct.pack('<i',len(rows))+b''.join(struct.pack('<HBHIHHIB',*r) for r in rows)


def fixture(kind=2, *, links=None, rows=None, doors=None):
    # Historical Cairo-like coordinates, with synthetic rectangular geometry.
    stages={12500:dict(pos_x_ratio=2,pos_y_ratio=4,map_width=10000,map_height=12000,
                       small_offset_x=0,small_offset_y=0),58001:{},60014:{},12501:{}}
    doors=doors if doors is not None else {12500:[
        dict(index=1,x=159,y=96,right=161,bottom=98,sign_x=0,sign_y=0,
             sign_type=1,event_ids=[1],touch_event_ids=[1]),
        dict(index=2,x=5,y=100,right=6,bottom=101,sign_x=0,sign_y=0,
             sign_type=1,event_ids=[5],touch_event_ids=[5])]}
    event_id=58001 if kind==3 else 1
    raw=marker(*(rows if rows is not None else [(12500,kind,0,event_id,3177,1920,10,0)]))
    positions,targets=boundary_portal_bindings(raw,links,doors,stages)
    runtime=SimpleNamespace(revision=1286,doors=doors,portal_positions=positions,
        portal_destinations=targets,portal_stage_markers=read_only_stage_portal_markers(raw,stages),
        texts={10:'往航海大地圖'},scene_names={12500:'開羅',58001:'航海大地圖',60014:'埃及野外'},
        portal_names={(12500,event_id):'往航海大地圖'})
    with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
         patch('wlre.services.world.catalog_source_policy.official_runtime',return_value=runtime):
        catalog=Portals()
    return SimpleNamespace(raw=raw,links=links,stages=stages,doors=doors,
                           positions=positions,targets=targets,catalog=catalog)


def projection(row):
    return SimpleNamespace(**row['projection_guard'],packet_to_pixel=lambda x,y:(x/10,y/10))


class StageMapOnlyPortalTests(unittest.TestCase):
    def test_normal_marker_with_no_link_table_can_trigger_actual_door_without_guessing_target(self):
        f=fixture();row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        self.assertEqual(row['name'],'往航海大地圖')
        self.assertEqual(row['direct_door_index'],1)
        self.assertTrue(row['door_binding_verified'])
        self.assertTrue(row['direct_eligible'])
        self.assertIsNone(row['destination'])
        self.assertFalse(row['destination_verified'])
        self.assertEqual(row['destination_status'],'server_decided')
        self.assertIsNone(row['link_index'])
        self.assertEqual((row['x'],row['y']),(6354,7680))
        self.assertEqual(marked_portals(f.catalog.for_scene(12500),projection(row)),[row])
        maps=SimpleNamespace(has_image=Mock(side_effect=AssertionError('Image must not gate a trigger')))
        self.assertIsNone(destination_problem(row,maps))
        state=State();state.player.update(role_id=42,scene=12500,x=6400,y=7600)
        travel=PortalTravel(f.catalog)
        packet,=travel.start_direct(state,Mock(),row['id'],10)
        self.assertEqual((packet.main,packet.sub,packet.payload),(20,8,struct.pack('<H',1)))
        self.assertEqual(state.player['scene'],12500)
        self.assertEqual(travel.start_direct(state,Mock(),row['id'],11),[])
        travel.observe(dict(type='position_snapshot',role_id=42,scene=12500,x=6500,y=7700),state,Mock())
        self.assertEqual(state.portal_travel['status'],'awaiting_map')
        travel.observe(dict(type='position_snapshot',role_id=42,scene=58001,x=2600,y=12560),state,Mock())
        self.assertEqual(state.portal_travel['status'],'completed')
        self.assertEqual(state.portal_travel['arrival']['scene'],58001)

    def test_hidden_marker_with_zero_event_id_keeps_named_exit_and_real_door(self):
        f=fixture(rows=[(12500,3,0,0,3177,1920,10,0)])
        binding=f.targets[12500,1]
        self.assertIsNone(binding['destination'])
        self.assertEqual(binding['stage_marker_event_id'],0)
        row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        self.assertEqual(row['name'],'往航海大地圖')
        self.assertEqual(row['stage_marker_kind'],3)
        self.assertEqual(row['direct_door_index'],1)
        self.assertIsNone(row['destination'])
        self.assertFalse(row['destination_verified'])
        self.assertEqual(row['destination_status'],'server_decided')
        self.assertEqual(marked_portals(f.catalog.for_scene(12500),projection(row)),[row])
        self.assertIsNone(destination_problem(row,SimpleNamespace(has_image=lambda _:False)))
        state=State();state.player.update(role_id=42,scene=12500)
        packet,=PortalTravel(f.catalog).start_direct(state,Mock(),row['id'],10)
        self.assertEqual(packet.payload,struct.pack('<H',1))

    def test_cairo_door_one_does_not_borrow_egypt_destination_from_link_one(self):
        links=('事件ID=12500\n原場景位置[X:92,Y:1990][60014][X:5624,Y:166]\n').encode('utf-16-le')
        f=fixture(links=links);rows={r['index']:r for r in f.catalog.for_scene(12500)}
        self.assertIsNone(rows[1]['destination'])
        self.assertEqual(rows[1]['direct_door_index'],1)
        self.assertEqual(rows[2]['destination'],60014)
        self.assertIsNone(rows[2]['official_name'])
        self.assertEqual(rows[2]['name'],'前往 埃及野外(60014)')
        self.assertEqual(rows[2]['direct_door_index'],2)

    def test_zero_target_hidden_marker_does_not_borrow_cairo_link_one(self):
        links=('事件ID=12500\n原場景位置[X:92,Y:1990][60014][X:5624,Y:166]\n').encode('utf-16-le')
        f=fixture(rows=[(12500,3,0,0,3177,1920,10,0)],links=links)
        rows={r['index']:r for r in f.catalog.for_scene(12500) if type(r['index']) is int}
        self.assertEqual(rows[1]['stage_marker_event_id'],0)
        self.assertTrue(rows[1]['direct_eligible'])
        self.assertIsNone(rows[1]['destination'])
        self.assertEqual(rows[2]['destination'],60014)
        self.assertEqual(rows[2]['direct_door_index'],2)
        self.assertEqual(len(marked_portals(f.catalog.for_scene(12500),projection(rows[1]))),2)

    def test_unknown_nonzero_target_is_not_treated_as_unassigned_or_revived_by_zero(self):
        for rows in ([(12500,3,0,65000,3177,1920,10,0)],
                     [(12500,3,0,65000,3177,1920,10,0),(12500,3,0,0,3177,1920,10,0)]):
            with self.subTest(rows=rows):
                f=fixture(rows=rows)
                self.assertNotIn((12500,1),f.targets)
        f=fixture(rows=[(12500,3,0,0,3177,1920,0,0)])
        row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        self.assertFalse(row['direct_eligible'])
        self.assertEqual(marked_portals(f.catalog.for_scene(12500),projection(row)),[])

    def test_hidden_marker_target_is_a_scene_not_a_door_index(self):
        f=fixture(3);row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        self.assertEqual(row['destination'],58001)
        self.assertTrue(row['destination_verified'])
        self.assertEqual(row['direct_door_index'],1)
        self.assertNotEqual(row['direct_door_index'],58001)
        self.assertIsNone(destination_problem(row,SimpleNamespace(has_image=lambda _:False)))
        self.assertEqual(len(marked_portals(f.catalog.for_scene(12500),projection(row))),1)
        report=audit_portal_coverage(f.doors,f.stages,f.raw,None,f.positions,f.targets,
                                     names={(12500,58001):'往航海大地圖'})
        detail=next(d for s in report['scenes'] if s['scene']==12500 for d in s['details'] if d['index']==1)
        self.assertEqual(detail['category'],'stage_marker_portal')
        self.assertTrue(detail['named'])
        self.assertNotIn('missing_door_link',detail['issues'])

    def test_known_destination_without_image_enables_ui_and_sends_once(self):
        f=fixture(3);row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        page=PortalInteractionMixin();page.selected_portal=row;page.portals=f.catalog
        page.maps=SimpleNamespace(has_image=lambda _:False);page.projection=projection(row)
        page.state={'player':{'scene':12500}};page.selected_id=12500
        page.portal_go=Mock();page.portal_status=Mock();page.on_portal=Mock()
        page.update_portal_button()
        self.assertEqual(page.portal_go.configure.call_args.kwargs['state'],'normal')
        self.assertTrue(page.go_portal());page.on_portal.assert_called_once_with(row['id'])
        state=State();state.player.update(role_id=42,scene=12500)
        packet,=PortalTravel(f.catalog).start_direct(state,Mock(),row['id'],10)
        self.assertEqual(packet.payload,struct.pack('<H',1))

    def test_no_current_image_allows_verified_list_trigger_without_drawing_coordinates(self):
        f=fixture(3);row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        self.assertEqual(marked_portals([row],None),[])
        self.assertEqual(marked_portals([row],None,allow_unprojected=True),[row])
        page=PortalInteractionMixin();page.selected_portal=row;page.portals=f.catalog
        page.maps=SimpleNamespace(has_image=lambda _:False);page.projection=None;page.image=None
        page.state={'player':{'scene':12500}};page.selected_id=12500
        page.portal_go=Mock();page.portal_status=Mock();page.on_portal=Mock()
        page.update_portal_button()
        self.assertEqual(page.portal_go.configure.call_args.kwargs['state'],'normal')
        self.assertTrue(page.go_portal());page.on_portal.assert_called_once_with(row['id'])
        bad=dict(row,direct_eligible=False)
        self.assertEqual(marked_portals([bad],None,allow_unprojected=True),[])

    def test_marker_with_no_actual_touch_door_stays_disabled(self):
        for mutation in ('touch','geometry','duplicate'):
            f=fixture();doors=f.doors
            if mutation=='touch':doors[12500][0]['touch_event_ids']=[]
            elif mutation=='geometry':doors[12500][0]['x']=200
            else:doors[12500].append(dict(doors[12500][0],index=9))
            bad=fixture(doors=doors)
            self.assertNotIn((12500,1),bad.targets)
            row=next(r for r in bad.catalog.for_scene(12500) if r['index']==1)
            self.assertFalse(row['direct_eligible'])
            self.assertIsNotNone(destination_problem(row))

    def test_conflicting_hidden_targets_do_not_enable_an_unknown_marker_fallback(self):
        rows=[(12500,3,0,target,3177,1920,10,0) for target in (58001,60014)]
        rows.append((12500,2,0,1,3177,1920,10,0))
        self.assertEqual(fixture(rows=rows).targets,{})

    def test_unnamed_unknown_target_is_not_a_blanket_permission_for_old_references(self):
        f=fixture(rows=[(12500,2,0,999,3177,1920,0,0)])
        row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        self.assertIsNone(row['official_name'])
        self.assertFalse(row['direct_eligible'])
        self.assertIsNotNone(destination_problem(row))
        with self.assertRaises(ProtocolError):
            state=State();state.player.update(role_id=42,scene=12500)
            PortalTravel(f.catalog).start_direct(state,Mock(),row['id'],10)

    def test_server_decided_trigger_rejection_or_timeout_never_retries_or_reports_success(self):
        for outcome in ('rejected','timeout'):
            with self.subTest(outcome=outcome):
                f=fixture();row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
                state=State();state.player.update(role_id=42,scene=12500,x=6400,y=7600)
                travel=PortalTravel(f.catalog);movement=Mock()
                travel.start_direct(state,movement,row['id'],10)
                if outcome=='rejected':
                    travel.observe(dict(type='event_rejected',reason='需要載具'),state,movement)
                else:
                    self.assertEqual(travel.tick(state,movement,26),[])
                self.assertEqual(state.portal_travel['status'],outcome)
                self.assertEqual(state.player['scene'],12500)
                self.assertIsNone(travel.pending)
                self.assertEqual(travel.tick(state,movement,40),[])

    def test_duplicate_hidden_markers_keep_one_real_door_row(self):
        marker_row=(12500,3,0,58001,3177,1920,10,0)
        f=fixture(rows=[marker_row,marker_row])
        row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
        visible=collapse_portal_destinations(marked_portals(f.catalog.for_scene(12500),projection(row)))
        self.assertEqual([r['direct_door_index'] for r in visible],[1])


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','Requires desktop')
class StageOnlyMapUI(unittest.TestCase):
    def test_actual_list_and_button_accept_stage_only_exit_with_no_target_image(self):
        self.check_fixture(fixture())

    def test_zero_target_hidden_marker_is_visible_and_clickable_in_actual_list(self):
        self.check_fixture(fixture(rows=[(12500,3,0,0,3177,1920,10,0)]))

    def check_fixture(self,f):
        import tkinter as tk
        from wlre.ui.home_map import HomeMap
        root=tk.Tk();sent=Mock()
        try:
            with patch('wlre.ui.home_map.Portals',return_value=f.catalog):
                page=HomeMap(root,Mock(),Mock(),on_portal=sent,compact=True)
            page.pack();page.state={'player':{'scene':12500}}
            row=next(r for r in f.catalog.for_scene(12500) if r['index']==1)
            page.selected_id=12500;page.projection=projection(row);page.image=object()
            page.maps=SimpleNamespace(has_image=lambda _:False)
            with patch('wlre.ui.home_map.scene_npcs',return_value=[]),patch.object(page,'draw'):
                page.refresh_portals()
                self.assertEqual(len(page.portal_rows),1)
                self.assertIn('往航海大地圖',page.portal_list.get(0))
                page.select_portal(page.portal_rows[0]);page.portal_go.invoke()
            sent.assert_called_once_with(row['id'])
            sent.reset_mock();page.image=None;page.projection=None
            with patch('wlre.ui.home_map.scene_npcs',return_value=[]),patch.object(page,'draw'):
                page.refresh_portals();self.assertEqual(len(page.portal_rows),1)
                page.select_portal(page.portal_rows[0]);page.portal_go.invoke()
            sent.assert_called_once_with(row['id'])
        finally:
            for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
            root.destroy()
