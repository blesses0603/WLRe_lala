using System.Buffers.Binary;
using System.Security.Cryptography;

namespace Lala.Core.Resources;

// Canonical cache encoding only: RGBA8, filter None, one IDAT, stored DEFLATE blocks.
// Reads compare to a freshly encoded independent candidate; no untrusted PNG decompression.
internal static class SpritePng
{
    internal const int MaximumBytes = 4 * 1024 * 1024;
    internal static byte[] Encode(SpritePixelCandidate candidate, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        int width = candidate.Width, height = candidate.Height;
        BoundedSpritePixels.Check(width is > 0 and <= 512 && height is > 0 and <= 512, "PNG dimensions exceed bounds");
        byte[] pixels = candidate.CopyPixels();
        BoundedSpritePixels.Check(pixels.Length == width * height * 4 && Hash(pixels) == candidate.PixelSha256, "PNG candidate pixel mismatch");
        byte[] scanlines = new byte[(width * 4 + 1) * height];
        for (int y = 0; y < height; y++)
        {
            token.ThrowIfCancellationRequested();
            pixels.AsSpan(y * width * 4, width * 4).CopyTo(scanlines.AsSpan(y * (width * 4 + 1) + 1));
        }
        using var zlib = new MemoryStream();
        zlib.Write([0x78, 0x01]); // RFC1950: DEFLATE, 32KiB window, no dictionary.
        uint a = 1, b = 0;
        for (int offset = 0; offset < scanlines.Length;)
        {
            token.ThrowIfCancellationRequested();
            int length = Math.Min(65535, scanlines.Length - offset);
            zlib.WriteByte((byte)(offset + length == scanlines.Length ? 1 : 0));
            zlib.WriteByte((byte)length); zlib.WriteByte((byte)(length >> 8));
            zlib.WriteByte((byte)~length); zlib.WriteByte((byte)(~length >> 8));
            var block = scanlines.AsSpan(offset, length); zlib.Write(block);
            foreach (byte value in block) { a = (a + value) % 65521; b = (b + a) % 65521; }
            offset += length;
        }
        Write32(zlib, (b << 16) | a);
        using var png = new MemoryStream();
        png.Write([137, 80, 78, 71, 13, 10, 26, 10]);
        byte[] header = new byte[13];
        BinaryPrimitives.WriteUInt32BigEndian(header, (uint)width);
        BinaryPrimitives.WriteUInt32BigEndian(header.AsSpan(4), (uint)height);
        header[8] = 8; header[9] = 6;
        Chunk(png, "IHDR"u8, header); Chunk(png, "IDAT"u8, zlib.ToArray()); Chunk(png, "IEND"u8, []);
        token.ThrowIfCancellationRequested(); return png.ToArray();
    }
    internal static string Hash(ReadOnlySpan<byte> bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static void Chunk(Stream stream, ReadOnlySpan<byte> type, ReadOnlySpan<byte> data)
    {
        Write32(stream, (uint)data.Length); stream.Write(type); stream.Write(data);
        uint crc = uint.MaxValue;
        foreach (byte value in type) crc = Update(crc, value);
        foreach (byte value in data) crc = Update(crc, value);
        Write32(stream, ~crc);
    }
    private static uint Update(uint crc, byte value)
    {
        crc ^= value;
        for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0 : 0xedb88320u);
        return crc;
    }
    private static void Write32(Stream stream, uint value)
    {
        Span<byte> bytes = stackalloc byte[4]; BinaryPrimitives.WriteUInt32BigEndian(bytes, value); stream.Write(bytes);
    }
}
