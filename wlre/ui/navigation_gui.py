"""Compatibility entry for the official-only preview; legacy seed UI retired."""
from wlre.ui.official_navigation_preview import OfficialNavigationPreview


class NavigationWindow(OfficialNavigationPreview):
    """Older imports now open a versioned official preview, never a seed reader."""
    def __init__(self, parent, scene=None, on_route=None):
        self._state={}
        # Historical route callbacks are deliberately not used as movement input.
        super().__init__(parent,lambda:self._state,suggested_scene=scene)

    def update_live_state(self,state):
        self._state=state or {}


def main():
    # The normal App owns official resource preparation before preview access.
    from wlre.ui.gui import main as official_main
    official_main()


if __name__=='__main__':main()
