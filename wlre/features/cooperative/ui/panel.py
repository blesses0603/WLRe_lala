"""CooperativePage feature page; shared room snapshots and guards remain authoritative."""
from wlre.features.instances.ui.instance_ui import InstanceModePage


class CooperativePage(InstanceModePage):
    def __init__(self, parent, app=None):
        super().__init__(parent, cooperative=True, app=app)
