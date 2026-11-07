"""Review-pinned combat tables and data-only Lua constants."""
import hashlib
import re
import struct
from wlre.services.parser_diagnostics import diagnosed
from wlre.services.world.itemdata_v1 import Reader, parse_itemdata, ITEMDATA_1296_SHA256
from wlre.services.world.normal_attack_catalog import parse_npcs as validate_npcs
from wlre.services.world.official_lua_codec import KNOWN_FILES

SKILL_SHA256='ed6383251b4f0fb9f7d9eb85c99346a268b99bdded839f6957f083c4b7f0545c'
SKILL_FIELDS=(('Name', 'I'), ('Sort', 'H'), ('Kind', 'B'), ('ID', 'H'), ('ReduceSP', 'H'), ('ReduceHP', 'B'), ('Element', 'B'), ('AtkKind', 'H'), ('FightWay', 'B'), ('Grade', 'B'), ('FightArea', 'B'), ('VariableA', 'H'), ('VariableB', 'H'), ('VariableC', 'B'), ('VariableD', 'H'), ('Round', 'B'), ('HitStatus', 'H'), ('InitSkillPot', 'B'), ('PreSkillId', 'H'), ('NextSkillId', 'H'), ('Spare1', 'H'), ('Spare2', 'H'), ('Spare3', 'H'), ('Spare4', 'H'), ('Spare5', 'H'), ('Spare6', 'H'), ('Spare7', 'H'), ('Spare8', 'H'), ('Spare9', 'H'), ('Spare10', 'H'), ('Desc', 'I'), ('HitID', 'H'), ('Key', 'H'), ('TargetKind', 'B'), ('GId', 'H'), ('CornerTag', 'B'), ('StatusId', 'H'), ('Duration', 'B'), ('WeaponKind1', 'B'), ('WeaponKind2', 'B'), ('WeaponKind3', 'B'), ('WeaponKind4', 'B'), ('WeaponKind5', 'B'), ('LvLimit', 'B'), ('Discolor', 'B'), ('HitBackId', 'H'), ('RangeKind1', 'B'), ('RangeKind2', 'B'), ('RangeKind3', 'B'), ('RangeKind4', 'B'), ('SpareByte1', 'B'), ('SpareByte2', 'B'), ('SpareByte3', 'B'), ('SpareByte4', 'B'), ('SpareByte5', 'B'), ('SoundKey', 'H'), ('SpareWord2', 'H'), ('SpareWord3', 'H'), ('SpareWord4', 'H'), ('SpareWord5', 'H'), ('SpareInt1', 'I'), ('SpareInt2', 'I'), ('SpareInt3', 'I'), ('SpareInt4', 'I'), ('SpareInt5', 'I'), ('KindSort', 'B'), ('MotionKind', 'B'), ('SPSkillTextureId', 'B'), ('TargetNPCID', 'H'), ('CostItemID', 'H'), ('CostItemCount', 'H'))


@diagnosed('combat-skill-reviewed-1296')
def parse_skills(raw):
    if hashlib.sha256(raw).hexdigest()!=SKILL_SHA256:raise ValueError('技能資料格式尚未驗證')
    count=struct.unpack_from('<I',raw)[0]
    if not 0<count<=10000 or len(raw)!=4+125*count:raise ValueError('Invalid skill record size')
    layout=struct.Struct('<'+''.join(kind for _,kind in SKILL_FIELDS));rows={}
    for index in range(count):
        row=dict(zip((name for name,_ in SKILL_FIELDS),layout.unpack_from(raw,4+index*125)))
        ident=row['ID']
        if not ident or str(ident) in rows:raise ValueError('Invalid or duplicate skill ID')
        rows[str(ident)]=row
    return rows


def _block(text,name):
    match=re.search(r'\b'+re.escape(name)+r'\s*=\s*\{',text)
    if not match:raise ValueError('Missing official constant: '+name)
    start=match.end();depth=1
    for i in range(start,len(text)):
        if text[i]=='{':depth+=1
        elif text[i]=='}':
            depth-=1
            if not depth:return text[start:i]
    raise ValueError('Unterminated official table')


def _enum(text,name):
    rows=re.findall(r'(\w+)\s*=\s*(\d+)',_block(text,name))
    if len(dict(rows))!=len(rows):raise ValueError('Duplicate enum key')
    return {k:int(v) for k,v in rows}


def parse_constants(define,fight):
    for name,text in (('Define.lua',define),('FightUnit.lua',fight)):
        if hashlib.sha256(text.encode('utf-8')).hexdigest()!=KNOWN_FILES[name][1]:
            raise ValueError('Unreviewed combat Lua text')
    elements=_enum(define,'EElementType');sex=_enum(define,'ERoleType');weights={}
    for label,body in re.findall(r'\[EElementType\.(\w+)\]\s*=\s*\{([^}]+)\}',_block(fight,'elementAttackTimes')):
        row={str(elements[k]):float(v) for k,v in re.findall(r'\[EElementType\.(\w+)\]\s*=\s*([\d.]+)',body)}
        weights[str(elements[label])]=row
    if set(weights)!=set(map(str,range(5))) or any(set(row)!=set(weights) for row in weights.values()):
        raise ValueError('Incomplete element matrix')
    characters=[]
    for ident,body in re.findall(r'\[(\d+)\]\s*=\s*\{([^}]+)\}',_block(define,'CHARACTER_DATAS')):
        if int(ident)!=len(characters)+1:raise ValueError('Unexpected character order')
        def number(key):
            match=re.search(r'\b'+key+r'\s*=\s*(\d+)',body)
            if not match:raise ValueError('Missing character field')
            return int(match.group(1))
        gender=re.search(r'sex\s*=\s*ERoleType\.(\w+)',body)
        if not gender:raise ValueError('Missing character type')
        characters.append(dict(sex=sex[gender.group(1)],head=number('headStyle'),
                               skill=number('firstSkill'),body=number('InitialEquip')))
    if len(characters)!=15:raise ValueError('Incomplete reviewed character table')
    return characters,weights


def build_catalog(skill_raw,npc_raw,item_raw,texts,clear):
    if hashlib.sha256(item_raw).hexdigest()!=ITEMDATA_1296_SHA256:raise ValueError('Unreviewed combat ItemData')
    validate_npcs(npc_raw)
    reader=Reader(npc_raw);npcs={}
    for _ in range(reader.u32()):
        name=reader.utf16(allow_empty=True);reader.utf16(allow_empty=True);fields=reader.take(203)
        ident=struct.unpack_from('<H',fields,1)[0]
        npcs[str(ident)]={'name':name,'skills':list(struct.unpack_from('<5H',fields,75))}
    items={str(k):{field:v[field] for field in ('name','kind','attributes','special','restrict','skill_link','fit_type')}
           for k,v in parse_itemdata(item_raw,include_skill_link=True).items()}
    skills=parse_skills(skill_raw)
    for row in skills.values():
        row['name']=texts.get(row['Name'])
        description=texts.get(row['Desc'])
        row['description']=description if isinstance(description,str) else ''
        if not isinstance(row['name'],str) or not row['name']:raise ValueError('Missing official skill name')
    keys={}
    for ident,row in skills.items():
        key=row['Key']
        if key:
            if str(key) in keys:raise ValueError('Ambiguous skill key')
            keys[str(key)]=int(ident)
    characters,weights=parse_constants(clear['Define.lua'],clear['FightUnit.lua'])
    return dict(skills=skills,keys=keys,items=items,npcs=npcs,characters=characters,element_weights=weights)


def load_verified_catalog(manifest,bundle_root,loader,root,identity,sources,texts):
    from pathlib import Path
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.world.catalog_adapters import SourceContract
    from wlre.services.world.official_catalog_pipeline import AssetBinding
    from wlre.services.world.unity_textasset import extract_textasset
    from wlre.services.world.official_combat_sources import load_inputs
    from wlre.storage.normalized_resources import load_parsed
    asset='Assets/ResourcesBuild/Data/SkillData_C.bytes'
    plan=build_update_plan(manifest,asset_paths=(asset,),cache_root=bundle_root)
    if not plan.entries or any(e.action!='cached' for e in plan.entries):raise ValueError('官方技能 Bundle 尚未同步')
    paths=tuple(e.spec.cache_path(bundle_root) for e in plan.entries)
    if any(not _verified_file(p,e.spec) for p,e in zip(paths,plan.entries)):raise ValueError('技能 Bundle 驗證失敗')
    binding=AssetBinding(asset,SourceContract('scenes','SkillData_C','stage-new-76-v1','0'*64,'DataPackage',manifest.spec.package_version))
    skill_raw=extract_textasset(binding,paths,loader=loader)
    clear,lua_inputs=load_inputs(root,identity.data_ver)
    inputs={**lua_inputs,'SkillData_C':skill_raw,**{name:sources[name] for name in ('NpcData_C','ItemData_C','TextData_C')}}
    return load_parsed(Path(root)/'derived_catalogs'/'resource_inventory.sqlite3',identity.key,
        'combat','combat-reviewed-v2',inputs,
        lambda:build_catalog(skill_raw,sources['NpcData_C'],sources['ItemData_C'],texts,clear))
