"""Server-confirmed expedition services; original public import path remains stable.

Compatibility:
    from wlre.services.expedition import Expedition, validate, choose_members
New focused modules:
    from wlre.services.expedition.manager import Expedition
    from wlre.services.expedition.data import load_catalog
    from wlre.services.expedition.teams import choose_members

This package replaces the historical expedition.py module. All consuming
code can continue importing from wlre.services.expedition unchanged.
"""
from .manager import (
    Expedition, defaults, apply_expedition, with_deadline, preferences,
    validate, faith_gain, recovery_stock, duration, condition_ok, blocked,
    item_totals, claim_space, load_catalog, choose_members, condition_met,
    success_details,
)

__all__ = [
    'Expedition', 'defaults', 'apply_expedition', 'with_deadline', 'preferences',
    'validate', 'faith_gain', 'recovery_stock', 'duration', 'condition_ok',
    'blocked', 'item_totals', 'claim_space', 'load_catalog', 'choose_members',
    'condition_met', 'success_details',
]
