"""Offline, fail-closed decoder for independently reviewed official Lua files.

No client code is executed. No keys or Lua content are shipped: content codec
parameters come from the fingerprint-checked public client metadata supplied
by the operator. See docs/OFFICIAL_CLIENT_LUA_DECODING.md for evidence.
Shares the reviewed pycryptodome codec used by the runtime data importer.
"""
from pathlib import Path
from wlre.services.world.official_lua_codec import (
    METADATA_SHA256, MAX_LUA_BYTES, KNOWN_FILES, _digest, _parameters, _cbc_decode)


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
