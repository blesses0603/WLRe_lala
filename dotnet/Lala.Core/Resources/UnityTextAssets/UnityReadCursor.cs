using System.Buffers.Binary;
using System.Text;

namespace Lala.Core.Resources;

internal sealed class UnityTextAssetException(string message) : Exception(message);

// No capacity or byte-array allocation depends on a field until its local AND aggregate
// bound has been checked. All slices retain the owned verified input, never an external path.
internal sealed class UnityReadCursor(ReadOnlyMemory<byte> bytes, bool bigEndian = false)
{
    internal static readonly UTF8Encoding Utf8 = new(false, true);
    internal ReadOnlyMemory<byte> Bytes { get; } = bytes;
    internal bool BigEndian { get; set; } = bigEndian;
    internal int Position { get; private set; }
    internal int Remaining => Bytes.Length - Position;
    internal ReadOnlyMemory<byte> Take(int count)
    {
        Require(count >= 0 && count <= Remaining, "Truncated Unity field or span");
        var result = Bytes.Slice(Position, count); Position += count; return result;
    }
    internal void Align(int n = 4) => Take((n - Position % n) % n);
    internal byte U8() => Take(1).Span[0];
    internal ushort U16() { var s = Take(2).Span; return BigEndian ? BinaryPrimitives.ReadUInt16BigEndian(s) : BinaryPrimitives.ReadUInt16LittleEndian(s); }
    internal uint U32() { var s = Take(4).Span; return BigEndian ? BinaryPrimitives.ReadUInt32BigEndian(s) : BinaryPrimitives.ReadUInt32LittleEndian(s); }
    internal int I32() => unchecked((int)U32());
    internal long I64() { var s = Take(8).Span; return BigEndian ? BinaryPrimitives.ReadInt64BigEndian(s) : BinaryPrimitives.ReadInt64LittleEndian(s); }
    internal int Count(int maximum, int minimumBytes = 0)
    {
        int count = I32(); Require(count >= 0 && count <= maximum && (long)count * minimumBytes <= Remaining, "Unity count exceeds bound or remaining span"); return count;
    }
    internal string NullString(int maximum = 1024, bool allowEmpty = false)
    {
        int n = Bytes.Span.Slice(Position, Math.Min(Remaining, maximum + 1)).IndexOf((byte)0);
        Require(n >= 0 && n <= maximum && (allowEmpty || n > 0), "Unterminated, empty or oversized Unity string");
        string result = Decode(Take(n).Span); Take(1); return result;
    }
    internal string String(int maximum = 1024, bool allowEmpty = true)
    {
        int n = Count(maximum, 1); Require(allowEmpty || n > 0, "Empty Unity string");
        string result = Decode(Take(n).Span); Require(!result.Contains('\0'), "NUL in Unity identity"); Align(); return result;
    }
    internal static string Decode(ReadOnlySpan<byte> bytes)
    {
        try { return Utf8.GetString(bytes); }
        catch (DecoderFallbackException) { throw new UnityTextAssetException("Invalid UTF-8 identity"); }
    }
    internal void End() => Require(Remaining == 0, "Unexpected trailing Unity data");
    internal static void Require(bool condition, string message)
    { if (!condition) throw new UnityTextAssetException(message); }
}
