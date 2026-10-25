"""Cross-feature window lifecycle on the Tk main thread.

The App remains the coordinator and owner of state/worker. UI windows have
one instance each; no game protocol or session timing moves into this module.
"""
from wlre.ui.feature_windows import WINDOWS
from wlre.ui.window_layout import center_on_main
from wlre.ui.resource_view import ResourceView
from wlre.ui.attribute_points_ui import AttributePointWindow


class FeatureWindowController:
    def open_feature(self,key):
        """Single non-modal window per feature, centered on the main dashboard."""
        self.assert_ui_thread()
        window=self.feature_windows[key]
        if not window.winfo_exists():
            return
        center_on_main(window,self.root,*WINDOWS[key][1:])
        window.deiconify()
        window.lift()
        window.focus_set()
        panel=getattr(self,{
            'party':'party_panel','companion':'companion_panel',
            'expedition':'expedition_panel','instance':'instance_panel',
            'alchemy':'alchemy_panel','crafting':'crafting_panel',
            'efficiency':'efficiency_panel'}[key])
        if key=='instance':
            panel.render(self.snapshot,live=self.live_active)
        elif key=='efficiency':
            panel.update_state(self.snapshot)
        elif hasattr(panel,'render'):
            panel.render(self.snapshot)

    def hide_feature(self,key):
        self.assert_ui_thread()
        window=getattr(self,'feature_windows',{}).get(key)
        if window is not None and window.winfo_exists():
            window.withdraw()

    def hide_all_features(self):
        for key in tuple(getattr(self,'feature_windows',{})):
            self.hide_feature(key)

    def open_instances(self):
        self.open_feature('instance')

    def hide_instances(self):
        self.hide_feature('instance')

    def open_resources(self):
        self.resource_windows.append(ResourceView(self))

    def open_attributes(self):
        view=self.attribute_window
        if view is not None and view.window.winfo_exists():
            view.window.lift()
            view.window.focus_force()
        else:
            self.attribute_window=AttributePointWindow(self)

