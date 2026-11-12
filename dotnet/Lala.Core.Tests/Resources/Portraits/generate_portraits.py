"""Synthetic complete-image oracle from the repository Python renderer. No official pixels.
Run from repository root with Pillow installed. Records the exact source digest.
"""
import hashlib, json
from pathlib import Path
from PIL import Image
from wlre.services.world.portrait_render import render, COLOR_PROFILE, PARTS
rows=[]
for seed in range(10):
    base=bytes((i*37+seed*19+11)%256 for i in range(256*256*4))
    mask=bytes((i*17+(i//4)*31+seed*43)%256 for i in range(256*256*4))
    palettes=[{}, {1:123456789}, {2:987654321,3:102030405,4:901234567,5:123456789}, {1:0,5:999999999}, {1:444900444}][seed%5]
    colors={} if seed<5 else {PARTS[1]:[2.5,7.5,1.25], '_13_EyeColor_':[9,0,5]}
    material=dict(color_profile=COLOR_PROFILE,shader='UI_ProfilePhotoWithMask',keywords=[],use_shape_mask=0,
                  mask_clip=[.2199999988079071,.05999999865889549,-1,1,.22][seed%5],edge_length=0 if seed<5 else .12,colors=colors)
    with Image.frombytes('RGBA',(256,256),base) as b, Image.frombytes('RGBA',(256,256),mask) as m:
        with render(b,m,palettes,material) as result:
            pixels=result.tobytes()
    rows.append(dict(seed=seed,palettes=palettes,colors=colors,clip=material['mask_clip'],edge=material['edge_length'],sha256=hashlib.sha256(pixels).hexdigest()))
source=Path('wlre/services/world/portrait_render.py')
Path(__file__).with_name('vectors.json').write_text(json.dumps(dict(source=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),vectors=rows),indent=2)+'\n')
