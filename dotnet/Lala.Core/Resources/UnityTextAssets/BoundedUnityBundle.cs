using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

internal sealed class UnityExtractionBudget
{
    internal long ExpandedBytes;
    internal long MetadataBytes;
    internal int Files;
    internal int Objects;
    internal int ContainerEntries;
    internal long ContainerIdentityBytes;
}

internal static class BoundedUnityBundle
{
    internal const int MaximumBundleBytes = 64 * 1024 * 1024;
    internal const int MaximumBlockInfoBytes = 4 * 1024 * 1024;
    internal const long MaximumTotalBytes = 128L * 1024 * 1024;
    internal sealed record Entry(string Name, ReadOnlyMemory<byte> Bytes);

    internal static List<Entry> Read(ReadOnlyMemory<byte> input, UnityExtractionBudget budget, CancellationToken token)
    {
        var r = new UnityReadCursor(input, true);
        Require(input.Length is > 0 and <= MaximumBundleBytes && r.NullString(7) == "UnityFS", "Unsupported UnityFS signature or size");
        uint version = r.U32(); Require(version is 6 or 7 or 8, "Unsupported UnityFS version");
        r.NullString(127); string engine = r.NullString(127);
        Require(r.I64() == input.Length, "UnityFS declared length mismatch");
        uint packed = r.U32(), unpacked = r.U32(), flags = r.U32();
        Require(packed is > 0 and <= MaximumBlockInfoBytes && unpacked is > 0 and <= MaximumBlockInfoBytes &&
            (flags & ~0x2ffU) == 0 && (flags & 0x40) != 0 && (flags & 0x100) == 0, "Unsupported UnityFS block flags or sizes");
        // 0x200 is padding only in reviewed modern engine builds. Earlier Unity CN uses
        // it for encryption. Do not reinterpret that flag on unreviewed engine versions.
        Require((flags & 0x200) == 0 || engine == "2021.3.45f2", "Unreviewed UnityFS padding/encryption flag");
        if (version >= 7) r.Align(16);
        bool atEnd = (flags & 0x80) != 0;
        Require(packed <= r.Remaining, "Truncated block info");
        int infoStart = atEnd ? input.Length - (int)packed : r.Position;
        byte[] info = Expand(input.Slice(infoStart, (int)packed), (int)unpacked, flags & 0x3f, token);
        if (!atEnd) r.Take((int)packed);
        if ((flags & 0x200) != 0) r.Align(16);
        int dataEnd = atEnd ? infoStart : input.Length;
        var ir = new UnityReadCursor(info, true); ir.Take(16);
        int blockCount = ir.Count(4096, 10); Require(blockCount > 0, "Missing UnityFS blocks");
        var blocks = new List<(int Plain, int Packed, uint Compression)>(blockCount);
        long plainTotal = 0, packedTotal = 0;
        for (int i = 0; i < blockCount; i++)
        {
            token.ThrowIfCancellationRequested();
            uint plain = ir.U32(), size = ir.U32(), blockFlags = ir.U16();
            Require(plain is > 0 and <= MaximumBundleBytes && size is > 0 and <= MaximumBundleBytes && (blockFlags & ~0x3fU) == 0, "Unsupported UnityFS data block");
            CheckCompression(blockFlags & 0x3f);
            plainTotal += plain; packedTotal += size;
            Require(plainTotal <= MaximumBundleBytes && budget.ExpandedBytes + plainTotal <= MaximumTotalBytes, "UnityFS expansion limit");
            blocks.Add(((int)plain, (int)size, blockFlags & 0x3f));
        }
        Require(packedTotal == dataEnd - r.Position, "UnityFS data span mismatch");
        budget.ExpandedBytes += plainTotal;
        int fileCount = ir.Count(128, 21); budget.Files += fileCount;
        Require(fileCount > 0 && budget.Files <= 128, "UnityFS directory limit");
        var directory = new List<(string Name, int Offset, int Size)>(fileCount);
        var names = new HashSet<string>(StringComparer.Ordinal);
        long priorEnd = 0;
        for (int i = 0; i < fileCount; i++)
        {
            token.ThrowIfCancellationRequested();
            long offset = ir.I64(), size = ir.I64(); uint fileFlags = ir.U32(); string name = ir.NullString(255);
            Require(offset >= priorEnd && size > 0 && offset <= plainTotal && size <= plainTotal - offset && fileFlags == 4,
                "Unsupported UnityFS directory span or entry flags");
            Require(name.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_' or '.') && name is not "." and not ".." && names.Add(name),
                "Invalid or duplicate UnityFS file identity");
            directory.Add((name, (int)offset, (int)size)); priorEnd = offset + size;
        }
        ir.End();
        byte[] expanded = new byte[(int)plainTotal]; int write = 0;
        foreach (var block in blocks)
        {
            token.ThrowIfCancellationRequested();
            ExpandInto(r.Take(block.Packed).Span, expanded.AsSpan(write, block.Plain), block.Compression, token);
            write += block.Plain;
        }
        return directory.Select(x => new Entry(x.Name, expanded.AsMemory(x.Offset, x.Size))).ToList();
    }

    private static void CheckCompression(uint compression) => Require(compression is 0 or 2 or 3, "Unsupported compression; LZMA/encryption disabled");
    private static byte[] Expand(ReadOnlyMemory<byte> input, int length, uint compression, CancellationToken token)
    {
        CheckCompression(compression); var output = new byte[length]; ExpandInto(input.Span, output, compression, token); return output;
    }
    // LZ4 and LZ4HC use identical raw block decoding. No upstream decompressor, dictionary,
    // expanding buffer, recursive call or allocation based on an extension byte is used.
    internal static void ExpandInto(ReadOnlySpan<byte> input, Span<byte> output, uint compression, CancellationToken token)
    {
        CheckCompression(compression); token.ThrowIfCancellationRequested();
        if (compression == 0) { Require(input.Length == output.Length, "Uncompressed block length mismatch"); input.CopyTo(output); token.ThrowIfCancellationRequested(); return; }
        Require(input.Length > 0 && output.Length > 0, "Empty LZ4 block");
        int read = 0, written = 0, lastMatchStart = -1;
        while (read < input.Length)
        {
            token.ThrowIfCancellationRequested();
            byte control = input[read++]; int literal = Length(input, ref read, control >> 4, output.Length - written);
            Require(literal <= input.Length - read && literal <= output.Length - written, "LZ4 literal exceeds span");
            input.Slice(read, literal).CopyTo(output.Slice(written)); read += literal; written += literal;
            if (read == input.Length)
            {
                Require(written == output.Length, "Short LZ4 output");
                Require(lastMatchStart < 0 || (literal >= 5 && lastMatchStart <= output.Length - 12), "Noncanonical LZ4 final sequence");
                token.ThrowIfCancellationRequested(); return;
            }
            Require(input.Length - read >= 2, "Truncated LZ4 offset");
            int distance = input[read] | input[read + 1] << 8; read += 2;
            Require(distance > 0 && distance <= written, "Invalid LZ4 back reference");
            int match = Length(input, ref read, control & 15, output.Length - written) + 4;
            Require(match <= output.Length - written, "LZ4 match exceeds output");
            lastMatchStart = written;
            for (int i = 0; i < match; i++)
            { if ((i & 4095) == 0) token.ThrowIfCancellationRequested(); output[written] = output[written - distance]; written++; }
        }
        throw new UnityTextAssetException("LZ4 block must end with a literal sequence");
    }
    private static int Length(ReadOnlySpan<byte> input, ref int offset, int length, int maximum)
    {
        if (length == 15)
        {
            byte next;
            do
            {
                Require(offset < input.Length, "Truncated LZ4 length"); next = input[offset++];
                Require(length <= maximum - next, "LZ4 length exceeds output"); length += next;
            } while (next == 255);
        }
        Require(length <= maximum, "LZ4 length exceeds output"); return length;
    }
}
