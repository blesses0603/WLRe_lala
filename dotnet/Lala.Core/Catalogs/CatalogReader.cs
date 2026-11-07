using System.Buffers.Binary;
using System.Runtime.CompilerServices;
using System.Text;

[assembly: InternalsVisibleTo("Lala.Core.Tests")]

namespace Lala.Core.Catalogs;

/// <summary>A bounded, offline catalog failed its reviewed source or binary contract.</summary>
public sealed class CatalogDecodeException : FormatException
{
    public CatalogDecodeException(string message) : base(message) { }
}

internal ref struct CatalogReader(ReadOnlySpan<byte> data, CancellationToken cancellationToken)
{
    private static readonly UnicodeEncoding StrictUnicode = new(false, false, true);
    private readonly ReadOnlySpan<byte> data = data;
    private readonly CancellationToken cancellationToken = cancellationToken;
    public int Position { get; private set; }
    public int Remaining => data.Length - Position;

    public ReadOnlySpan<byte> Take(int length)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (length < 0 || length > Remaining)
            throw new CatalogDecodeException("Catalog record truncated");
        ReadOnlySpan<byte> result = data.Slice(Position, length);
        Position += length;
        return result;
    }

    public void Skip(int length) => Take(length);
    public byte UInt8() => Take(1)[0];
    public ushort UInt16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
    public uint UInt32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
    public int Int32() => BinaryPrimitives.ReadInt32LittleEndian(Take(4));

    public string Utf16(bool allowEmpty = false)
    {
        ushort length = UInt16();
        if ((!allowEmpty && length == 0) || length > ItemDataParser.MaxTextBytes || (length & 1) != 0)
            throw new CatalogDecodeException("Invalid ItemData Unicode byte length");
        string text;
        try { text = StrictUnicode.GetString(Take(length)).TrimEnd('\0'); }
        catch (DecoderFallbackException)
        {
            // Do not include catalog content in errors or diagnostics.
            throw new CatalogDecodeException("Invalid ItemData Unicode data");
        }
        if (text.Length == 0 && !allowEmpty)
            throw new CatalogDecodeException("Empty ItemData name");
        return text;
    }
}
