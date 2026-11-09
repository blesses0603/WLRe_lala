"""Owned field/pixel fixtures; no official asset or SerializedFile admission claim.
Run with UnityPy==1.25.4; SpriteHelper and Texture2DConverter are independent oracles.
"""
import base64, hashlib, json
from pathlib import Path
from types import SimpleNamespace as NS
import UnityPy
from UnityPy.export.SpriteHelper import get_image_from_sprite
assert UnityPy.__version__ == '1.25.4'
width, height = 4, 3
rgba = bytes((i * 37 + 11) % 256 for i in range(width * height * 4))
class Pointer:
    path_id = 2
    def __init__(self, texture): self.texture = texture
    def deref_parse_as_object(self): return self.texture
vectors = []
for fmt, channels in [(3, (0,1,2)), (4,(0,1,2,3)), (5,(3,0,1,2)), (14,(2,1,0,3))]:
    raw = bytes(rgba[i+c] for i in range(0,len(rgba),4) for c in channels)
    texture = NS(get_image_data=lambda:raw, m_Width=width, m_Height=height, m_TextureFormat=fmt,
                 object_reader=NS(version=(2021,3,45,2),platform=19))
    for x,y,w,h in [(0,0,4,3),(1,0,2,3),(0,1,3,2),(3,2,1,1),(1,1,1,1)]:
        sprite = NS(m_SpriteAtlas=None, m_AtlasTags=[], assets_file=NS(_cache={}),
                    m_RD=NS(texture=Pointer(texture),alphaTexture=None,
                            textureRect=NS(x=x,y=y,width=w,height=h),settingsRaw=2))
        image=get_image_from_sprite(sprite).convert('RGBA')
        pixels=image.tobytes()
        vectors.append(dict(format=fmt,width=width,height=height,x=x,y=y,w=w,h=h,
                            payload=base64.b64encode(raw).decode(),pixels=base64.b64encode(pixels).decode(),
                            pixel_sha256=hashlib.sha256(pixels).hexdigest(),source_sha256=hashlib.sha256(raw).hexdigest()))
Path(__file__).with_name('vectors.json').write_text(json.dumps({'oracle':'UnityPy 1.25.4 SpriteHelper + Texture2DConverter','vectors':vectors},indent=2)+'\n')
