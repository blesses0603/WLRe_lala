"""Offline, fail-closed decoder for six independently reviewed official Lua files.

No client code is executed. No keys or Lua content are shipped: content codec
parameters come from the fingerprint-checked public client metadata supplied
by the operator. See docs/OFFICIAL_CLIENT_LUA_DECODING.md for evidence.
Optional research dependency: pycryptodome (not required by LaLa runtime).
"""
import hashlib
from pathlib import Path
import struct

METADATA_SHA256 = '5a71da3a4b37486b056b9873655e42d7d7a583eae6ebfe2efdd18ebe66a23260'
MAX_LUA_BYTES = 2 * 1024 * 1024
KNOWN_FILES = {'EmojiData.lua': ('a2e7d0bd5b9c732fbc507bae0cec109862209ee93a1cf8b17a575cb89520171b', '84f2d17ccd8fd232b89bc65d83e23882c68c759535a83c5ebf0b5a1757fef698'), 'ItemData.lua': ('a102fea143c4e9f953c67b07c030c7212379538beb159d360020be4c31b3b115', '438f5470cc1fc1f09661935bf210135ad0f22aeaf536d9a5c18f17646c062d42'), 'NpcTalkData.lua': ('761ee4f272fd65138cd4bb51db71b443c1cb961ff6314a483d384d2d66041e26', '2ea284d5d2ccca42fad4b684c55c0e9a8dc706f14bcbcc4d9032399f9b5fc0a5'), 'SkillData.lua': ('1304e566b6f33e23d4cdc569e35b350a4c5eaa438c8942f126f4f96af000cb3c', '962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228'), 'SkillMotionData.lua': ('9682ce2874f540bafebe50d37efcc7589b2dab018c8891558782f05e80ab7dcd', '54fb4daf742c8379fc9778d00f2a4329355250277a6d9c607236c68b419d4c0b'), 'StageMapData.lua': ('ba17aafad21c0529bffe1dd472268c7f37463234602c95afbd87e2d9e6a21631', 'fcd4b5704ff46341cb0307c5e1d5be753c69fd9a7c6b6361af26c3cabeb49a06')}


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _parameters(metadata):
    if type(metadata) is not bytes or _digest(metadata) != METADATA_SHA256:
        raise ValueError('Official client metadata fingerprint is not reviewed')
    if len(metadata)<256:
        raise ValueError('Truncated metadata')
    h=struct.unpack_from('<64I',metadata)
    if h[:2]!=(0xfab11baf,31):
        raise ValueError('Unsupported metadata format')
    def literal(index):
        if index*8+8>h[3] or h[2]+h[3]>len(metadata) or h[4]+h[5]>len(metadata):
            raise ValueError('Invalid metadata string region')
        size,start=struct.unpack_from('<II',metadata,h[2]+index*8)
        if not 0<size<=128 or start+size>h[5]:
            raise ValueError('Invalid codec literal')
        value=metadata[h[4]+start:h[4]+start+size]
        value.decode('utf-8','strict')
        return value
    # Exact literals referenced by ProjectSetting..cctor into static +0x30/+0x38.
    key,iv=literal(1571),literal(1667)
    if len(key)!=16 or len(iv)!=16:
        raise ValueError('Unsupported codec parameters')
    return key,iv


def _cbc_decode(raw,key,iv):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad,pad
    if type(raw) is not bytes or not 0<len(raw)<=MAX_LUA_BYTES or len(raw)%16:
        raise ValueError('Invalid encrypted Lua size')
    clear=unpad(AES.new(key,AES.MODE_CBC,iv).decrypt(raw),16)
    if AES.new(key,AES.MODE_CBC,iv).encrypt(pad(clear,16))!=raw:
        raise ValueError('Lua cipher round trip failed')
    clear.decode('utf-8-sig','strict')
    return clear


def decode_reviewed(name,raw,metadata):
    expected=KNOWN_FILES.get(name)
    if expected is None or type(raw) is not bytes or _digest(raw)!=expected[0]:
        raise ValueError('Lua source fingerprint is not reviewed')
    key,iv=_parameters(metadata)
    clear=_cbc_decode(raw,key,iv)
    if _digest(clear)!=expected[1]:
        raise ValueError('Decoded Lua does not match independent reviewed evidence')
    return clear


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    target=args.output.expanduser().resolve()
    if any((p/'.git').exists() for p in (target,*target.parents)):
        parser.error('Decoded official Lua must remain outside Git worktrees')
    if args.input.stat().st_size>MAX_LUA_BYTES or args.metadata.stat().st_size>16*1024*1024:
        parser.error('Input exceeds research bounds')
    clear=decode_reviewed(args.input.name,args.input.read_bytes(),args.metadata.read_bytes())
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as stream:stream.write(clear)
    print('Verified Lua written:',len(clear),'bytes; sha256',_digest(clear))


if __name__=='__main__':
    main()
