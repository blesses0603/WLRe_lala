"""Verify published Windows PE icon resources against the exact repository ICO.

No Windows execution or third-party PE parser required. This checks the apphost,
not merely an embedded managed resource or the project configuration.
"""
import argparse
import struct
from pathlib import Path


def verify(executable, icon):
    data = Path(executable).read_bytes()
    ico = Path(icon).read_bytes()
    def unpack(fmt, offset, source=data):
        return struct.unpack_from(fmt, source, offset)
    assert data[:2] == b'MZ', 'Not a Windows executable'
    pe, = unpack('<I', 0x3c)
    assert data[pe:pe + 4] == b'PE\0\0', 'Missing PE header'
    sections, = unpack('<H', pe + 6)
    optional_size, = unpack('<H', pe + 20)
    optional = pe + 24
    magic, = unpack('<H', optional)
    assert magic in (0x10b, 0x20b), 'Unsupported PE format'
    directory = optional + (112 if magic == 0x20b else 96)
    resource_rva, resource_size = unpack('<II', directory + 16)
    assert resource_rva and resource_size, 'No native resources'
    section_rows = [unpack('<IIII', optional + optional_size + i * 40 + 8) for i in range(sections)]
    def offset(rva):
        for virtual_size, address, raw_size, raw in section_rows:
            if address <= rva < address + max(virtual_size, raw_size):
                return raw + rva - address
        raise AssertionError('RVA outside sections')
    base = offset(resource_rva)
    resources = {}
    def walk(relative, path=()):
        assert len(path) < 4, 'Invalid resource tree'
        named, numbered = unpack('<HH', base + relative + 12)
        for i in range(named + numbered):
            name, child = unpack('<II', base + relative + 16 + i * 8)
            if name & 0x80000000:
                continue
            key = (*path, name)
            if child & 0x80000000:
                walk(child & 0x7fffffff, key)
            else:
                rva, size, _, _ = unpack('<IIII', base + child)
                start = offset(rva)
                resources[key] = data[start:start + size]
    walk(0)
    reserved, kind, count = unpack('<HHH', 0, ico)
    assert (reserved, kind) == (0, 1) and count, 'Invalid source ICO'
    frames = []
    for i in range(count):
        entry = ico[6 + i * 16:22 + i * 16]
        size, start = struct.unpack_from('<II', entry, 8)
        frames.append((entry[:12], ico[start:start + size]))
    groups = [(key, value) for key, value in resources.items() if key[0] == 14]
    assert groups, 'Missing native RT_GROUP_ICON'
    for key, group in groups:
        if unpack('<HHH', 0, group) != (0, 1, count):
            continue
        for i, (header, frame) in enumerate(frames):
            entry = group[6 + i * 14:20 + i * 14]
            assert entry[:12] == header, 'Native icon frame metadata differs'
            image_id, = unpack('<H', 12, entry)
            assert resources.get((3, image_id, key[-1])) == frame, 'Native RT_ICON differs from app.ico'
        return count
    raise AssertionError('No native icon group matches source ICO')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--icon', type=Path, default=Path(__file__).resolve().parents[1] / 'wlre/resources/assets/app.ico')
    args = parser.parse_args()
    count = verify(args.executable, args.icon)
    print(f'Windows apphost native icon: {count} exact ICO frames verified.')
