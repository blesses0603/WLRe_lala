"""The cooperative page's dedicated feature entry point.

The shared room widgets and public InstanceModePage contract stay intact
while the cooperative-specific view is progressively migrated.
"""
from wlre.ui.instance_ui import InstanceModePage


class CooperativeModePage(InstanceModePage):
    """Cooperative instance screen retaining the original Tk parent and API."""

    def __init__(self, parent, app=None):
        super().__init__(parent, cooperative=True, app=app)
