"""Owned canonical PNG vectors; independently decoded by Pillow and Python zlib."""
import hashlib, io, json, struct, zlib
from pathlib import Path
import PIL
from PIL import Image

rows = []
for width, height in [(1, 1), (2, 3), (128, 128), (512, 512)]:
    source = bytes((i * 37 + 11) % 256 for i in range(width * height * 4))
    pixels = b''.join(source[y * width * 4:(y + 1) * width * 4] for y in reversed(range(height)))
    scanlines = b''.join(b'\0' + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
    compressed = bytearray(b'\x78\x01')
    for start in range(0, len(scanlines), 65535):
        block = scanlines[start:start + 65535]
        compressed += struct.pack('<BHH', int(start + len(block) == len(scanlines)), len(block), len(block) ^ 65535) + block
    compressed += struct.pack('>I', zlib.adler32(scanlines))
    assert zlib.decompress(compressed) == scanlines
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')
    with Image.open(io.BytesIO(png)) as image:
        assert image.format == 'PNG' and image.mode == 'RGBA' and image.size == (width, height)
        assert image.tobytes() == pixels
    rows.append(dict(width=width, height=height, bytes=len(png), sha256=hashlib.sha256(png).hexdigest()))
Path(__file__).with_name('png_vectors.json').write_text(json.dumps(dict(pillow=PIL.__version__, zlib=zlib.ZLIB_VERSION, vectors=rows), indent=2) + '\n')
