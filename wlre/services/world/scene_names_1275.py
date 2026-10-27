"""Scene display names from the same verified 1275 ScenesData_C and TextData_C.

A door's source scene is NOT its transfer destination. Names are read-only
labels and never grant an event index, navigation route, or packet permission.
"""
from wlre.resources_runtime.official.references import scene_display_name


def bind_scene_names(stages, texts):
    """Return verified scene ID -> Chinese name, skipping invalid/missing texts."""
    result = {}
    for scene_id, stage in stages.items():
        if type(scene_id) is not int or not 0 <= scene_id <= 65535:
            continue
        if not isinstance(stage, dict):
            continue
        name_id = stage.get('name_id')
        if type(name_id) is not int or name_id <= 0:
            continue
        name = scene_display_name(texts.get(name_id))
        if name is None:
            continue
        result[scene_id] = name
    return result


def source_scene_label(scene_id, scene_names):
    """Never guess a destination, and never substitute legacy 1262 map names."""
    if type(scene_id) is not int or not 0 <= scene_id <= 65535:
        raise ValueError('場景 ID 無效')
    name = scene_names.get(scene_id) if isinstance(scene_names, dict) else None
    if type(name) is not str or not name.strip():
        return f'場景 {scene_id}'
    return f'{name.strip()}({scene_id})'
