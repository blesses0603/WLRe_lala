using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.World;
using Lala.Core.World.Tent;
using Xunit;

namespace Lala.Core.Tests.World.Tent;

public sealed class TentDecoderTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly JsonNode[] Vectors = PythonTentVectors.JsonParts.SelectMany(part => JsonNode.Parse(part)!.AsArray()).Cast<JsonNode>().ToArray();
    public static IEnumerable<object[]> AllCases() => Cases(Vectors);
    public static IEnumerable<object[]> ValidCases() => Cases(Vectors.Where(v => v["expected"] is not null));
    private static IEnumerable<object[]> Cases(IEnumerable<JsonNode> values) => values.Select(v => new object[] { v["name"]!.GetValue<string>(), v.ToJsonString() });
    private static byte[] Bytes(JsonNode vector) => Convert.FromHexString(vector["hex"]!.GetValue<string>());
    private static TentEvent? Decode(JsonNode vector, ReadOnlySpan<byte> bytes) => TentDecoder.Decode(new(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), bytes));
    [Theory, MemberData(nameof(ValidCases))]
    public void CommonDispatcherPreservesTypedTentObservations(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        var packet = new Packet(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), Bytes(vector));
        var actual = Assert.IsAssignableFrom<TentEvent>(ServerProtocol.Decode(packet));
        Assert.True(JsonNode.DeepEquals(vector["expected"], JsonSerializer.SerializeToNode(actual, actual.GetType(), Options)));
    }

    private static JsonNode? Canonical(JsonNode? value) => value switch
    {
        JsonObject obj => new JsonObject(obj.OrderBy(p => p.Key, StringComparer.Ordinal)
            .Select(p => new KeyValuePair<string, JsonNode?>(p.Key, Canonical(p.Value)))),
        JsonArray array => new JsonArray(array.Select(Canonical).ToArray()),
        _ => value?.DeepClone()
    };

    private static void AssertOutcome(JsonNode vector, JsonNode outcome, ReadOnlySpan<byte> bytes)
    {
        var data = bytes.ToArray();
        if (outcome["error"] is { } error)
        {
            Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() => Decode(vector, data)).Message);
            return;
        }
        var result = Decode(vector, data);
        JsonNode? actual = result is null ? null : JsonSerializer.SerializeToNode(result, result.GetType(), Options);
        if (result is not null)
        {
            Assert.Equal(vector["main"]!.GetValue<byte>(), result.Main);
            Assert.Equal(vector["sub"]!.GetValue<byte>(), result.Sub);
            Assert.Equal($"{result.Type} (S{result.Main}-{result.Sub})", result.ToString());
        }
        if (outcome["sha256"] is { } hash)
        {
            var json = Canonical(actual)?.ToJsonString() ?? "null";
            Assert.Equal(hash.GetValue<string>(), Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant());
        }
        else Assert.True(JsonNode.DeepEquals(outcome["expected"], actual), $"Expected {outcome["expected"]}; actual {actual}");
    }

    [Theory, MemberData(nameof(AllCases))]
    public void AllFieldsUnknownKeysAndMalformedErrorsMatchRetainedPython(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector, Bytes(vector));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryTruncationBoundaryIncludingCompleteListPrefixesMatchesPython(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; var bytes = Bytes(vector);
        var prefixes = vector["prefixes"]!.AsArray(); Assert.Equal(bytes.Length, prefixes.Count);
        for (var length = 0; length < bytes.Length; length++)
            AssertOutcome(vector, prefixes[length]!, bytes.AsSpan(0, length));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void TailsKeepSourceLengthErrorsOrOpaqueExtendedSignalPolicy(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector["tail"]!, [.. Bytes(vector), 0x7e]);
    }

    [Theory]
    [InlineData(2)] [InlineData(5)] [InlineData(8)]
    public void NonemptySignalPayloadNeverConfirmsAnOutcome(int sub)
    {
        Assert.NotNull(TentDecoder.Decode(new(65, sub)));
        Assert.Null(TentDecoder.Decode(new(65, sub, [0])));
        Assert.Null(TentDecoder.Decode(new(65, sub, new byte[65535])));
    }

    [Fact]
    public void PermissiveByteBooleansAreNotMistakenForArkFlags()
    {
        for (var raw = 0; raw <= 255; raw++)
        {
            var access = Assert.IsType<TentAccessEvent>(TentDecoder.Decode(new(65, 7, [(byte)raw, (byte)raw])));
            Assert.Equal(raw == 0, access.AccessOpen); Assert.Equal(raw != 0, access.ShowMessage);
        }
    }

    [Fact]
    public void ListsAreImmutableOwnInputAndPreserveUnvalidatedDuplicateOwners()
    {
        var source = new PacketWriter().U32(123456789).U16(65535).U32(uint.MaxValue).U32(0).U8(255).U8(0).Build();
        var packet = new Packet(65, 3, [.. source, .. source]); Array.Fill(source, (byte)0);
        var result = Assert.IsType<TentSceneListEvent>(TentDecoder.Decode(packet));
        Assert.Equal(2, result.Tents.Length); Assert.Equal(result.Tents[0], result.Tents[1]);
        Assert.Equal(123456789u, result.Tents[0].OwnerId);
        Assert.Throws<NotSupportedException>(() => ((IList<TentCamp>)result.Tents).Clear());
        Assert.DoesNotContain("123456789", result.ToString());
        Assert.Equal(nameof(TentCamp), result.Tents[0].ToString());
        Assert.Empty(Assert.IsType<TentSceneListEvent>(TentDecoder.Decode(new(65, 3))).Tents);
    }

    [Fact]
    public void DecoderDoesNotInventRowCapsOrRequireIdentityAndRuntimeCatalogs()
    {
        // Packet's in-memory receive API has no wire-size cap; the source checks only alignment.
        var result = Assert.IsType<TentSceneListEvent>(TentDecoder.Decode(new(65, 3, new byte[16 * 4096])));
        Assert.Equal(4096, result.Tents.Length);
        Assert.Single(typeof(TentDecoder).GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static));
        Assert.Throws<ArgumentNullException>(() => TentDecoder.Decode(null!));
    }

    [Fact]
    public void TheseServiceObservationsDoNotInventWorldGeometryUpdates()
    {
        var state = new WorldEventSnapshot { Navigation = new() { Revision = 42, Stale = false } };
        foreach (var vector in Vectors.Where(v => v["expected"] is not null))
            Assert.Same(state, WorldEventReducer.Apply(state, Decode(vector, Bytes(vector))!));
    }
}
