"""Legacy module path for expedition catalog parsing.

Implementation moved to wlre.services.expedition.data. Keep this module as a
thin alias so existing imports continue working while downstream code migrates.
"""
from .expedition import data as _implementation
from .expedition.data import data_root, parse_catalog, load_catalog, attach_names, parse_npcs

__all__ = ['data_root', 'parse_catalog', 'load_catalog', 'attach_names', 'parse_npcs']

def __getattr__(name):
    return getattr(_implementation, name)
