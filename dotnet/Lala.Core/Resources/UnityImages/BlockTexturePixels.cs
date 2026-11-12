using System.Buffers.Binary;

namespace Lala.Core.Resources;

// BC1/DXT1 and BC3/DXT5 base levels only. No source admission or atlas support.
internal static class BlockTexturePixels
{
    internal static int PayloadLength(int width, int height, int format)
    {
        BoundedSpritePixels.Check(width is > 0 and <= 2048 && height is > 0 and <= 2048, "Invalid texture dimensions");
        return format switch
        {
            3 => width * height * 3,
            4 or 5 or 14 => width * height * 4,
            10 or 12 => ((width + 3) / 4) * ((height + 3) / 4) * (format == 10 ? 8 : 16),
            _ => throw new SpritePixelException("Unreviewed TextureFormat")
        };
    }

    internal static byte[] Decode(ReadOnlySpan<byte> source, int width, int height, int format, CancellationToken token)
    {
        BoundedSpritePixels.Check(format is 10 or 12 && source.Length == PayloadLength(width, height, format), "Invalid block texture payload");
        token.ThrowIfCancellationRequested();
        var result = new byte[width * height * 4];
        Span<byte> colors = stackalloc byte[16];
        Span<byte> alpha = stackalloc byte[8];
        int offset = 0;
        for (int by = 0; by < height; by += 4)
        {
            token.ThrowIfCancellationRequested();
            for (int bx = 0; bx < width; bx += 4)
            {
                ulong alphaIndices = 0;
                if (format == 12)
                {
                    alpha[0] = source[offset]; alpha[1] = source[offset + 1];
                    int count = alpha[0] > alpha[1] ? 7 : 5;
                    for (int i = 1; i < count; i++) alpha[i + 1] = (byte)(((count - i) * alpha[0] + i * alpha[1]) / count);
                    if (count == 5) { alpha[6] = 0; alpha[7] = 255; }
                    for (int i = 0; i < 6; i++) alphaIndices |= (ulong)source[offset + 2 + i] << (8 * i);
                    offset += 8;
                }
                ushort c0 = BinaryPrimitives.ReadUInt16LittleEndian(source[offset..]);
                ushort c1 = BinaryPrimitives.ReadUInt16LittleEndian(source[(offset + 2)..]);
                Color(c0, colors); Color(c1, colors[4..]);
                bool four = format == 12 || c0 > c1;
                for (int c = 0; c < 3; c++)
                {
                    colors[8 + c] = (byte)(four ? (2 * colors[c] + colors[4 + c]) / 3 : (colors[c] + colors[4 + c]) / 2);
                    colors[12 + c] = four ? (byte)((colors[c] + 2 * colors[4 + c]) / 3) : (byte)0;
                }
                colors[11] = 255; colors[15] = four ? (byte)255 : (byte)0;
                uint indices = BinaryPrimitives.ReadUInt32LittleEndian(source[(offset + 4)..]); offset += 8;
                for (int i = 0; i < 16; i++)
                {
                    int x = bx + i % 4, y = by + i / 4;
                    if (x >= width || y >= height) continue;
                    int target = (y * width + x) * 4, color = (int)((indices >> (2 * i)) & 3) * 4;
                    colors.Slice(color, 4).CopyTo(result.AsSpan(target, 4));
                    if (format == 12) result[target + 3] = alpha[(int)((alphaIndices >> (3 * i)) & 7)];
                }
            }
        }
        token.ThrowIfCancellationRequested(); return result;
    }

    private static void Color(ushort value, Span<byte> output)
    {
        int r = value >> 11, g = (value >> 5) & 63, b = value & 31;
        output[0] = (byte)((r << 3) | (r >> 2)); output[1] = (byte)((g << 2) | (g >> 4));
        output[2] = (byte)((b << 3) | (b >> 2)); output[3] = 255;
    }
}
