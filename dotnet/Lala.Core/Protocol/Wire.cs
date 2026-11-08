using System.Buffers.Binary;
using System.Text;

namespace Lala.Core.Protocol;

public sealed class ProtocolException(string message, Exception? inner = null) : Exception(message, inner);

/// <summary>Strict little-endian fields matching wlre/network/wire.py. Owns its input.</summary>
public sealed class PacketReader(ReadOnlySpan<byte> input)
{
    private readonly byte[] data = input.ToArray();
    public int Offset { get; private set; }
    public int Remaining => data.Length - Offset;
    public ReadOnlySpan<byte> Take(int count)
    {
        if (count < 0 || count > Remaining)
            throw new ProtocolException($"offset {Offset}: need {count}, have {Remaining}");
        var result = data.AsSpan(Offset, count);
        Offset += count;
        return result;
    }
    public byte U8() => Take(1)[0];
    public ushort U16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
    public uint U32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
    public int I32() => BinaryPrimitives.ReadInt32LittleEndian(Take(4));
    public long I64() => BinaryPrimitives.ReadInt64LittleEndian(Take(8));
    public string Unicode8()
    {
        var size = U8();
        if (size % 2 != 0) throw new ProtocolException("odd UTF-16LE byte length");
        try { return new UnicodeEncoding(false, false, true).GetString(Take(size)).TrimEnd('\0'); }
        catch (DecoderFallbackException ex) { throw new ProtocolException("invalid UTF-16LE string", ex); }
    }
    public void End()
    {
        if (Remaining != 0) throw new ProtocolException($"unexpected trailing bytes: {Remaining}");
    }
}

/// <summary>Values are range checked before append, never silently truncated.</summary>
public sealed class PacketWriter
{
    private readonly List<byte> data = [];
    private PacketWriter Unsigned(long value, long max, int bytes)
    {
        if (value < 0 || value > max) throw new ProtocolException($"invalid unsigned {bytes * 8}-bit value");
        for (int i = 0; i < bytes; i++) data.Add((byte)((value >> (i * 8)) & 255));
        return this;
    }
    public PacketWriter U8(long value) => Unsigned(value, byte.MaxValue, 1);
    public PacketWriter U16(long value) => Unsigned(value, ushort.MaxValue, 2);
    public PacketWriter U32(long value) => Unsigned(value, uint.MaxValue, 4);
    public PacketWriter Raw(ReadOnlySpan<byte> bytes) { foreach (byte b in bytes) data.Add(b); return this; }
    public byte[] Build() => data.ToArray();
}

public sealed class Packet
{
    private readonly byte[] payload;
    public byte Main { get; }
    public byte Sub { get; }
    public ReadOnlyMemory<byte> Payload => payload;
    public Packet(int main, int sub, ReadOnlySpan<byte> payload = default)
    {
        if (main is < 0 or > 255 || sub is < 0 or > 255) throw new ProtocolException("main/sub must be bytes");
        Main = (byte)main; Sub = (byte)sub; this.payload = payload.ToArray();
    }
    // Only an exclusive, internally owned credential packet lease may call this.
    internal void ClearSensitivePayload() => System.Security.Cryptography.CryptographicOperations.ZeroMemory(payload);
    public byte[] Body() => new PacketWriter().U8(Main).U8(Sub).Raw(payload).Build();
    public static Packet FromBody(ReadOnlySpan<byte> body)
    {
        if (body.Length < 2) throw new ProtocolException("packet body has no main/sub header");
        return new Packet(body[0], body[1], body[2..]);
    }
}

/// <summary>Candidate wire encoding only. This is not authorization to send game commands.</summary>
public static class WireCodec
{
    public static byte[] Encode(Packet packet, int xorKey = 0xAD)
    {
        ValidateKey(xorKey);
        if (packet.Payload.Length > ushort.MaxValue - 2) throw new ProtocolException("body exceeds uint16 length");
        var body = packet.Body();
        var result = new PacketWriter().Raw([0xC4, 0xC6]).U16(body.Length).Raw(body).Build();
        for (int i = 0; i < result.Length; i++) result[i] ^= (byte)xorKey;
        return result;
    }
    internal static void ValidateKey(int key)
    {
        if (key is < 0 or > 255) throw new ProtocolException("XOR key must be a byte");
    }
}

/// <summary>Incremental framing, not TCP sequence reassembly. On error discard this decoder.</summary>
public sealed class FrameDecoder
{
    private readonly byte key;
    private readonly List<byte> buffer = [];
    public int BufferedBytes => buffer.Count;
    public FrameDecoder(int xorKey = 0xAD) { WireCodec.ValidateKey(xorKey); key = (byte)xorKey; }
    public IReadOnlyList<Packet> Feed(ReadOnlySpan<byte> input)
    {
        foreach (byte b in input) buffer.Add((byte)(b ^ key));
        List<Packet> packets = [];
        int consumed = 0;
        while (buffer.Count - consumed >= 4)
        {
            if (buffer[consumed] != 0xC4 || buffer[consumed + 1] != 0xC6)
                throw new ProtocolException("bad frame magic; incomplete capture or different wire codec");
            int size = buffer[consumed + 2] | (buffer[consumed + 3] << 8);
            if (size < 2) throw new ProtocolException("frame shorter than main/sub header");
            if (buffer.Count - consumed < size + 4) break;
            packets.Add(Packet.FromBody(buffer.GetRange(consumed + 4, size).ToArray()));
            consumed += size + 4;
        }
        if (consumed > 0) buffer.RemoveRange(0, consumed);
        return packets;
    }
    public void Finish()
    {
        if (buffer.Count > 0) throw new ProtocolException($"incomplete final frame: {buffer.Count} bytes");
    }
}
