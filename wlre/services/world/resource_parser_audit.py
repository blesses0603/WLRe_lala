"""Exercise every applicable official table parser without activating results."""
from __future__ import annotations


def audit_sources(sources):
    """Continue after each failure. Missing inputs are explicitly not tested.

    Call only with TextAssets already checked against the official manifest.
    No downloading, offset guessing, schema promotion or source replacement.
    """
    from wlre.services.parser_diagnostics import record_coverage
    from wlre.services.world.itemdata_v1 import parse_itemdata
    from wlre.services.world.eve_v115 import derive_eve_index
    from wlre.services.world.doors_1275 import parse_verified_doors
    from wlre.services.world.npc_talk import parse_talk_data
    from wlre.services.world.smith_candidate import parse_smith_records
    from wlre.services.world.daily_task_1275 import parse_daily_tasks
    from wlre.services.instance_catalog import parse_stages, parse_dungeons, parse_cooperative_events
    from wlre.services.expedition.data import parse_catalog, parse_text_data, parse_npcs
    from wlre.services.world.portal_links_1275 import parse_stage_map_portals, parse_eve_door_links
    from wlre.services.world.portal_schema import parse_door_link_data

    checks = (
        ('items', ('ItemData_C',), parse_itemdata, {}),
        ('npc_events', ('Eve',), derive_eve_index, {'source': 'EventData.NewNpc'}),
        ('interactions', ('Eve',), derive_eve_index, {'source': 'EventData.NewInteract'}),
        ('doors', ('Eve',), parse_verified_doors, {}),
        ('talks', ('TalkData_C',), parse_talk_data, {}),
        ('texts', ('TextData_C',), parse_text_data, {}),
        ('recipes', ('SmithData_C',), parse_smith_records, {}),
        ('scenes', ('ScenesData_C',), parse_stages, {}),
        ('expedition', ('AdventureData_C', 'AdventureLvData_C'), parse_catalog, {}),
        ('npcs', ('NpcData_C', 'NpcCareerData_C'), parse_npcs, {}),
        ('daily_tasks', ('DailyTaskData_C',), parse_daily_tasks, {}),
        ('dungeons', ('DungeonData_C',), parse_dungeons, {}),
        ('cooperative_events', ('CooperateEventData_C',), parse_cooperative_events, {}),
        ('stage_map', ('StageMapData_C',), parse_stage_map_portals, {}),
        ('eve_links', ('EveDoorLinks',), parse_eve_door_links, {}),
        ('door_links', ('DoorLinkData_C',), parse_door_link_data, {}),
    )
    coverage = {}
    for name, tables, parser, kwargs in checks:
        if any(type(sources.get(t)) is not bytes for t in tables):
            coverage[name] = 'not_available'
            continue
        try:
            parser(*(sources[t] for t in tables), **kwargs)
        except Exception:
            # The diagnosed parser recorded the sanitized detail. Continue
            # inspection, while the caller's original runtime gate stays intact.
            coverage[name] = 'failed'
        else:
            coverage[name] = 'passed'
    record_coverage(coverage)
    return coverage
