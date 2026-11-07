"""Bounded static write-pattern and cached-Lua audit for OnAwakeSettings.

This is a candidate finder, not exhaustive control-flow/reflection analysis.
No Lua is executed, downloaded or imported into the product allowlist.
"""
import argparse
import array
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA
from wlre.services.world.official_lua_codec import METADATA_SHA256,_parameters,_cbc_decode

INDEX_SHA='7500fb403dac39b7eb555ff3b99be6cbedc9b25987141847f5e9f44be6e7b8c8'
KNOWN_WRITES={0x1a79820:'AstarPath.OnDestroy: clear',0x1b4a330:'AstarPathWrap.set_OnAwakeSettings: non-null delegate',0x1b4a350:'AstarPathWrap.set_OnAwakeSettings: null/general branch'}


def inspect(il2cpp,metadata,lua_root):
    raw=checked_bytes(il2cpp,IL2CPP_SHA);path=Path(metadata)
    if path.stat().st_size>16*1024*1024:raise ValueError('Metadata bound')
    meta=path.read_bytes()
    if hashlib.sha256(meta).hexdigest()!=METADATA_SHA256:raise ValueError('Unreviewed metadata digest')
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    with io.BytesIO(raw) as stream:segments=[dict(s.header) for s in ELFFile(stream).iter_segments() if s['p_type']=='PT_LOAD']
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);decoder.detail=True
    def code(address,length):
        segment=next(s for s in segments if s['p_vaddr']<=address and address+length<=s['p_vaddr']+s['p_filesz'])
        offset=segment['p_offset']+address-segment['p_vaddr'];return raw[offset:offset+length]
    references=[]
    for segment in segments:
        if not segment['p_flags']&1:continue
        start=segment['p_offset'];size=segment['p_filesz'];words=array.array('I',raw[start:start+size-size%4])
        if sys.byteorder!='little':words.byteswap()
        for i,word in enumerate(words):
            if word&0x9f000000!=0x90000000:continue
            immediate=((word>>5)&0x7ffff)<<2|((word>>29)&3)
            if immediate&(1<<20):immediate-=1<<21
            address=segment['p_vaddr']+4*i
            if (address&~4095)+(immediate<<12)!=0x498a000:continue
            instructions=list(decoder.disasm(code(address,128),address));register='x'+str(word&31)
            if any(i.mnemonic=='ldr' and i.op_str.endswith('['+register+', #0x430]') for i in instructions[:24]):references.append(address)
    found={}
    # Deliberately limited straight-line taint windows. Calls clobber caller-saved
    # registers; branches are not a complete CFG. Results cannot prove absence.
    for start in references:
        state={};instructions=list(decoder.disasm(code(start,768),start))
        for i,instruction in enumerate(instructions):
            text=instruction.op_str;old=dict(state)
            for register in instruction.regs_access()[1]:state.pop(instruction.reg_name(register),None)
            if instruction.mnemonic=='adrp' and text.endswith('#0x498a000'):state[text.split(',')[0]]=('page',0)
            elif instruction.mnemonic=='mov':
                parts=text.split(', ')
                if len(parts)==2 and parts[1] in old:state[parts[0]]=old[parts[1]]
            elif instruction.mnemonic in ('ldr','ldur','str','stur'):
                match=re.fullmatch(r'(x\d+|xzr), \[(x\d+)(?:, #(-?0x[0-9a-f]+|\d+))?\]!?',text)
                if match:
                    register,base,offset=match.groups();offset=int(offset or '0',0);kind=old.get(base)
                    if instruction.mnemonic in ('ldr','ldur'):
                        if kind==('page',0) and offset==0x430:state[register]=('slot',0)
                        elif kind==('slot',0) and offset==0:state[register]=('class',0)
                        elif kind==('class',0) and offset==0xb8:state[register]=('static',0)
                    elif kind and kind[0]=='static' and kind[1]+offset==0x20:
                        found[instruction.address]=dict(address=hex(instruction.address),reviewed_identity=KNOWN_WRITES.get(instruction.address,'unreviewed candidate'),context=[f'{x.address:x}: {x.mnemonic} {x.op_str}' for x in instructions[max(0,i-12):i+10]])
            elif instruction.mnemonic=='add':
                match=re.fullmatch(r'(x\d+), (x\d+), #(0x[0-9a-f]+|\d+)',text)
                if match:
                    dest,base,offset=match.groups();kind=old.get(base)
                    if kind and kind[0]=='static':state[dest]=('static',kind[1]+int(offset,0))
            if instruction.mnemonic in ('bl','blr'):
                for n in range(19):state.pop('x'+str(n),None)
            if instruction.mnemonic=='ret':break
    root=Path(lua_root)
    if (root/'index.json').stat().st_size>1024*1024:raise ValueError('Lua index bound')
    index_raw=(root/'index.json').read_bytes()
    if len(index_raw)>1024*1024 or hashlib.sha256(index_raw).hexdigest()!=INDEX_SHA:raise ValueError('Unreviewed official Lua index digest')
    index=json.loads(index_raw);files=sorted((root/'decoded').glob('*.lua'))
    if not 1<=len(files)<=64:raise ValueError('Cached Lua inventory bound')
    key,iv=_parameters(meta);lua=[];total=0
    for file in files:
        if file.stat().st_size>2*1024*1024:raise ValueError('Decoded Lua size bound')
        cipher_path=root/file.name
        with cipher_path.open('rb') as stream:cipher=stream.read(2*1024*1024+1)
        digest=hashlib.md5(cipher,usedforsecurity=False).hexdigest()
        candidates=[name for name,expected in index.items() if name.rsplit('/',1)[-1]==file.name and expected==digest]
        if len(candidates)!=1:raise ValueError('Missing/ambiguous cached Lua path and MD5 identity')
        clear=_cbc_decode(cipher,key,iv)
        if clear!=file.read_bytes():raise ValueError('Decoded cache differs from verified cipher')
        total+=len(clear)
        if total>20*1024*1024:raise ValueError('Lua aggregate bound')
        text=clear.decode('utf-8-sig');hits=[i+1 for i,line in enumerate(text.splitlines()) if 'OnAwakeSettings' in line]
        lua.append(dict(path=candidates[0],input_sha256=hashlib.sha256(cipher).hexdigest(),output_sha256=hashlib.sha256(clear).hexdigest(),literal_line_hits=hits))
    return dict(il2cpp_sha256=IL2CPP_SHA,metadata_sha256=METADATA_SHA256,lua_index_sha256=INDEX_SHA,type_reference_windows=len(references),write_candidates=[found[k] for k in sorted(found)],verified_cached_lua=lua,indexed_lua_count=len(index),actual_callback_target_verified=False,override_result_verified=False,can_send_packets=False,scope=__doc__)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--metadata',required=True);parser.add_argument('--lua-root',required=True);args=parser.parse_args()
    print(json.dumps(inspect(args.libil2cpp,args.metadata,args.lua_root),sort_keys=True))


if __name__=='__main__':main()
