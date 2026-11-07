"""Remaining reviewed bundled resources; retired bootstrap data is not shipped."""
RETIRED_RESOURCES = frozenset(('default_profile.json', 'enums.json', 'lala_supported_resources.json', 'server_list.json', 'crafting_catalog.json', 'expedition_catalog.json', 'npc_event_index_1262.json.gz', 'npc_interact_1262.json.gz', 'npc_talk_1262.json.gz', 'npc_text_1262.json.gz', 'map_names.json', 'instance_catalog_1262.json', 'npc_battle_talk_1262.json.gz', 'smallmaps.zip', 'portals.json', 'emoji_catalog.json', 'emoji_images.zip', 'item_icon_coverage.json', 'item_icon_map.json', 'item_icons.zip', 'item_stackable.json', 'alchemy_catalog.json', 'normal_attack_data.json', 'combat_catalog.json'))
RETIRED_NAVIGATION = frozenset(('navigation_data.zip', 'graph_origins.json', 'stage_coordinates.json'))
RETIRED_RESOURCES = RETIRED_RESOURCES | RETIRED_NAVIGATION | {'resource_catalog_seed.sqlite3'}
# Current data is acquired from verified official sources, not a shipped seed.
SOURCE_MANIFEST = {}
