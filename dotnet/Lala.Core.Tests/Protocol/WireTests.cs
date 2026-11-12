using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Protocol;

public class WireTests
{
    [Theory]
    [MemberData(nameof(PythonGoldenVectors.Cases), MemberType = typeof(PythonGoldenVectors))]
    public void MatchesPythonAndEveryFragmentBoundary(string name, Packet packet, int key, string bodyHex, string wireHex)
    {
        _ = name;
        byte[] expected = Convert.FromHexString(wireHex);
        Assert.Equal(bodyHex, Convert.ToHexString(packet.Body()));
        Assert.Equal(expected, WireCodec.Encode(packet, key));
        for (int split = 0; split <= expected.Length; split++)
        {
            var decoder = new FrameDecoder(key);
            var decoded = decoder.Feed(expected.AsSpan(0, split)).Concat(decoder.Feed(expected.AsSpan(split))).ToArray();
            Assert.Single(decoded);
            Assert.Equal(packet.Body(), decoded[0].Body());
            decoder.Finish();
        }
    }
    [Fact]
    public void MultipleFramesAndSingleByteDelivery()
    {
        var source = new[] { new Packet(1, 2), new Packet(3, 4, new byte[] { 255 }), new Packet(5, 6) };
        byte[] bytes = source.SelectMany(p => WireCodec.Encode(p)).ToArray();
        var whole = new FrameDecoder().Feed(bytes);
        Assert.Equal(3, whole.Count);
        var decoder = new FrameDecoder();
        List<Packet> decoded = [];
        foreach (byte b in bytes) decoded.AddRange(decoder.Feed(new byte[] {b}));
        Assert.Equal(source.Select(p => Convert.ToHexString(p.Body())), decoded.Select(p => Convert.ToHexString(p.Body())));
        Assert.Equal(0, decoder.BufferedBytes);
        decoder.Finish();
    }
    [Theory]
    [InlineData("000002000102")]
    [InlineData("C4C60000")]
    [InlineData("C4C6010001")]
    public void RejectsMalformedFrame(string plain) =>
        Assert.Throws<ProtocolException>(() => new FrameDecoder(0).Feed(Convert.FromHexString(plain)));
    [Theory]
    [InlineData("C4")]
    [InlineData("C4C6")]
    [InlineData("C4C602")]
    [InlineData("C4C6020001")]
    public void RejectsIncompleteFinalFrame(string plain)
    {
        var decoder = new FrameDecoder(0);
        Assert.Empty(decoder.Feed(Convert.FromHexString(plain)));
        Assert.Throws<ProtocolException>(decoder.Finish);
    }
    [Fact]
    public void BodyLengthBoundary()
    {
        Assert.Equal(65539, WireCodec.Encode(new Packet(1, 2, new byte[65533])).Length);
        Assert.Throws<ProtocolException>(() => WireCodec.Encode(new Packet(1, 2, new byte[65534])));
        Assert.Throws<ProtocolException>(() => Packet.FromBody(new byte[] {1}));
    }
    [Theory]
    [InlineData(-1)]
    [InlineData(256)]
    public void RejectsInvalidKey(int key)
    {
        Assert.Throws<ProtocolException>(() => new FrameDecoder(key));
        Assert.Throws<ProtocolException>(() => WireCodec.Encode(new Packet(1, 2), key));
    }
    [Fact]
    public void WriterRangesAreStrictAndAtomic()
    {
        var w = new PacketWriter().U8(1);
        Assert.Throws<ProtocolException>(() => w.U8(-1));
        Assert.Throws<ProtocolException>(() => w.U8(256));
        Assert.Throws<ProtocolException>(() => w.U16(65536));
        Assert.Throws<ProtocolException>(() => w.U32(4294967296));
        Assert.Equal(new byte[] {1}, w.Build());
        Assert.Equal("01FFFFFFFFFFFFFF", Convert.ToHexString(w.U8(255).U16(65535).U32(4294967295).Build()));
    }
    [Fact]
    public void ReaderSignedAndUnsignedLittleEndian()
    {
        var r = new PacketReader(Convert.FromHexString("FF341278563412FEFFFFFFFDFFFFFFFFFFFFFF"));
        Assert.Equal(255, r.U8()); Assert.Equal(0x1234, r.U16()); Assert.Equal(0x12345678u, r.U32());
        Assert.Equal(-2, r.I32()); Assert.Equal(-3, r.I64()); r.End();
        Assert.Throws<ProtocolException>(() => r.U8());
    }
    [Fact]
    public void ReaderBoundaryDoesNotAdvanceAndCopiesInput()
    {
        byte[] bytes = [1, 2]; var r = new PacketReader(bytes); bytes[0] = 99;
        Assert.Throws<ProtocolException>(() => r.Take(3));
        Assert.Throws<ProtocolException>(() => r.Take(-1));
        Assert.Equal(0, r.Offset); Assert.Equal(1, r.U8());
        Assert.Throws<ProtocolException>(r.End);
    }
    [Theory]
    [InlineData("06604F7D590000", "你好")]
    [InlineData("04A9030000", "Ω")]
    [InlineData("043DD800DE", "😀")]
    [InlineData("00", "")]
    public void StrictUtf16WithTrailingNuls(string bytes, string expected)
    {
        var r = new PacketReader(Convert.FromHexString(bytes));
        Assert.Equal(expected, r.Unicode8()); r.End();
    }
    [Theory]
    [InlineData("0100")]
    [InlineData("0200D8")]
    [InlineData("0200DC")]
    [InlineData("040000")]
    public void RejectsMalformedUnicode(string bytes) =>
        Assert.Throws<ProtocolException>(() => new PacketReader(Convert.FromHexString(bytes)).Unicode8());
    [Fact]
    public void CommandValidationDoesNotGuessOrTruncate()
    {
        Assert.Throws<ProtocolException>(() => CandidateCommands.Login("用戶", "test", 0, 3, 0));
        Assert.Throws<ProtocolException>(() => CandidateCommands.Login("", "test", 0, 3, 0));
        Assert.Throws<ProtocolException>(() => CandidateCommands.Login(new string('a', 256), "test", 0, 3, 0));
        Assert.Throws<ProtocolException>(() => CandidateCommands.SelectRole(0));
        Assert.Throws<ProtocolException>(() => CandidateCommands.SelectRole(3));
        Assert.Throws<ProtocolException>(() => CandidateCommands.Walk(-1, 0));
        Assert.Throws<ProtocolException>(() => CandidateCommands.Attack(1, 2, 3, 4, 12345));
        Assert.Throws<ProtocolException>(() => CandidateCommands.CastSkill(256, 0, 0, 0, 1));
        Assert.Throws<ProtocolException>(() => CandidateCommands.UseFieldItem(65536, 0, 0));
    }
}
