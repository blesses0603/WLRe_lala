"""Offline, fail-closed decoder for independently reviewed official Lua files.

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
KNOWN_FILES = {'Attribute.lua': ('8ffef7d396a0d55eb09859a3f7f5789e4295203ae4e7696f141047e3ea39df95',
                   '37427f02cd62302032c5a77ca66e1e51f6586aaa8ebf23b95cb5be96dfd26fc8'),
 'Bag.lua': ('c670a80f3bfaff53639bdaf1cb0d63ca1b53a4e47c92b46bb3d295c8483973e0',
             '5db2707db0e17219314dc292f6c3d142a6170898626a1f7fb2f4d123c4512c70'),
 'CreateRoleData.lua': ('593186ca3902719d02eaecec84e97aaa022c53457acd0a58f022e5dc63dd7801',
                        'e4d7d7d62e01864f5e46b190db34bfdef5026565d222020c6fa33d99914b31ca'),
 'Define.lua': ('e91e32a77d5ce5aa5b039fdd2584eb606b07298af11205c8aff6552343341140',
                '452e32903a686f22b8e98c1707efca80a45dcf73fd4f1bd5e7e08b38ae3db92c'),
 'EmojiData.lua': ('a2e7d0bd5b9c732fbc507bae0cec109862209ee93a1cf8b17a575cb89520171b',
                   '84f2d17ccd8fd232b89bc65d83e23882c68c759535a83c5ebf0b5a1757fef698'),
 'FightManager.lua': ('9e4d0c71d58fdb7a7261304ff7c791c521a1a86a4f17b29962424b46504c0f11',
                      '6b40ba250a2406193fc022a536c95addcb9034a899304a9d0f24d98c46c50004'),
 'FightUnit.lua': ('b708a1f58d8f3fbe1830efab59f8327cfce0a5a3488b6e33ebff1bba81fba836',
                   '4c0366884264b14765192c2b7d1644439898edfc06bf29dea988f6de6bf75d88'),
 'Function.lua': ('7b1d8bb32c0a71f92f2f8fbaa050d6ce1219d90bee24109666a3537cdb3cb5b6',
                  '2ed9b6b981d2b0d5b99f773a40c0493495f06e47f709046b51dcc3f6621efdd1'),
 'ItemData.lua': ('a102fea143c4e9f953c67b07c030c7212379538beb159d360020be4c31b3b115',
                  '438f5470cc1fc1f09661935bf210135ad0f22aeaf536d9a5c18f17646c062d42'),
 'NpcCareerData.lua': ('e9c09c0f81052c289540dbbe4e878039e99738640d7a67a41fdc58e6275bf6eb',
                       'ca21195182334583d332d7727d73e814d31feb0ffd74b88025e56011d75dff09'),
 'NpcData.lua': ('6ecf5448206e9a2d1b46fbff81d9e0432bd135151bb326ec7975378f37e0c1b0',
                 'e13fa43e7ede815889236f110025255076528458f035abaa298ee40d35cf5e4d'),
 'NpcTalkData.lua': ('761ee4f272fd65138cd4bb51db71b443c1cb961ff6314a483d384d2d66041e26',
                     '2ea284d5d2ccca42fad4b684c55c0e9a8dc706f14bcbcc4d9032399f9b5fc0a5'),
 'Skill.lua': ('9face105318af7fa2b247b5c55fd391d06dede6ab768ba8a17e9ec3e4ab879da',
               '92e7b3d297a9c4fc1121d2b7979cc04ace5776e6f3698b8e89b5ffca3517e003'),
 'SkillData.lua': ('1304e566b6f33e23d4cdc569e35b350a4c5eaa438c8942f126f4f96af000cb3c',
                   '962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228'),
 'SkillMotionData.lua': ('9682ce2874f540bafebe50d37efcc7589b2dab018c8891558782f05e80ab7dcd',
                         '54fb4daf742c8379fc9778d00f2a4329355250277a6d9c607236c68b419d4c0b'),
 'StageMapData.lua': ('ba17aafad21c0529bffe1dd472268c7f37463234602c95afbd87e2d9e6a21631',
                      'fcd4b5704ff46341cb0307c5e1d5be753c69fd9a7c6b6361af26c3cabeb49a06'),
 'UIAISetting.lua': ('df5d99da562c5df7843c8b2ef71bfb4540d54d312de001ad2ad1abc4ded871fe',
                     'c33e49820528c676c87b6648bfe4e23c850fefeb156916bf1212ccfc80966b46'),
 'UIAlchemy.lua': ('e2db909788bffc82c27968cd8dd5007db2a0b52d241bac5efcace86e66003885',
                   'ad2cf5da4225263c6fad00befe0a015c0758acbc879dbc7bc0386eb2da0836e0'),
 'UIAlchemyModule.lua': ('1f98191957abe9221a0a88deaaf2519169d99767034f84b30aa5f32638b14c4e',
                         '5b82f11da409452a3a3ab20aeea7cb6e34e054b5f458bd8944239e1d0d3e7b56'),
 'UIBattle.lua': ('74b9b6a82e08395265948ec5c2f530e072dc42fb42fe40bef6fe955a5e23355c',
                  '17710d928f153941f04a9648981aefa9be6c4dd352926b49cf7c3dd7497d51c2'),
 'UIBattleTarget.lua': ('00c7a304d8a86af58564e1136fd36e1e6b7a820c2703bc2b9686c9497a65585b',
                        '9d788c10262f985e8fab3e48b8438b2114bb2f8166e1d2f0987ad9e399340034')}


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
