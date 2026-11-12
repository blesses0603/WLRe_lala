using System.Globalization;
using System.Numerics;
using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.State;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Social.GuildActions;

public sealed class GuildActionsParityTests
{
    [Theory]
    [MemberData(nameof(GuildActionsPythonVectors.Sequences), MemberType = typeof(GuildActionsPythonVectors))]
    public void EveryTransitionAndHistoricalSnapshotMatchesRetainedPython(string name, string json)
    {
        var state = GuildActionsReceiveSnapshot.Empty;
        var guild = GuildEventSnapshot.Empty;
        var local = new LocalStateCoordinator();
        var historical = new List<(GuildActionsReceiveSnapshot State, JsonNode Expected)>();
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            var before = state;
            if (step!["seed"] is { } seed) state = Read(seed);
            else if (step["message"] is { } message)
            {
                var packet = new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                    Convert.FromHexString(message["hex"]!.GetValue<string>()));
                if (step["error"] is { } error)
                {
                    var beforeGuild = guild;
                    var beforeLocal = local.Snapshot();
                    Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() =>
                        Apply(ServerProtocol.Decode(packet, beforeLocal.Player?.RoleId))).Message);
                    Assert.Same(before, state); Assert.Same(beforeGuild, guild); Assert.Same(beforeLocal, local.Snapshot());
                }
                else Apply(ServerProtocol.Decode(packet, local.Snapshot().Player?.RoleId));
            }
            var after = local.Snapshot();
            var context = new GuildActionsReceiveContext(after.Player?.RoleId, guild, after.Session.Gold);
            Assert.Equal(step["own_role_id"]?.GetValue<uint>(), context.PlayerRoleId);
            Assert.Equal(step["valid_member"]!.GetValue<bool>(), context.ValidMember);
            AssertSnapshot(step["expected"]!, state, $"{name}, step {index++}");
            historical.Add((state, step["expected"]!));

            void Apply(ServerEvent observation)
            {
                // Same exact observer order as Python State.apply. Do not feed old gold
                // or the roster observer's pre-local identity into the actions reducer.
                guild = GuildEventReducer.Apply(guild, observation, local.Snapshot().Player?.RoleId);
                var afterLocal = local.Apply(observation);
                var context = new GuildActionsReceiveContext(afterLocal.Player?.RoleId, guild, afterLocal.Session.Gold);
                state = GuildActionsReceiveReducer.Apply(state, observation, context);
                if (observation is ServerSocialEvent social)
                    Assert.True(JsonNode.DeepEquals(Project(state),
                        Project(GuildActionsReceiveReducer.Apply(before, social.Event, context))));
            }
        }
        foreach (var (snapshot, expected) in historical) AssertSnapshot(expected, snapshot, name + " historical");
    }

    private static void AssertSnapshot(JsonNode expected, GuildActionsReceiveSnapshot actual, string label)
    {
        var projection = Project(actual);
        LazyAssert.True(JsonNode.DeepEquals(expected, projection), () => $"{label}: expected {expected}; actual {projection}");
    }

    internal static GuildActionsReceiveSnapshot Read(JsonNode node) => new()
    {
        SignEnabled = node["sign_enabled"]!.GetValue<bool>(), DonateEnabled = node["donate_enabled"]!.GetValue<bool>(),
        SellId = node["sell_id"]!.GetValue<ushort>(), Target = node["target"]!.GetValue<int>(), Budget = Integer(node["budget"]!),
        SettingsRevision = Integer(node["settings_revision"]!), Reserved = Integer(node["reserved"]!), Confirmed = Integer(node["confirmed"]!),
        Pending = ReadPending(node["pending"]), Uncertain = node["uncertain"]!.GetValue<bool>(),
        Role = node["role"]?.GetValue<uint>(), Guild = node["guild"]?.GetValue<uint>(), SignState = node["sign_state"]?.GetValue<byte>(),
        Remaining = node["remaining"]?.GetValue<byte>(), Allow = node["allow"]!.GetValue<bool>(), SignAttempted = node["sign_attempted"]!.GetValue<bool>(),
        CountsReady = node["counts_ready"]!.GetValue<bool>(), Counts = node["counts"]!.AsObject().ToImmutableDictionary(
            pair => byte.Parse(pair.Key, CultureInfo.InvariantCulture), pair => pair.Value!.GetValue<byte>()),
        Epoch = Integer(node["epoch"]!), CatalogToken = ReadToken(node["catalog_token"]), CatalogReady = node["catalog_ready"]!.GetValue<bool>(),
        Price = node["price"] is { } price ? Integer(price) : null, Donated = node["donated"]?.GetValue<int>(), Status = node["status"]!.GetValue<string>()
    };

    private static GuildActionPending? ReadPending(JsonNode? p)
    {
        if (p is null) return null;
        var role = p["role"]!.GetValue<uint>(); var guild = p["guild"]!.GetValue<uint>();
        var token = ReadToken(p["token"]); var epoch = Integer(p["epoch"]!); var due = p["due"]!.GetValue<double>();
        if (p["kind"]!.GetValue<string>() == "sign") return new GuildSignPending(role, guild, token, epoch, due, p["sign_ack"]!.GetValue<bool>());
        var q = p["quote"]!;
        return new GuildDonationPending(role, guild, token, epoch, due,
            new(Integer(q["price"]!), q["price_kind"]!.GetValue<byte>(), q["sell_id"]!.GetValue<ushort>(),
                q["save_index"]!.GetValue<byte>(), q["count"]!.GetValue<int>(), q["item_index"]?.GetValue<byte>()),
            p["before_remaining"]!.GetValue<byte>(), p["gold_before"]!.GetValue<uint>(), p["gold_ack"]!.GetValue<bool>(),
            p["sell_ack"]!.GetValue<bool>(), p["remaining_ack"]!.GetValue<bool>());
    }

    private static GuildActionsCatalogToken? ReadToken(JsonNode? token) => token is null ? null :
        new(token[0]!.GetValue<bool>(), token[1]?.GetValue<string>());
    private static BigInteger Integer(JsonNode node) => BigInteger.Parse(node.ToJsonString(), CultureInfo.InvariantCulture);
    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static JsonNode? Token(GuildActionsCatalogToken? value) => value is null ? null : new JsonArray(value.Attempted, value.IdentityKey);

    internal static JsonObject Project(GuildActionsReceiveSnapshot state)
    {
        var counts = new JsonObject();
        foreach (var (key, count) in state.Counts) counts[key.ToString(CultureInfo.InvariantCulture)] = count;
        JsonObject? pending = null;
        if (state.Pending is { } p)
        {
            pending = new() { ["kind"] = p is GuildSignPending ? "sign" : "donate", ["role"] = p.Role, ["guild"] = p.Guild,
                ["token"] = Token(p.Token), ["epoch"] = Number(p.Epoch), ["due"] = p.Due };
            if (p is GuildSignPending sign) pending["sign_ack"] = sign.SignAck;
            else if (p is GuildDonationPending donate)
            {
                pending["quote"] = new JsonObject { ["price"] = Number(donate.Quote.Price), ["price_kind"] = donate.Quote.PriceKind,
                    ["sell_id"] = donate.Quote.SellId, ["save_index"] = donate.Quote.SaveIndex, ["count"] = donate.Quote.Count,
                    ["item_index"] = donate.Quote.ItemIndex };
                pending["before_remaining"] = donate.BeforeRemaining; pending["gold_before"] = donate.GoldBefore;
                pending["gold_ack"] = donate.GoldAck; pending["sell_ack"] = donate.SellAck; pending["remaining_ack"] = donate.RemainingAck;
            }
        }
        return new()
        {
            ["sign_enabled"] = state.SignEnabled, ["donate_enabled"] = state.DonateEnabled, ["sell_id"] = state.SellId,
            ["target"] = state.Target, ["budget"] = Number(state.Budget), ["settings_revision"] = Number(state.SettingsRevision),
            ["reserved"] = Number(state.Reserved), ["confirmed"] = Number(state.Confirmed), ["pending"] = pending,
            ["uncertain"] = state.Uncertain, ["role"] = state.Role, ["guild"] = state.Guild, ["sign_state"] = state.SignState,
            ["remaining"] = state.Remaining, ["allow"] = state.Allow, ["sign_attempted"] = state.SignAttempted,
            ["counts_ready"] = state.CountsReady, ["counts"] = counts, ["epoch"] = Number(state.Epoch),
            ["catalog_token"] = Token(state.CatalogToken), ["catalog_ready"] = state.CatalogReady,
            ["price"] = state.Price is { } price ? Number(price) : null, ["donated"] = state.Donated, ["status"] = state.Status
        };
    }

    [Fact]
    public void FixtureSourceHashesMatchRetainedPythonIgnoringOnlyCrlfPairs()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !Directory.Exists(Path.Combine(directory.FullName, "wlre"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, hash) in JsonNode.Parse(GuildActionsPythonVectors.SourceSha256)!.AsObject())
        {
            var bytes = File.ReadAllBytes(Path.Combine(directory.FullName, path));
            Assert.Equal(hash!.GetValue<string>(), Hash(bytes));
            var canonical = Canonical(bytes);
            var crlf = canonical.SelectMany(value => value == 10 ? new byte[] { 13, 10 } : [value]).ToArray();
            Assert.Equal(hash.GetValue<string>(), Hash(crlf));
            Assert.NotEqual(hash.GetValue<string>(), Hash([.. bytes, 32]));
        }
        Assert.True(GuildActionsPythonVectors.SnapshotCount >= 2300);
    }

    [Fact]
    public void HashCanonicalizationPreservesBomLoneCrInvalidUtf8AndWhitespace()
    {
        byte[] lf = [0xef, 0xbb, 0xbf, 0xff, 0, 13, 32, 10];
        byte[] crlf = [0xef, 0xbb, 0xbf, 0xff, 0, 13, 32, 13, 10];
        Assert.Equal(Hash(lf), Hash(crlf)); Assert.NotEqual(Hash(lf), Hash(lf.AsSpan(3)));
        Assert.NotEqual(Hash(lf), Hash([0xef, 0xbb, 0xbf, 0xff, 0, 32, 10]));
        Assert.NotEqual(Hash(lf), Hash([.. lf, 0]));
    }

    private static string Hash(ReadOnlySpan<byte> bytes) => Convert.ToHexString(SHA256.HashData(Canonical(bytes))).ToLowerInvariant();
    private static byte[] Canonical(ReadOnlySpan<byte> bytes)
    {
        var output = new List<byte>(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
            if (bytes[i] != 13 || i + 1 == bytes.Length || bytes[i + 1] != 10) output.Add(bytes[i]);
        return output.ToArray();
    }
}
