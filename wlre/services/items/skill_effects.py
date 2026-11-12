"""Recovery categories from fingerprint-reviewed SkillData.lua, never cast authority.

Amounts, passive effects and SP absorption are deliberately left unknown.
ReduceSP is a cost; TargetKind and VariableA-D do not establish recovery.
"""
from collections.abc import Mapping

REVIEWED_LUA_SHA256='962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228'


def recovery_kind(data):
    if not isinstance(data,Mapping):return 'unknown'
    value=data.get('FightWay')
    if type(value) is not int:return 'unknown'
    return {6:'sp',7:'hp',14:'hp_sp'}.get(value,'unknown')


def recovery_description(data):
    kind=recovery_kind(data)
    resource={'sp':'SP','hp':'HP','hp_sp':'HP／SP'}.get(kind)
    return '恢復 '+resource+'（恢復量未知）' if resource else '恢復效果未驗證'
