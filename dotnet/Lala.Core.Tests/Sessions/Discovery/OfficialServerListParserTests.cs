using System.Text.Json;
using Lala.Core.Sessions.Discovery;
using Xunit;
using static Lala.Core.Tests.Sessions.Discovery.DiscoveryTestSupport;

namespace Lala.Core.Tests.Sessions.Discovery;

public sealed class OfficialServerListParserTests
{
    [Fact]
    public void Parses_bom_sorts_lines_and_builds_Python_group_labels_without_mutable_rows()
    {
        var bytes = Bytes("[{\"id\":102,\"name\":\"two\",\"address\":\"1.1.1.1\",\"port\":65535}," +
            "{\"id\":1,\"name\":\"群\\n組\\u007f\"},{\"id\":101,\"name\":\"one\",\"address\":\"8.8.8.8\",\"port\":1}]");
        var rows = OfficialServerListParser.Parse([0xef, 0xbb, 0xbf, .. bytes], default);
        Assert.Equal(new[] { 101, 102 }, rows.Select(row => row.Id));
        Assert.Equal("群組｜1線 (101)", rows[0].Name);
        Assert.Equal(1, rows[0].GroupId); Assert.Equal(1, rows[0].Port);
        Assert.False(rows[0].CanLogin); Assert.False(rows[0].CanSendPackets);
    }

    [Theory]
    [InlineData("0.0.0.0")] [InlineData("0.1.2.3")] [InlineData("10.1.2.3")]
    [InlineData("100.64.0.1")] [InlineData("100.127.255.254")] [InlineData("127.0.0.1")]
    [InlineData("169.254.1.2")] [InlineData("172.16.0.1")] [InlineData("172.31.255.255")]
    [InlineData("192.0.0.9")] [InlineData("192.0.2.1")] [InlineData("192.88.99.1")]
    [InlineData("192.168.0.1")] [InlineData("198.18.0.1")] [InlineData("198.19.255.255")]
    [InlineData("198.51.100.1")] [InlineData("203.0.113.1")] [InlineData("224.0.0.1")]
    [InlineData("239.255.255.255")] [InlineData("240.0.0.1")] [InlineData("255.255.255.255")]
    [InlineData("::1")] [InlineData("::ffff:8.8.8.8")] [InlineData("2001:4860:4860::8888")]
    [InlineData("fe80::1%1")] [InlineData("ff02::1")] [InlineData("[2001:4860:4860::8888]")]
    [InlineData("8.8.8.8:443")] [InlineData("https://8.8.8.8")]
    [InlineData("example.com")] [InlineData("localhost")] [InlineData("")]
    [InlineData("8.8.8")] [InlineData("8.8.2056")] [InlineData("134744072")]
    [InlineData("0x08080808")] [InlineData("010.8.8.8")] [InlineData("008.8.8.8")]
    [InlineData("8.8.8.8 ")] [InlineData(" 8.8.8.8")] [InlineData("8.8.8.8\n")]
    [InlineData("+8.8.8.8")] [InlineData("8.8.8.256")] [InlineData("8.8.8.-1")]
    [InlineData("８.8.8.8")] [InlineData("8.8.8.8/32")]
    public void Rejects_nonpublic_unsupported_and_ambiguous_literals(string address)
    {
        var failure = Assert.Throws<OfficialServerDiscoveryException>(() => OfficialServerListParser.Parse(List(address), default));
        Assert.Equal(OfficialServerDiscoveryFailure.InvalidEndpoint, failure.Failure);
    }

    [Theory]
    [InlineData("1.1.1.1")] [InlineData("8.8.8.8")] [InlineData("100.63.255.255")]
    [InlineData("100.128.0.1")] [InlineData("172.15.255.255")] [InlineData("172.32.0.1")]
    [InlineData("192.0.1.1")] [InlineData("198.17.0.1")] [InlineData("198.20.0.1")]
    [InlineData("223.255.255.254")]
    public void Supports_canonical_public_IPv4_subset(string address)
        => Assert.Single(OfficialServerListParser.Parse(List(address), default));

    [Theory]
    [InlineData("[]")] [InlineData("{}")] [InlineData("null")] [InlineData("[null]")]
    [InlineData("[{\"id\":1,\"name\":\"group\"}]")]
    [InlineData("[{\"id\":201,\"name\":\"line\",\"address\":\"8.8.8.8\",\"port\":1}]")]
    [InlineData("[{\"id\":1,\"id\":2,\"name\":\"group\"}]")]
    [InlineData("[{\"id\":1,\"name\":\"group\",\"na\\u006de\":\"other\"}]")]
    [InlineData("[{\"id\":1,\"name\":\"group\"},]")]
    public void Rejects_bad_shape_missing_group_and_duplicate_keys(string json)
        => Assert.Throws<OfficialServerDiscoveryException>(() => OfficialServerListParser.Parse(Bytes(json), default));

    [Theory]
    [InlineData("id", "true")] [InlineData("id", "\"101\"")] [InlineData("id", "101.0")]
    [InlineData("id", "1.01e2")] [InlineData("id", "0")] [InlineData("id", "-1")]
    [InlineData("id", "100")] [InlineData("id", "65536")] [InlineData("id", "201")]
    [InlineData("port", "false")] [InlineData("port", "\"1\"")] [InlineData("port", "1.0")]
    [InlineData("port", "0")] [InlineData("port", "-1")] [InlineData("port", "65536")]
    [InlineData("name", "null")] [InlineData("name", "\"\"")] [InlineData("name", "42")]
    [InlineData("address", "null")] [InlineData("address", "42")]
    public void Rejects_invalid_row_fields(string field, string replacement)
    {
        var root = JsonSerializer.Deserialize<List<Dictionary<string, JsonElement>>>(List())!;
        root[1][field] = JsonDocument.Parse(replacement).RootElement.Clone();
        Assert.Throws<OfficialServerDiscoveryException>(() => OfficialServerListParser.Parse(JsonSerializer.SerializeToUtf8Bytes(root), default));
    }

    [Fact]
    public void Rejects_duplicate_ids_nested_line_as_group_and_oversized_names_or_rows()
    {
        var line = new { id = 101, name = "line", address = "8.8.8.8", port = 1 };
        foreach (object[] rows in new object[][]
        {
            [new { id = 1, name = "group" }, line, line],
            [new { id = 1, name = "group" }, new { id = 1, name = "duplicate" }, line],
            [new { id = 1, name = "group" }, line, new { id = 10101, name = "line as group", address = "8.8.8.8", port = 1 }],
            [new { id = 1, name = new string('x', 121) }, line],
            [new { id = 100, name = "sentinel" }, new { id = 10001, name = "line", address = "8.8.8.8", port = 1 }]
        }) Assert.Throws<OfficialServerDiscoveryException>(() => OfficialServerListParser.Parse(JsonSerializer.SerializeToUtf8Bytes(rows), default));
        var tooMany = Enumerable.Range(1, 257).Select(id => new { id, name = "row" }).ToArray();
        Assert.Throws<OfficialServerDiscoveryException>(() => OfficialServerListParser.Parse(JsonSerializer.SerializeToUtf8Bytes(tooMany), default));
    }

    [Fact]
    public void Enforces_bytes_UTF8_and_cancellation()
    {
        foreach (byte[] raw in new byte[][] { [], new byte[65537], [0xff, 0xfe, 0x5b, 0x5d], [0x5b, 0xff, 0x5d] })
            Assert.Throws<OfficialServerDiscoveryException>(() => OfficialServerListParser.Parse(raw, default));
        byte[] atLimit = new byte[65536];
        Array.Fill(atLimit, (byte)' '); List().CopyTo(atLimit, 0);
        Assert.Single(OfficialServerListParser.Parse(atLimit, default));
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        Assert.ThrowsAny<OperationCanceledException>(() => OfficialServerListParser.Parse(List(), cancellation.Token));
    }
}
