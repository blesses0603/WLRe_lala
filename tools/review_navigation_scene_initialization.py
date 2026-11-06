"""Pinned-source static initialization evidence; does not execute Unity Awake.

Records the verified scene-load call and native OnAwakeSettings indirect-call
boundary. The callback's runtime target and post-Awake values remain unknown.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
from tools.review_navigation_rotation import checked_bytes,IL2CPP_SHA

STAGE_SHA='784b5098241463159112b29fa81ca23dfa9a2cc24dd3fe20ec29f1a05df52605'


def inspect(il2cpp,stage_source):
    raw=checked_bytes(il2cpp,IL2CPP_SHA);path=Path(stage_source)
    if path.stat().st_size>1024*1024:raise ValueError('Stage source exceeds bound')
    source=path.read_bytes()
    if hashlib.sha256(source).hexdigest()!=STAGE_SHA:raise ValueError('Unreviewed Stage source digest')
    call=b'CGResource.LoadScene(sceneName, sceneName, this.OnLoadStage, this.stageId)'
    if source.count(call)!=1:raise ValueError('Ambiguous scene-load call')
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    with io.BytesIO(raw) as stream:segments=[dict(s.header) for s in ELFFile(stream).iter_segments() if s['p_type']=='PT_LOAD']
    def code(address,size):
        segment=next(s for s in segments if s['p_vaddr']<=address and address+size<=s['p_vaddr']+s['p_filesz'])
        offset=segment['p_offset']+address-segment['p_vaddr'];return raw[offset:offset+size]
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    instructions=[dict(address=hex(i.address),mnemonic=i.mnemonic,operands=i.op_str) for i in decoder.disasm(code(0x1a78a1c,0x38),0x1a78a1c)]
    expected={0x1a78a1c:('ldr','x8, [x0, #0xb8]'),0x1a78a20:('ldr','x8, [x8, #0x20]'),
              0x1a78a24:('cbz','x8, #0x1a78a54'),0x1a78a44:('ldr','x9, [x8, #0x18]'),0x1a78a50:('blr','x9')}
    observed={int(i['address'],16):(i['mnemonic'],i['operands']) for i in instructions}
    if any(observed.get(address)!=value for address,value in expected.items()):raise ValueError('Unreviewed Awake callback sequence')
    return dict(il2cpp_sha256=IL2CPP_SHA,stage_sha256=STAGE_SHA,scene_load_call=call.decode(),
                callback_field='AstarPath.OnAwakeSettings',callback_static_offset=32,awake_callback_instructions=instructions,
                callback_target_verified=False,post_awake_profile_verified=False,can_send_packets=False,scope=__doc__)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);parser.add_argument('--stage-source',required=True);args=parser.parse_args()
    print(json.dumps(inspect(args.libil2cpp,args.stage_source),sort_keys=True))


if __name__=='__main__':main()
