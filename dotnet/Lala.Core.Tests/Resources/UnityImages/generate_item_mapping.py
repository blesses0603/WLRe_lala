"""Owned vectors from the repository's actual Python item-image functions; no network."""
import json
from pathlib import Path
from types import SimpleNamespace
from wlre.services.world.item_image_database import PREFIX, image_paths, ItemImageCatalog

cases=[]
for names in [('s1000.png','s0020.png'),('s1000.png','s01000.png'),('s0000.png',),('s65536.png',),('s100.png',),('s100000.png',),('s１２３４.png',),('s1001.PNG',),('../s1001.png',),('s+100.png',)]:
    manifest=SimpleNamespace(index={'assets':[{'path':PREFIX+n} for n in names]})
    try:
        paths=image_paths(manifest)
        valid=PREFIX+'s1000.png' in paths # load_verified_images requires the exact fallback
    except ValueError:
        valid=False
    cases.append(dict(names=names,valid=valid))
catalog=ItemImageCatalog(SimpleNamespace(models=frozenset({1000,20})),{1:20,2:0,3:9999})
result={'cases':cases,'icons':{str(i):catalog.icon(i) for i in [1,2,3,65535]}}
Path(__file__).with_name('item_mapping_vectors.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
