"""Verify pinned IL2CPP int-specialized deduplication method registrations.

Read-only binary/metadata inspection. Does not create live managed runtime state.
"""
import argparse
import io
import json
import struct
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA

METADATA_SHA='5a71da3a4b37486b056b9873655e42d7d7a583eae6ebfe2efdd18ebe66a23260'
# MethodSpec index, metadata definition, native address, declaring type, method.
EXPECTED=((44245,31487,0x1f50ee0,'List`1','Contains'),
          (44263,31509,0x1f51960,'List`1','IndexOf'),
          (79911,22219,0x2a270e0,'Array','IndexOf'),
          (80104,22319,0x25371d0,'Array','IndexOfImpl'),
          (26298,31702,0x164c9d8,'EqualityComparer`1','get_Default'),
          (30489,31713,0x2ce74f8,'GenericEqualityComparer`1','IndexOf'))


def inspect(binary,metadata):
    raw=checked_bytes(binary,IL2CPP_SHA);meta=checked_bytes(metadata,METADATA_SHA)
    from elftools.elf.elffile import ELFFile
    with io.BytesIO(raw) as f:
        elf=ELFFile(f);segments=[dict(s.header) for s in elf.iter_segments() if s['p_type']=='PT_LOAD'];rel={}
        for section in elf.iter_sections():
            if section['sh_type']=='SHT_RELA':
                for r in section.iter_relocations():
                    if r['r_info_type']==1027:rel[r['r_offset']]=r['r_addend']
    def offset(a,n=8):
        s=next(s for s in segments if s['p_vaddr']<=a and a+n<=s['p_vaddr']+s['p_filesz'])
        return s['p_offset']+a-s['p_vaddr']
    def ptr(a):return rel.get(a,struct.unpack_from('<Q',raw,offset(a))[0])
    h=struct.unpack_from('<64I',meta)
    if h[:2]!=(0xfab11baf,31):raise ValueError('Unexpected metadata format')
    strings=meta[h[6]:h[6]+h[7]]
    def name(i):return strings[i:strings.index(b'\0',i)].decode()
    mr=0x4890f98;cr=0x46f9288
    if ptr(mr+80)!=h[41]//88 or ptr(mr+96)!=h[41]//88:raise ValueError('Registration type-count mismatch')
    gp_count=ptr(cr+16);gp=ptr(cr+24);count=ptr(mr+32);table=ptr(mr+40);specs=ptr(mr+72);insts=ptr(mr+24)
    if gp_count!=0x1577d or count!=0x15822:raise ValueError('Unexpected registration sizes')
    selected={row[0]:row for row in EXPECTED};rows=[]
    for i in range(count):
        spec,method,invoker,adjustor=struct.unpack_from('<4i',raw,offset(table+i*16,16))
        if spec not in selected:continue
        expected=selected[spec]
        if not 0<=method<gp_count:raise ValueError('Invalid generic method pointer index')
        address=ptr(gp+method*8)
        definition,ci,mi=struct.unpack_from('<3i',raw,offset(specs+spec*12,12))
        if definition!=expected[1] or address!=expected[2]:raise ValueError('Registered method mismatch')
        m=struct.unpack_from('<7I4H',meta,h[12]+definition*36)
        type_name=name(struct.unpack_from('<I',meta,h[40]+m[1]*88)[0]);method_name=name(m[0])
        if (type_name,method_name)!=expected[3:]:raise ValueError('Metadata method name mismatch')
        generic=ci if ci>=0 else mi
        if generic<0 or (ci>=0 and mi>=0):raise ValueError('Unexpected generic context')
        inst=ptr(insts+generic*8)
        if ptr(inst)!=1:raise ValueError('Expected one type argument')
        typ=ptr(ptr(inst+8));bits=struct.unpack_from('<I',raw,offset(typ+8,4))[0]
        if (bits>>16)&255!=8:raise ValueError('Expected Int32 type argument')
        rows.append(dict(spec=spec,definition=definition,type=type_name,method=method_name,address=hex(address),type_argument='Int32'))
    if len(rows)!=len(EXPECTED):raise ValueError('Missing/duplicate registrations')
    return dict(binary_sha256=IL2CPP_SHA,metadata_sha256=METADATA_SHA,methods=rows,can_send_packets=False,
                scope='Pinned static registration identity, not runtime comparer construction or generic class initialization')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libil2cpp',required=True);parser.add_argument('--metadata',required=True);args=parser.parse_args()
    try:print(json.dumps(inspect(args.libil2cpp,args.metadata),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
