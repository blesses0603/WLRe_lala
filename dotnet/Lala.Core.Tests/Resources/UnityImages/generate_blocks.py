"""Owned BC1/BC3 vectors, UnityPy 1.25.4 actual converter + SpriteHelper.
No official asset bytes. Deterministic random blocks cover endpoint/selector cases.
"""
import base64, hashlib, json, random, struct
from pathlib import Path
from types import SimpleNamespace as NS
import UnityPy
from UnityPy.export.SpriteHelper import get_image_from_sprite
assert UnityPy.__version__ == '1.25.4'
class Pointer:
    path_id = 2
    def __init__(self, texture): self.texture = texture
    def deref_parse_as_object(self): return self.texture
rng = random.Random(8053)
rows = []
for fmt in (10,12):
    for w,h in [(1,1),(3,2),(4,4),(5,7),(8,8),(12,4)]:
        for mode in range(4):
            blocks=[]
            for _ in range(((w+3)//4)*((h+3)//4)):
                a,b = [(0xffff,0),(0,0xffff),(0x8410,0x8410),(rng.randrange(65536),rng.randrange(65536))][mode]
                color=struct.pack('<HHI',a,b,0xe4e4e4e4 if mode<3 else rng.getrandbits(32))
                if fmt==12:
                    a0,a1=[(255,0),(0,255),(127,127),(rng.randrange(256),rng.randrange(256))][mode]
                    indices=sum((i%8)<<(3*i) for i in range(16))
                    color=bytes([a0,a1])+indices.to_bytes(6,'little')+color
                blocks.append(color)
            raw=b''.join(blocks)
            texture=NS(get_image_data=lambda:raw,m_Width=w,m_Height=h,m_TextureFormat=fmt,
                       object_reader=NS(version=(2021,3,45,2),platform=19))
            for x,y,cw,ch in [(0,0,w,h),(min(1,w-1),min(1,h-1),max(1,w-2),max(1,h-2))]:
                sprite=NS(m_SpriteAtlas=None,m_AtlasTags=[],assets_file=NS(_cache={}),
                          m_RD=NS(texture=Pointer(texture),alphaTexture=None,textureRect=NS(x=x,y=y,width=cw,height=ch),settingsRaw=2))
                pixels=get_image_from_sprite(sprite).convert('RGBA').tobytes()
                rows.append(dict(format=fmt,width=w,height=h,x=x,y=y,w=cw,h=ch,payload=base64.b64encode(raw).decode(),
                                 pixels=base64.b64encode(pixels).decode(),pixel_sha256=hashlib.sha256(pixels).hexdigest(),source_sha256=hashlib.sha256(raw).hexdigest()))
Path(__file__).with_name('block_vectors.json').write_text(json.dumps({'oracle':'UnityPy 1.25.4 SpriteHelper + Texture2DConverter','vectors':rows},indent=2)+'\n')
