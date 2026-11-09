"""Owned projection and fractional endpoint vectors; UnityPy/Pillow oracle."""
import base64,copy,gzip,hashlib,json,struct
from pathlib import Path
import generate_pixels as px
from UnityPy.helpers.Tpk import get_typetree_node
import UnityPy
b64=lambda b:base64.b64encode(b).decode()
# Preserve Float32 field conversion through a complete SerializedFile.
rows=[]
for rect in ((2.5,1.5,3,4),(1.5,.5,3,5),(2.49,1.01,3.02,4.98),(.07612038,.07612038,5.847763,5.847763)):
 for rotation in range(5):
  for alpha in (False,True):
   atlas=copy.deepcopy(px.atlas);sprite=copy.deepcopy(px.sprite)
   entry=atlas['m_RenderDataMap'][0][1];entry.update(textureRect=dict(zip(('x','y','width','height'),rect)),settingsRaw=3+(rotation<<2),alphaTexture=px.ptr(4 if alpha else 0))
   sprite['m_Rect'].update(width=9.,height=9.)
   bodies=[(687078895,px.encode(687078895,atlas)),(213,px.encode(213,sprite)),(28,px.encode(28,px.texture(4,17)))]
   if alpha:bodies.append((28,px.encode(28,px.texture(4,91))))
   asset=px.file(bodies);image=next(o for o in UnityPy.load(asset).objects if o.path_id==2).read().image.convert('RGBA')
   rows.append(dict(asset=b64(asset),width=image.width,height=image.height,pixels=b64(image.tobytes())))
# Include an unrelated Sprite with 65 valid physics shapes. Selected objects
# retain the same physics limits; container and all metadata remain checked.
root=get_typetree_node(142,px.v)
raw=[]
def walk(i):
 n=px.tpk.NodeBuffer[i];raw.append(n)
 for c in n.SubNodes:walk(c)
walk(px.tpk.ClassInformation[142].getVersionedClass(px.v).ReleaseRootNode)
for i,(n,r) in enumerate(zip(root.traverse(),raw)):
 n.m_Index=i;n.m_RefTypeHash=0;n.m_TypeFlags=r.TypeFlags
px.roots[142]=root;px.classes.append(142)
bundle=px.defaults(root);bundle['m_Name']='Owned';bundle['m_AssetBundleName']='Owned'
info={'preloadIndex':0,'preloadSize':0,'asset':px.ptr(1)}
bundle['m_Container']=[('Assets/ResourcesBuild/Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2',info)]
atlas=copy.deepcopy(px.atlas);sprite=copy.deepcopy(px.sprite)
atlas['m_RenderDataMap'][0][1]['alphaTexture']=px.ptr(0)
unused=copy.deepcopy(sprite);unused['m_Name']='Unused';unused['m_PhysicsShape']=[[{'x':0.,'y':0.}]]*65
base=[(687078895,px.encode(687078895,atlas)),(213,px.encode(213,sprite)),(28,px.encode(28,px.texture(4,17))),(213,px.encode(213,unused))]
cases={}
def save(name,a=atlas,b=bundle):
 bodies=base.copy();bodies[0]=(687078895,px.encode(687078895,a));bodies.append((142,px.encode(142,b)))
 cases[name]=b64(px.file(bodies))
save('unused')
a=copy.deepcopy(atlas);a['m_PackedSprites'].append(px.ptr(4));save('selected_physics',a)
b=copy.deepcopy(bundle);b['m_Container']*=2;save('duplicate_root',b=b)
b=copy.deepcopy(bundle);b['m_Container'][0][1]['asset']=px.ptr(2);save('wrong_root_class',b=b)
a=copy.deepcopy(atlas);a['m_PackedSprites']=[px.ptr(999)];save('missing_sprite',a)
a=copy.deepcopy(atlas);a['m_PackedSprites'][0]['m_FileID']=1;save('external_sprite',a)
Path(__file__).with_name('projection.json.gz').write_bytes(gzip.compress((json.dumps({'fractional':rows,'projection':cases},indent=2)+'\n').encode(),mtime=0))
print(len(rows),'fractional complete RGBA oracle cases;',len(cases),'projection files')
