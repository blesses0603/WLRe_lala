using System.Buffers.Binary;
using System.Globalization;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

// wire.Reader semantics used by the expedition sources, including every read/end checkpoint.
// Unlike CatalogReader this does not trim strings, cap them at 8192 bytes, or guess fields.
internal ref struct ExpeditionWireReader(ReadOnlySpan<byte> raw, CancellationToken token)
{
    private readonly ReadOnlySpan<byte> raw = raw;
    private readonly CancellationToken token = token;
    public int Position { get; private set; }
    private int Remaining => raw.Length - Position;
    public ReadOnlySpan<byte> Take(int size)
    {
        ParserDiagnostics.ReadCheckpoint(Position, size, Remaining);
        token.ThrowIfCancellationRequested();
        if (size < 0 || size > Remaining)
            throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                $"offset {Position}: need {size}, have {Remaining}"));
        var result = raw.Slice(Position, size);
        Position += size;
        return result;
    }
    public byte U8() => Take(1)[0];
    public ushort U16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
    public uint U32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
    public int I32() => BinaryPrimitives.ReadInt32LittleEndian(Take(4));
    public void End()
    {
        ParserDiagnostics.ReadCheckpoint(Position, 0, Remaining);
        token.ThrowIfCancellationRequested();
        if (Remaining != 0)
            throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                $"unexpected trailing bytes: {Remaining}"));
    }
}
