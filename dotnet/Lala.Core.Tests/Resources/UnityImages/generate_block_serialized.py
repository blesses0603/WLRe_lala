"""Owned compressed Texture2D/Sprite fixtures, real UnityPy writer/readback."""
import base64, copy, hashlib, json, runpy
from pathlib import Path
import UnityPy
here=Path(__file__).parent
source=runpy.run_path(str(here/'generate_serialized.py'))
rows=json.loads((here/'block_vectors.json').read_text())['vectors']
result=[]
for fmt in (10,12):
    v=next(v for v in rows if v['format']==fmt and v['width']==8 and v['x']==1)
    texture=copy.deepcopy(source['texture']);sprite=copy.deepcopy(source['sprite'])
    raw=base64.b64decode(v['payload'])
    texture.update(m_Width=v['width'],m_Height=v['height'],m_TextureFormat=fmt,m_CompleteImageSize=len(raw))
    texture['image data']=raw
    sprite['m_Rect'].update(width=v['w'],height=v['h'])
    sprite['m_RD']['textureRect'].update(x=v['x'],y=v['y'],width=v['w'],height=v['h'])
    bundle=source['old'].bundle(source['make'](sprite,texture))
    obj=next(o for o in UnityPy.load(bundle).objects if o.type.name=='Sprite').read()
    pixels=obj.image.convert('RGBA').tobytes()
    assert pixels==base64.b64decode(v['pixels'])
    result.append(dict(format=fmt,bundle=base64.b64encode(bundle).decode(),sha256=hashlib.sha256(bundle).hexdigest(),pixels=v['pixels']))
(here/'block_serialized.json').write_text(json.dumps(result,indent=2)+'\n')
