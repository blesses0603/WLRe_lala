"""Normal dungeon page, retaining original InstanceModePage API."""
from wlre.ui.instance_ui import InstanceModePage


class DungeonModePage(InstanceModePage):
    """Dedicated main-dungeon feature entry without duplicating room dialogs."""

    def __init__(self, parent, app=None):
        super().__init__(parent, cooperative=False, app=app)
