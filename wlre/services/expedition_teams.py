"""Legacy module path for expedition team selection and success rates.

Implementation moved to wlre.services.expedition.teams.
"""
from .expedition import teams as _implementation
from .expedition.teams import (
    _model, _compile, _met, condition_met, success_details,
    choose_members, _choose_cached,
)

__all__ = ['condition_met', 'success_details', 'choose_members']

def __getattr__(name):
    return getattr(_implementation, name)
