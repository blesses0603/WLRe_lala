"""Display labels from verified current Scenes/Text records; never movement authority."""
from copy import deepcopy
import re

_cached = (None, None)


def _current_data():
    global _cached
    from wlre.services.world.runtime_1275 import active_runtime
    try:
        runtime = active_runtime()
    except (OSError, ValueError, EOFError, UnicodeError):
        return {'maps': {}, 'models': {}, 'ambiguous_models': [],
                'source_kind': 'official_runtime_unavailable'}
    previous, names = _cached
    if previous is runtime:
        return names
    from wlre.services.world.scene_names_1275 import bind_scene_names
    stages=getattr(runtime,'stages',None);texts=getattr(runtime,'texts',None)
    if type(stages) is not dict or type(texts) is not dict:
        return {'maps':{},'models':{},'ambiguous_models':[],
                'source_kind':'official_names_unavailable'}
    scenes = bind_scene_names(stages, texts)
    models = {}
    for sid, name in scenes.items():
        model = stages[sid].get('model_id')
        if type(model) is int and 0 < model <= 65535:
            models.setdefault(str(model), set()).add(name)
    names = {'version': runtime.revision,
             'source_kind': 'verified_official_runtime',
             'maps': {str(k): v for k, v in scenes.items()},
             'models': {k: next(iter(v)) for k, v in models.items() if len(v) == 1},
             'ambiguous_models': sorted((k for k, v in models.items() if len(v) > 1), key=int)}
    _cached = (runtime, names)
    return names


def data():
    return deepcopy(_current_data())


def parse_map_id(value):
    text=str(value).strip()
    match=re.search(r'[（(](\d+)[）)]\s*$',text)
    if match:return int(match.group(1))
    if re.fullmatch(r'[Mm]?\d+',text):return int(text.lstrip('Mm'))
    raise ValueError('請輸入地圖 ID 或選擇「地圖名稱(地圖ID)」。')


def map_label(value):
    sid=parse_map_id(value)
    return f"{_current_data()['maps'].get(str(sid),'未知地圖')}({sid})"


def model_label(value):
    sid=parse_map_id(value)
    names=_current_data()
    fallback='多個場景共用模型' if str(sid) in names['ambiguous_models'] else '未命名場景'
    return f"{names['models'].get(str(sid),fallback)}({sid})"


def map_choices():
    names=_current_data()['maps']
    return [f'{names[sid]}({sid})' for sid in sorted(names,key=int)]
