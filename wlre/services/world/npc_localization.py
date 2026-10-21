"""Separate official 1262 NPC battle quotes from event TalkData.

NpcTalkData_C references TextData_C, never TalkData_C. Optional text file
must be independently verified before loading. This module does not issue packets.
"""
import gzip
import hashlib
import json
from pathlib import Path

from wlre.paths import RESOURCE_ROOT
from wlre.services.world.npc_asset_install import ASSETS, MAX_UNCOMPRESSED


def _catalog(filename, expected_source, path=None):
    target=Path(path) if path is not None else RESOURCE_ROOT/filename
    if not target.is_file():return {}
    if path is None:
        expected_digest, expected_size, _, _, _ = ASSETS[filename]
        if (target.stat().st_size != expected_size
                or hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest):
            raise ValueError('官方 1262 本地化檔案 SHA-256 或大小不符')
    with gzip.open(target,'rb') as stream:
        data=stream.read(MAX_UNCOMPRESSED+1)
    if len(data)>MAX_UNCOMPRESSED:raise ValueError('本地化資源解壓超出限制')
    doc=json.loads(data.decode('utf-8'))
    if (not isinstance(doc,dict) or doc.get('version')!=1262
            or doc.get('source')!=expected_source
            or not isinstance(doc.get('records'),dict)):
        raise ValueError('本地化資源來源或結構不正確')
    if path is None:
        _,_,_,expected_sha,expected_count=ASSETS[filename]
        if doc.get('source_sha256')!=expected_sha or len(doc['records'])!=expected_count:
            raise ValueError('官方 1262 本地化來源 SHA256 或數量不符')
    return doc['records']


def load_text_data(path=None):
    data=_catalog('npc_text_1262.json.gz','TextData_C',path)
    result={}
    for key,value in data.items():
        if (not isinstance(key,str) or not key.isdecimal()
                or str(int(key))!=key or not 0<=int(key)<=4294967295
                or not isinstance(value,str) or len(value)>8192):
            raise ValueError('TextData_C 文字索引有誤')
        result[int(key)]=value
    return result


def load_battle_talk(path=None):
    data=_catalog('npc_battle_talk_1262.json.gz','NpcTalkData_C',path)
    result={}
    for key,entries in data.items():
        if (not isinstance(key,str) or not key.isdecimal() or
                str(int(key))!=key or not isinstance(entries,list) or len(entries)>255):
            raise ValueError('NpcTalkData_C 群組無效')
        validated=[]
        for row in entries:
            if (not isinstance(row,dict)
                or any(type(row.get(field)) is not int
                       for field in ('text_id','kind','parameter','duration'))
                or not 0<=row['text_id']<=4294967295):
                raise ValueError('NpcTalkData_C 條目無效')
            validated.append(row.copy())
        result[int(key)]=validated
    return result


def battle_lines(group,battle_data,text_data):
    """Read-only resolved quotes. Never invent fallback dialogue text."""
    return [(row['text_id'],text_data[row['text_id']])
            for row in battle_data.get(group,()) if row['text_id'] in text_data]
