"""Compatibility import for wlre.ui.navigation_gui; implementation: wlre.features.minimap.ui.navigation_gui."""
from wlre.compat import alias_module as _alias_module

if __name__ == '__main__':
    from wlre.features.minimap.ui.navigation_gui import main as _main
    raise SystemExit(_main())
else:
    _alias_module(__name__, 'wlre.features.minimap.ui.navigation_gui', descendants=[])
