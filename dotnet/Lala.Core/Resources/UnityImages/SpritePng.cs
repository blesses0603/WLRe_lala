using System.Buffers.Binary;
using System.Security.Cryptography;
using System.IO.Compression;

namespace Lala.Core.Resources;

// Cache encoding: RGBA8, filter None, one IDAT; sprites use stored DEFLATE, portraits zlib.
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
        return EncodeOwnedRgba(width, height, pixels, false, token);
    }
    // Separate portrait entry; no invented Sprite context or relaxed Sprite dimensions.
    internal static byte[] EncodePortrait(byte[] pixels, CancellationToken token = default)
    {
        BoundedSpritePixels.Check(pixels.Length == 256 * 256 * 4, "Portrait PNG geometry mismatch");
        return EncodeOwnedRgba(256, 256, pixels.ToArray(), true, token);
    }
    // Emoji uses its own candidate identity and compressed variable-size PNG budget.
    internal static byte[] EncodeEmoji(AtlasPixelCandidate candidate, CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();int width=candidate.Width,height=candidate.Height;
        BoundedSpritePixels.Check(width is >0 and <=512 && height is >0 and <=512,"Emoji PNG geometry exceeds bound");
        byte[] pixels=candidate.CopyPixels();
        BoundedSpritePixels.Check(pixels.Length==width*height*4 && Hash(pixels)==candidate.PixelSha256,"Emoji PNG pixel mismatch");
        return EncodeOwnedRgba(width,height,pixels,true,token);
    }
    internal static byte[] EncodeSmallMap(TexturePixelCandidate candidate,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        BoundedSpritePixels.Check(candidate.Layout.Width==1024&&candidate.Layout.Height==1024,"Small map PNG geometry mismatch");
        var pixels=candidate.CopyPixels();BoundedSpritePixels.Check(pixels.Length==1024*1024*4&&Hash(pixels)==candidate.PixelSha256,"Small map PNG pixel mismatch");
        var png=EncodeOwnedRgba(1024,1024,pixels,true,token);
        BoundedSpritePixels.Check(png.Length<=MaximumBytes,"Small map PNG exceeds bound");return png;
    }
    private static byte[] EncodeOwnedRgba(int width, int height, byte[] pixels, bool compressed, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        byte[] scanlines = new byte[(width * 4 + 1) * height];
        for (int y = 0; y < height; y++)
        {
            token.ThrowIfCancellationRequested();
            pixels.AsSpan(y * width * 4, width * 4).CopyTo(scanlines.AsSpan(y * (width * 4 + 1) + 1));
        }
        using var zlib = new MemoryStream();
        if (compressed)
        {
            using var deflate = new ZLibStream(zlib, CompressionLevel.SmallestSize, leaveOpen: true);
            deflate.Write(scanlines);
        }
        else
        {
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
        }
        using var png = new MemoryStream();
        png.Write([137, 80, 78, 71, 13, 10, 26, 10]);
        byte[] header = new byte[13];
        BinaryPrimitives.WriteUInt32BigEndian(header, (uint)width);
        BinaryPrimitives.WriteUInt32BigEndian(header.AsSpan(4), (uint)height);
        header[8] = 8; header[9] = 6;
        Chunk(png, "IHDR"u8, header); Chunk(png, "IDAT"u8, zlib.ToArray()); Chunk(png, "IEND"u8, []);
        token.ThrowIfCancellationRequested(); return png.ToArray();
    }
    // Only private PNG bytes already independently matched by PortraitPngStore reach this
    // path in production. Still bound structure and decompressed bytes before rendering.
    internal static byte[] DecodePortrait(ReadOnlySpan<byte> png, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        BoundedSpritePixels.Check(png.Length is >=57 and <=524288 && png[..8].SequenceEqual(new byte[]{137,80,78,71,13,10,26,10}), "Invalid owned portrait PNG");
        int offset=8; byte[]? compressed=null;
        foreach (string expected in new[]{"IHDR","IDAT","IEND"})
        {
            BoundedSpritePixels.Check(offset<=png.Length-12,"Truncated owned portrait PNG");
            uint length=BinaryPrimitives.ReadUInt32BigEndian(png[offset..]);
            BoundedSpritePixels.Check(length<=(uint)(png.Length-offset-12),"Portrait PNG chunk exceeds bound");
            int size=(int)length; var kind=png.Slice(offset+4,4); var data=png.Slice(offset+8,size);
            BoundedSpritePixels.Check(System.Text.Encoding.ASCII.GetString(kind)==expected,"Unexpected portrait PNG chunk");
            uint crc=uint.MaxValue; foreach(byte b in kind)crc=Update(crc,b); foreach(byte b in data)crc=Update(crc,b);
            BoundedSpritePixels.Check(~crc==BinaryPrimitives.ReadUInt32BigEndian(png[(offset+8+size)..]),"Portrait PNG CRC mismatch");
            if(expected=="IHDR") BoundedSpritePixels.Check(size==13 && BinaryPrimitives.ReadUInt32BigEndian(data)==256 &&
                BinaryPrimitives.ReadUInt32BigEndian(data[4..])==256 && data[8..].SequenceEqual(new byte[]{8,6,0,0,0}),"Portrait PNG geometry mismatch");
            else if(expected=="IDAT") compressed=data.ToArray();
            else BoundedSpritePixels.Check(size==0,"Invalid portrait PNG end");
            offset+=size+12;
        }
        BoundedSpritePixels.Check(offset==png.Length,"Trailing portrait PNG data");
        using var input=new MemoryStream(compressed!,false); using var z=new ZLibStream(input,CompressionMode.Decompress);
        byte[] scanlines=new byte[256*1025]; z.ReadExactly(scanlines);
        BoundedSpritePixels.Check(z.ReadByte()==-1,"Portrait PNG expands beyond geometry");
        var pixels=new byte[256*256*4];
        for(int y=0;y<256;y++) { token.ThrowIfCancellationRequested(); BoundedSpritePixels.Check(scanlines[y*1025]==0,"Unsupported portrait PNG filter"); scanlines.AsSpan(y*1025+1,1024).CopyTo(pixels.AsSpan(y*1024)); }
        return pixels;
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
