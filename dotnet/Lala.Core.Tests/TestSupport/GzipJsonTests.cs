using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using Xunit;

namespace Lala.Core.Tests.TestSupport;

public sealed class GzipJsonTests
{
    private static string Hash(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static byte[] Compress(byte[] bytes)
    {
        using var output = new MemoryStream();
        using (var gzip = new GZipStream(output, CompressionLevel.SmallestSize, leaveOpen: true)) gzip.Write(bytes);
        return output.ToArray();
    }

    [Fact]
    public void Missing_resource_fails_instead_of_returning_empty_json() =>
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeResource("Lala.Core.Tests.Missing.json.gz", new string('0', 64), new string('0', 64)));

    [Fact]
    public void Verified_decode_preserves_exact_unicode_and_existing_byte_api()
    {
        var bytes = Encoding.UTF8.GetBytes("[\"空白 😀\", 1]\n");
        var compressed = Compress(bytes);
        Assert.Equal(Encoding.UTF8.GetString(bytes), GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes)));
        Assert.Equal(GzipJson.Decode(compressed), GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes)));
    }

    [Fact]
    public void Corrupt_truncated_or_wrong_hash_resources_fail_closed()
    {
        var bytes = Encoding.UTF8.GetBytes("{\"expected\":true}");
        var compressed = Compress(bytes);
        var damaged = (byte[])compressed.Clone();
        damaged[^1] ^= 1;
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(damaged), Hash(compressed), Hash(bytes)));
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed[..^1]), Hash(compressed), Hash(bytes)));
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), new string('0', 64)));
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed), "bad", Hash(bytes)));
        var notGzip = Encoding.UTF8.GetBytes("not gzip");
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(notGzip), Hash(notGzip), Hash(bytes)));
    }

    [Fact]
    public void Both_compressed_and_inflated_sizes_are_bounded()
    {
        var bytes = new byte[100_000];
        var compressed = Compress(bytes);
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes), compressed.Length - 1));
        Assert.Throws<InvalidDataException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes), maxDecodedBytes: bytes.Length - 1));
        Assert.Equal(bytes.Length, GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes), compressed.Length, bytes.Length).Length);
        Assert.Throws<ArgumentOutOfRangeException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes), 0));
    }

    [Fact]
    public void Invalid_utf8_is_not_silently_replaced()
    {
        byte[] bytes = [0xff];
        var compressed = Compress(bytes);
        Assert.Throws<DecoderFallbackException>(() => GzipJson.DecodeVerified(new MemoryStream(compressed), Hash(compressed), Hash(bytes)));
    }
}
