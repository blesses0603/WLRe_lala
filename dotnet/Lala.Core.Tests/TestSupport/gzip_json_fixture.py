"""Emit deterministic C# gzip byte literals without adding fixture data to the #US heap."""
import gzip
import io


def gzip_json_bytes(payload: str) -> bytes:
    """Preserve the exact UTF-8 JSON bytes; fix gzip's timestamp, filename and OS header.

    GzipFile (rather than gzip.compress) also fixes the OS byte across Python versions.
    """
    encoded = payload.encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(encoded)
    compressed = buffer.getvalue()
    assert gzip.decompress(compressed) == encoded
    return compressed


def csharp_gzip_json(payload: str) -> str:
    """Return the existing byte-literal expression; compressed bytes stay unchanged."""
    compressed = gzip_json_bytes(payload)
    rows = ["        " + ", ".join(f"0x{value:02x}" for value in compressed[offset:offset + 24]) + ","
            for offset in range(0, len(compressed), 24)]
    return "Lala.Core.Tests.TestSupport.GzipJson.Decode([\n" + "\n".join(rows) + "\n    ])"
