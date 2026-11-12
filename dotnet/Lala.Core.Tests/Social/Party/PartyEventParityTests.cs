using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Social.Party;

public sealed class PartyEventParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    [Theory]
    [MemberData(nameof(PartyEventPythonVectors.Sequences), MemberType = typeof(PartyEventPythonVectors))]
    public void EveryTransitionHelperAndHistoricalSnapshotMatchesRetainedPython(string name, string json)
    {
        var state = PartyEventSnapshot.Empty;
        uint? ownRoleId = null;
        string? ownName = null;
        var historical = new List<(PartyEventSnapshot State, JsonNode Expected)>();
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            var before = state;
            var now = step!["now"]!.GetValue<double>();
            if (step["message"] is { } message)
            {
                var packet = new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                    Convert.FromHexString(message["hex"]!.GetValue<string>()));
                if (step["error"] is { } error)
                {
                    Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() =>
                    {
                        var observation = ServerProtocol.Decode(packet, ownRoleId);
                        state = PartyEventReducer.Apply(state, observation, now, ownRoleId);
                    }).Message);
                    Assert.Same(before, state);
                }
                else
                {
                    var observation = ServerProtocol.Decode(packet, ownRoleId);
                    state = PartyEventReducer.Apply(state, observation, now, ownRoleId);
                    if (observation is ServerSocialEvent social)
                        AssertJson(Project(state), Project(PartyEventReducer.Apply(before, social.Event, now, ownRoleId)), name);
                    // Match State.apply: party observes the current role before local world dispatch.
                    if (observation is ServerLayoutEvent { Event: WorldPlayerEvent world })
                    {
                        ownRoleId = world.Player.RoleId;
                        ownName = world.Player.Name;
                    }
                }
            }
            else if (step["seed"] is { } seed)
            {
                state = state with
                {
                    Outbound = seed["outbound"]!.Deserialize<ImmutableDictionary<string, PartyOutboundRequest>>(Options)!,
                    EnabledRequested = seed["enabled_requested"]!.GetValue<bool>()
                };
                if (seed["sent_request"] is { } sent)
                {
                    var request = sent.Deserialize<PartyRequest>(Options)!;
                    state = state with { Requests = state.Requests.SetItem(request.Key, request) };
                }
            }
            else if (step["expire"] is { } expired)
            {
                state = PartyEventReducer.Expire(state, now);
                Assert.Equal(expired.GetValue<bool>(), !ReferenceEquals(before, state));
            }
            Assert.Equal(step["own_role_id"]?.GetValue<uint>(), ownRoleId);
            Assert.Equal(step["own_name"]?.GetValue<string>(), ownName);
            AssertJson(step["expected"], Project(state), $"{name} step {index++}");
            Assert.Equal(step["team_order"]!.AsArray().Select(v => v!.GetValue<string>()),
                state.Teams.Select(team => team.LeaderId.ToString(CultureInfo.InvariantCulture)));
            AssertJson(step["own_team"], JsonSerializer.SerializeToNode(state.OwnTeam(ownRoleId), Options), name + " own team");
            foreach (var (roleId, expected) in step["names"]!.AsObject())
                Assert.Equal(expected!.GetValue<string>(), state.PlayerName(uint.Parse(roleId, CultureInfo.InvariantCulture), ownRoleId, ownName));
            historical.Add((state, step["expected"]!));
        }
        foreach (var (snapshot, expected) in historical) AssertJson(expected, Project(snapshot), name + " historical");
    }

    private static void AssertJson(JsonNode? expected, JsonNode? actual, string label) =>
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"{label}: expected {expected}; actual {actual}");

    private static JsonObject Project(PartyEventSnapshot state)
    {
        var teams = new JsonObject();
        foreach (var team in state.Teams)
            teams.Add(team.LeaderId.ToString(CultureInfo.InvariantCulture), JsonSerializer.SerializeToNode(team, Options));
        var result = new JsonObject
        {
            ["teams"] = teams, ["nearby"] = JsonSerializer.SerializeToNode(state.Nearby, Options),
            ["requests"] = JsonSerializer.SerializeToNode(state.Requests, Options),
            ["outbound"] = JsonSerializer.SerializeToNode(state.Outbound, Options),
            ["enabled"] = state.Enabled, ["status"] = state.Status
        };
        if (state.EnabledRequested is { } requested) result["enabled_requested"] = requested;
        return result;
    }

    public static IEnumerable<object[]> SourceHashes() => JsonNode.Parse(PartyEventPythonVectors.SourceSha256)!.AsObject()
        .Select(pair => new object[] { pair.Key, pair.Value!.GetValue<string>() });

    [Theory, MemberData(nameof(SourceHashes))]
    public void RetainedSourceHashesAcceptLfCrlfAndRejectContentEdits(string path, string expected)
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, path))) directory = directory.Parent;
        Assert.NotNull(directory);
        var lf = NormalizeCrlfPairs(File.ReadAllBytes(Path.Combine(directory.FullName, path)));
        var crlf = new List<byte>();
        foreach (var value in lf)
        {
            if (value == '\n') crlf.Add((byte)'\r');
            crlf.Add(value);
        }
        Assert.Equal(expected, Hash(lf));
        Assert.Equal(expected, Hash(crlf.ToArray()));
        Assert.NotEqual(expected, Hash([.. lf, (byte)' ']));
        Assert.NotEqual(expected, Hash([.. crlf, 0]));
        lf[0] ^= 1;
        Assert.NotEqual(expected, Hash(lf));
    }

    [Fact]
    public void SourceHashNormalizationPreservesAllOtherBytesAndIsNotRecursive()
    {
        byte[] canonical = [0xef, 0xbb, 0xbf, 0, 0xff, 0xfe, 13, 42, 10, 32, 13, 10, 13];
        byte[] checkout = [0xef, 0xbb, 0xbf, 0, 0xff, 0xfe, 13, 42, 13, 10, 32, 13, 13, 10, 13];
        Assert.Equal(canonical, NormalizeCrlfPairs(checkout));
        var expected = Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant();
        Assert.Equal(expected, Hash(checkout));
        Assert.NotEqual(expected, Hash(checkout.AsSpan(3)));
        Assert.NotEqual(expected, Hash([.. checkout, 0]));
        Assert.Empty(NormalizeCrlfPairs([]));
    }

    private static string Hash(ReadOnlySpan<byte> bytes) =>
        Convert.ToHexString(SHA256.HashData(NormalizeCrlfPairs(bytes))).ToLowerInvariant();

    private static byte[] NormalizeCrlfPairs(ReadOnlySpan<byte> source)
    {
        var bytes = new byte[source.Length];
        var count = 0;
        for (var index = 0; index < source.Length; index++)
        {
            if (source[index] == '\r' && index + 1 < source.Length && source[index + 1] == '\n') continue;
            bytes[count++] = source[index];
        }
        return bytes[..count];
    }
}
