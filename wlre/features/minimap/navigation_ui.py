"""Minimap scene loading, verified route status and redraw synchronization.

No movement commands are emitted. Original HomeMap methods remain callable
through inheritance. This layer keeps missing image / stale navigation closed.
"""
from wlre.services.world.navigation import NavigationError
from wlre.services.world.map_names import map_label, parse_map_id
from wlre.services.world.scene_names_1275 import source_scene_label


class MinimapNavigationMixin:
    def scene_display_name(self):
        """The map header is sourced only from the selected scene ID.

        Portal event labels and selected destinations must never be used as
        the map title. 1275 without verified names shows a numeric scene ID,
        not an outdated 1262 name.
        """
        scene_id = self.selected_id
        catalog = getattr(self, 'portals', None)
        data = getattr(catalog, 'data', {}) if catalog is not None else {}
        if data.get('source_revision') == 1275:
            return source_scene_label(scene_id, data.get('scene_names', {}))
        return map_label(scene_id)

    def update_scene_title(self):
        if type(getattr(self, 'selected_id', None)) is not int:
            return
        self.map_title.set('小地圖｜' + MinimapNavigationMixin.scene_display_name(self))

    def show_map(self,map_id):
        self.route=None
        self.image=None
        self.mesh=None
        self.projection=None
        try:
            self.selected_id=parse_map_id(map_id)
            self.update_scene_title()
            self.projection,scene=self.maps.projection(self.selected_id)
            self.image=self.maps.image(scene)
            if self.image is not None:
                try:self.mesh=self.repository.load(scene)
                except NavigationError:pass
                self.note.set(self.scene_display_name()+'｜原始小地圖')
            else:
                self.projection=None
                self.note.set(self.scene_display_name()+'｜沒有原始小地圖；請使用左側返回出口。')
        except (OSError,ValueError,KeyError) as exc:
            self.image=None;self.mesh=None;self.projection=None
            self.note.set(str(exc))
        self.refresh_portals()
        self.draw()

    def set_state(self,state,force=False):
        previous_navigation=self.state.get('navigation',{})
        self.state=state or {}
        self.update_portal_button()
        scene=self.state.get('player',{}).get('scene')
        if scene is not None and (force or scene!=self.selected_id):
            self.show_map(scene)
        self.update_npc_buttons()
        self.show_dialogue_status()
        travel=self.state.get('portal_travel',{})
        if travel and travel.get('scene')==scene:self.portal_status.set(travel.get('name','')+'｜'+travel.get('reason',''))
        nav=self.state.get('navigation',{})
        if (nav.get('scene')==self.selected_id and
                nav.get('revision')!=previous_navigation.get('revision')):
            self.route=None
        if self.image is not None and nav.get('stale') and nav.get('scene')==self.selected_id:
            self.route=None
            self.note.set('障礙資料已變更，舊路徑已清除。')
        loc=self.state.get('location',{})
        signature=(scene,str(loc),nav.get('revision'),nav.get('stale'),str(self.state.get('local_movement')))
        if force or signature!=self._signature:
            self._signature=signature
            self.draw()

    def set_route(self,result):
        if result is None:
            self.route=None;self.draw();return
        if not self.mesh or result['scene_resource']!=self.mesh.scene_id:return
        nav=self.state.get('navigation',{})
        if self.image is not None and nav.get('stale') and nav.get('scene')==self.selected_id:return
        self.route=result
        self.draw()
