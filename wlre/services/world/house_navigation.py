"""Source-checked S7/S12 floor context; no defaults for unobserved house size."""
HOUSE_MIN=63501
HOUSE_MAX=65500
HOUSE_TEMPLATES={1:10299,2:10298,3:10000}


def decode_floor_extension(raw):
    """Stage.ReceiveChangeMap reads optional UInt16, floor, size and size-index.

    Unknown/truncated layouts remain observable but grant no model mapping.
    Never treat S62-64 (which has no floor payload) as a floor number.
    """
    if type(raw) is not bytes or len(raw) not in (1,3,5):
        return {'verified':False}
    payload=raw[2:] if len(raw)>2 else raw
    floor=payload[0]+1
    if not 1<=floor<=4:return {'verified':False}
    result={'verified':True,'floor':floor}
    if len(payload)==3:
        size,index=payload[1],payload[2]+1
        if size not in HOUSE_TEMPLATES or not 1<=index<=4:return {'verified':False}
        result.update(size=size,size_floor=index)
    return result


def update_context(previous,scene,extension):
    if type(scene) is not int or not HOUSE_MIN<=scene<=HOUSE_MAX:return None
    if not isinstance(extension,dict) or extension.get('verified') is not True:
        return {'scene':scene,'verified':False}
    sizes=dict(previous.get('sizes',{})) if isinstance(previous,dict) and previous.get('scene')==scene and previous.get('verified') is True else {}
    if 'size' in extension:sizes[str(extension['size_floor'])]=extension['size']
    return dict(scene=scene,floor=extension['floor'],sizes=sizes,verified=True)


def resolve_house_stage(scene,context):
    from wlre.services.world.navigation import NavigationError
    if (not isinstance(context,dict) or context.get('verified') is not True
            or context.get('scene')!=scene or not HOUSE_MIN<=scene<=HOUSE_MAX):
        raise NavigationError('房屋樓層尚未由目前場景的伺服器封包確認。')
    floor=context.get('floor');size=context.get('sizes',{}).get(str(floor))
    if type(floor) is not int or not 1<=floor<=4 or type(size) is not int or size not in HOUSE_TEMPLATES:
        raise NavigationError('目前樓層大小尚未確認，不能推定房屋模型。')
    return HOUSE_TEMPLATES[size]


REVIEWED_STAGE_ORDER='1f1bd5ad718542a8469812a5cdabc12155a24ac01fdac6e2dc2506d82c3c41dd'


def instance_aliases(stages):
    """Data.OnLoadSceneData assigns IDs in binary record order, never sorted ID."""
    import hashlib
    import json
    from wlre.services.world.navigation import NavigationError
    order=hashlib.sha256(json.dumps(list(stages),separators=(',',':')).encode()).hexdigest()
    if order!=REVIEWED_STAGE_ORDER:
        raise NavigationError('副本場景的官方原始順序未通過驗證。')
    aliases={};next_id=61501
    for scene,row in stages.items():
        members=row.get('max_members');rooms=row.get('room_capacity')
        if type(members) is not int or not 0<=members<=255 or type(rooms) is not int or not 0<=rooms<=255:
            raise NavigationError('副本場景欄位無效。')
        if members:
            for _ in range(rooms):
                if next_id>62000 or next_id in stages:raise NavigationError('副本場景別名衝突或超出已審核範圍。')
                aliases[next_id]=scene;next_id+=1
    return aliases
