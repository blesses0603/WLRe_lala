"""Manual target selection, actual movement packets, portal trigger and automatic resume."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.features.minimap.buttons import MinimapPickMixin
from wlre.features.minimap.map_view import MinimapCanvasMixin
from wlre.network.client import SessionLogic
from wlre.network.service_scheduler import advance_services
from wlre.network.wire import ProtocolError, Writer
from wlre.services.world.coordinates import Coordinates
from wlre.services.world.navigation import Mesh, NavigationError
from wlre.services.world.movement import Movement
from wlre.services.world.smallmaps import SmallMaps
from wlre.services.world.portals import Portals
from wlre.services.world.portal_travel import PortalTravel
from wlre.services.expedition import Expedition, choose_members
from wlre.ui.gui import App
from wlre.ui.overview_ui import summarize
from test_expedition import ExpeditionFixture, catalog, role
from test_portal_coordinates_1275 import stage_marker, door_links, position_fixture
from wlre.services.world.portal_links_1275 import verified_portal_destinations


class Var:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value


class MinimapActionTests(unittest.TestCase):
    def setUp(self):
        self.converter=Coordinates()
        stage=deepcopy(self.converter.stages['12170'])
        self.runtime=SimpleNamespace(revision=1286,catalog_identity=SimpleNamespace(key='a'*64),
                                     stages={12170:stage})
        from smallmap_runtime_fixtures import attach
        attach(self.runtime)
        self.current=patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=self.runtime)
        self.active=patch('wlre.services.world.runtime_1275.active_runtime',return_value=self.runtime)
        for item in (self.current,self.active):
            item.start();self.addCleanup(item.stop)
        self.state=State(phase='world_ready')
        self.state.player={'role_id':1,'scene':12170,'x':1033,'y':4210}
        self.state.location.update(confirmed={'scene':12170,'x':1033,'y':4210,'packet_number':1},
                                   confirmed_is_current=True)
        self.logic=SessionLogic();self.logic.world_acknowledged=True
        mesh=Mesh({'tiles':[{'vertices_b_int3':[[0,0,0],[100000,0,0],[100000,0,100000],[0,0,100000]],
                              'triangles':[[0,1,2],[0,2,3]]}]})
        mesh.scene_id='M12170'
        self.logic.movement=Movement(self.converter,SimpleNamespace(load=lambda scene:mesh))
        self.app=SimpleNamespace(snapshot=self.state.snapshot(),x=Var(),y=Var(),status=Mock(),map_target_scene=None)
        self.page=MinimapPickMixin()
        self.page.maps=SmallMaps(source_revision='1286')
        self.page.projection,_=self.page.maps.projection(12170)
        self.page.portal_rows=[];self.page.selected_id=12170
        self.page.selected_portal=self.page.selected_npc=None
        self.page.update_portal_button=Mock();self.page.note=Mock()
        self.page.draw=Mock();self.page.state=self.state.snapshot()
        self.page.view=lambda:(0,0,1)
        self.page.screen_pixel=lambda x,y:(x,y)
        self.page.on_pick=lambda scene,x,y:App.pick_map_destination(self.app,scene,x,y)
        self.commands=[]
        def move():
            command={'type':'walk','scene':self.app.map_target_scene,
                     'x':int(self.app.x.get()),'y':int(self.app.y.get())}
            self.commands.append(command)
            with patch('wlre.network.commands.time.monotonic',return_value=0):
                self.logic.command(command,self.state)
        self.page.on_move=move

    def event(self,x=1050,y=4200):
        u,v=self.page.projection.packet_to_pixel(x,y)
        return SimpleNamespace(x=u,y=v)

    def test_single_click_selects_and_draws_target_without_sending_move(self):
        self.assertTrue(self.page.pick(self.event()))
        self.assertEqual((self.app.x.get(),self.app.y.get()),('1050','4200'))
        self.assertEqual(self.page.picked_destination,{'scene':12170,'x':1050,'y':4200})
        self.assertEqual(self.commands,[])
        self.page.draw.assert_called_once_with()

    def test_double_click_cannot_authorize_unverified_legacy_geometry(self):
        with self.assertRaisesRegex(ProtocolError,'僅供預覽'):
            self.page.double_pick(self.event())
        self.assertEqual(self.commands,[{'type':'walk','scene':12170,'x':1050,'y':4200}])
        self.assertFalse(self.logic.movement.active)
        self.assertEqual(self.logic.movement.tick(self.state,.2),[])
        self.assertFalse(self.state.local_movement)

    def test_target_selection_does_not_require_a_navigation_mesh(self):
        self.page.maps.supports_navigation=False
        self.assertTrue(self.page.pick(self.event()))
        self.assertEqual(self.page.picked_destination['x'],1050)
        self.assertEqual(self.commands,[])

    def test_outside_map_click_never_queues_a_move(self):
        self.assertFalse(self.page.pick(SimpleNamespace(x=-1,y=-1)))
        self.assertEqual(self.commands,[])

    def test_current_geometry_mismatch_keeps_image_but_does_not_send_movement(self):
        self.runtime.stages[12170]['map_width']+=1
        maps=SmallMaps(source_revision='1286')
        projection,model=maps.projection(12170)
        self.assertIsNotNone(maps.image(model))
        self.assertFalse(maps.supports_navigation)
        with self.assertRaises(NavigationError):
            self.logic.movement.start(self.state,1050,4200,0)
        self.assertFalse(self.logic.movement.active)

    def test_runtime_replacement_stops_an_old_active_route(self):
        # Explicit synthetic authority tests only the runtime-expiry contract.
        original=self.converter.route
        def synthetic(*args,**kwargs):
            return {**original(*args,**kwargs),'can_send_packets':True,'live_movement_verified':True}
        with patch.object(self.converter,'route',side_effect=synthetic):
            self.logic.movement.start(self.state,1100,4200,0)
        replacement=deepcopy(self.runtime)
        replacement.catalog_identity.key='b'*64
        with patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',return_value=replacement):
            self.assertEqual(self.logic.movement.tick(self.state,.2),[])
        self.assertFalse(self.logic.movement.active)

    def test_database_mesh_for_current_scene_supports_a_geometric_route(self):
        from wlre.services.world.navigation import Repository
        repo=Repository()
        mesh=repo.load('M12170')
        source=next(face for face,neighbors in mesh.adjacency.items() if neighbors)
        target=next(iter(mesh.adjacency[source]))
        first,last=mesh.centers[source],mesh.centers[target]
        start=self.converter.to_packet(12170,first[0],first[2])
        end=self.converter.to_packet(12170,last[0],last[2])
        route=self.converter.route(repo,12170,start,end,start_height=first[1],end_height=last[1])
        self.assertEqual(route['scene_resource'],'M12170')
        self.assertGreater(len(route['points']),1)
        self.assertIs(route['can_send_packets'],False)

    def test_selected_target_is_drawn_before_movement(self):
        page=SimpleNamespace(_resize_job=None,canvas=Mock(),projection=self.page.projection,
            selected_id=12170,image=None,route=None,portal_rows=[],selected_portal=None,
            state={},picked_destination={'scene':12170,'x':1050,'y':4200})
        page.canvas.winfo_width.return_value=1040;page.canvas.winfo_height.return_value=1040
        page.view=lambda:(8,8,1)
        page.screen_pixel=lambda x,y:(x+8,y+8)
        MinimapCanvasMixin.draw(page)
        self.assertTrue(any(call.kwargs.get('outline')=='#ffc654'
                            for call in page.canvas.create_oval.call_args_list))


class DynamicPortalTriggerTests(unittest.TestCase):
    def test_fully_matched_dynamic_portal_can_send_one_manual_trigger(self):
        from test_portal_coordinates_1275 import physical_door, physical_stages
        doors={11016:[physical_door()]}
        links=verified_portal_destinations(stage_marker(),door_links(),doors,physical_stages())
        runtime=SimpleNamespace(revision=1286,catalog_identity=SimpleNamespace(key='a'*64),
            doors=doors,portal_positions=position_fixture(),portal_destinations=links,
            scene_names={11016:'來源',11017:'目的地'})
        with patch('wlre.services.world.runtime_1275.baseline_revision',return_value='1286'), \
             patch('wlre.services.world.catalog_source_policy.official_runtime',return_value=runtime):
            portals=Portals()
        row=portals.for_scene(11016)[0]
        self.assertTrue(row['direct_eligible'])
        state=State(phase='world_ready')
        state.player={'role_id':1,'scene':11016,'x':600,'y':600}
        service=PortalTravel(portals)
        with patch('wlre.services.world.portal_policy.smallmaps',return_value=SimpleNamespace(has_image=lambda scene:True)):
            packets=service.start_direct(state,Mock(),row['id'],0)
            self.assertEqual(service.start_direct(state,Mock(),row['id'],1),[])
        self.assertEqual(len(packets),1)
        self.assertEqual((packets[0].main,packets[0].sub,packets[0].payload),(20,8,Writer().u16(1).build()))


class ExpeditionResumeTests(ExpeditionFixture,unittest.TestCase):
    def test_manual_start_arms_until_both_server_snapshots_arrive(self):
        self.state.expedition.update(ready=False,outpost_ready=False)
        self.service.start(self.state,self.settings)
        self.assertTrue(self.state.expedition['enabled'])
        self.assertEqual(self.service.tick(self.state,10),[])
        self.state.expedition['ready']=True
        self.assertEqual(self.service.tick(self.state,11),[])
        self.state.expedition['outpost_ready']=True
        packet,=self.service.tick(self.state,12)
        self.assertEqual((packet.main,packet.sub),(31,15))

    def test_start_during_battle_waits_and_automatically_resumes(self):
        self.state.battle['active']=True
        self.service.start(self.state,self.settings)
        self.assertTrue(self.state.expedition['enabled'])
        self.assertEqual(self.service.tick(self.state,10),[])
        self.state.battle['active']=False
        packet,=self.service.tick(self.state,13)
        self.assertEqual((packet.main,packet.sub),(31,15))

    def test_missing_faith_items_waits_then_resumes_after_stock_update(self):
        self.state.expedition['roles']['1']['faith']=70
        self.state.inventory.update(ready=True,reliable=True,items={})
        self.service.start(self.state,{**self.settings,'item_id':0})
        self.assertEqual(self.service.tick(self.state,10),[])
        self.assertTrue(self.state.expedition['enabled'])
        self.state.inventory['items']={'1':{'item_id':34014,'count':5}}
        packet,=self.service.tick(self.state,13)
        self.assertEqual((packet.main,packet.sub),(31,27))
        self.assertEqual(self.service.pending['kind'],'faith')

    def test_faith_above_configured_threshold_but_below_quest_cost_is_not_excluded(self):
        quest={'condition':[1,1,0],'faith_cost':90}
        member=role(faith=85)
        self.assertEqual(choose_members(quest,[member],80),[member])

    def test_scheduler_really_sends_dispatch_after_armed_sync_completes(self):
        self.state.expedition.update(ready=False,outpost_ready=False)
        logic=SessionLogic();logic.world_acknowledged=True;logic.expedition=self.service
        logic.command({'type':'start_expedition','settings':self.settings},self.state)
        self.state.expedition.update(ready=True,outpost_ready=True)
        sent=[]
        with patch('wlre.network.service_scheduler.time.monotonic',return_value=10):
            advance_services(logic,self.state,sent.append,Mock(),Mock(),None)
        self.assertTrue(any((p.main,p.sub)==(31,15) for p in sent))
        self.assertEqual(self.state.expedition['pending'],'dispatch')

    def test_dashboard_displays_actual_wait_reason(self):
        self.state.player={'role_id':1,'name':'測試'}
        self.state.expedition.update(enabled=True,status='等待足夠的好友度恢復物品，補齊後自動繼續')
        text=summarize(self.state.snapshot(),True,{},now=10)['expedition']
        self.assertIn('好友度恢復物品',text)


def setUpModule():
    from combat_runtime_fixtures import install
    install()
