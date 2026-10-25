"""Compatibility imports for feature moves, sharing the canonical module object.

Aliases preserve old monkeypatch points and class identity. Package descendants
are registered explicitly, so Python cannot load a second copy under an old
package prefix. No global import hook or replacement of shared services is used.
"""
from importlib import import_module
import sys


def alias_module(legacy_name, canonical_name, descendants=()):
    """Bind a legacy import to its sole implementation and known descendants."""
    implementation = import_module(canonical_name)
    sys.modules[legacy_name] = implementation
    for old, new in descendants:
        child = import_module(new)
        sys.modules[old] = child
    return implementation
