"""Pinned native Lua bootstrap literals and instructions, not runtime execution."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA
from wlre.services.world.official_lua_codec import METADATA_SHA256


def review(libil2cpp,metadata):
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    raw=checked_bytes(libil2cpp,IL2CPP_SHA)
    with Path(metadata).open('rb') as stream:meta=stream.read(16*1024*1024+1)
    if hashlib.sha256(meta).hexdigest()!=METADATA_SHA256:raise ValueError('Unreviewed metadata')
    elf=ELFFile(io.BytesIO(raw));segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD'];rel={}
    for section in elf.iter_sections():
        if section['sh_type']=='SHT_RELA':
            for row in section.iter_relocations():
                if row['r_info_type']==1027:rel[row['r_offset']]=row['r_addend']
    def offset(address,size=8):
        for s in segments:
            if s['p_vaddr']<=address and address+size<=s['p_vaddr']+s['p_filesz']:return s['p_offset']+address-s['p_vaddr']
        raise ValueError('Unmapped native range')
    def pointer(address):return rel.get(address,struct.unpack_from('<Q',raw,offset(address))[0])
    h=struct.unpack_from('<64I',meta);literals=[]
    for slot,expected in ((0x49ace70,'Logic/'),(0x49acea0,'/Lua'),(0x4965968,'LuaArtifact'),(0x49382e8,'Initialize'),(0x4992ed8,'Update')):
        encoded=pointer(pointer(slot))
        if encoded>>29!=5:raise ValueError('Unexpected literal slot')
        index=(encoded&0x1fffffff)>>1
        if index*8+8>h[3]:raise ValueError('Literal index bound')
        size,start=struct.unpack_from('<II',meta,h[2]+index*8)
        if not 0<size<=128 or start+size>h[5]:raise ValueError('Literal bounds')
        value=meta[h[4]+start:h[4]+start+size].decode('utf-8')
        if value!=expected:raise ValueError('Bootstrap literal changed')
        literals.append(dict(slot=hex(slot),index=index,value=value))
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);instructions=[]
    # Exact pinned sites, selected from full-method disassembly. No claim of a
    # complete control-flow graph or absence of other writes to the static slot.
    sites={0x3100640:('str','x1, [x0, #0x18]!'),0x30ff3a4:('ldr','x1, [x8, #0x18]'),
           0x30ff3ac:('bl','#0x194cc9c'),0x30ff3c8:('b','#0x3630400'),
           0x1586098:('bl','#0x30ffab4')}
    for address,expected in sites.items():
        decoded=list(decoder.disasm(raw[offset(address,4):offset(address,4)+4],address))
        if len(decoded)!=1 or (decoded[0].mnemonic,decoded[0].op_str)!=expected:raise ValueError('Bootstrap instruction changed')
        instructions.append(dict(address=hex(address),mnemonic=expected[0],operands=expected[1]))
    return dict(il2cpp_sha256=IL2CPP_SHA,metadata_sha256=METADATA_SHA256,literals=literals,
                checked_instructions=instructions,scope=__doc__,runtime_execution_verified=False,
                callback_state_verified=False,all_static_writes_verified=False,can_send_packets=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--libil2cpp',required=True);p.add_argument('--metadata',required=True);a=p.parse_args()
    print(json.dumps(review(a.libil2cpp,a.metadata),sort_keys=True))


if __name__=='__main__':main()
