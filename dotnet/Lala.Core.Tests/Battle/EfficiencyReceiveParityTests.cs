using System.Text.Json;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.Tests.Inventory;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class EfficiencyReceiveParityTests
{
    [Theory]
    [MemberData(nameof(EfficiencyReceivePythonVectors.Sequences), MemberType = typeof(EfficiencyReceivePythonVectors))]
    public void DecoderAdapterAndImmutableObserverMatchRetainedPython(string name, string json)
    {
        Assert.NotEmpty(name);
        using var document = JsonDocument.Parse(json);
        var state = EfficiencySnapshot.Empty;
        var player = PlayerKnowledgeSnapshot.Empty;
        var companions = CompanionReceiveSnapshot.Empty;
        var local = new LocalStateSnapshot();
        var history = new List<(EfficiencySnapshot Snapshot, JsonElement Expected)>();
        var knowledgeHistory = new List<(EfficiencyKnowledgeSnapshot Actual, EfficiencyKnowledgeSnapshot Expected)>();
        foreach (var step in document.RootElement.EnumerateArray())
        {
            var expectedKnowledge = EfficiencyParityTests.Knowledge(step.GetProperty("knowledge"));
            var project = step.GetProperty("project_knowledge").GetBoolean();
            var knowledge = project ? EfficiencyKnowledgeProjector.Project(player, companions, local.Player) : expectedKnowledge;
            var preLocalRole = project ? local.Player?.RoleId : knowledge.RoleId;
            var packet = new Packet(step.GetProperty("main").GetInt32(), step.GetProperty("sub").GetInt32(),
                Convert.FromHexString(step.GetProperty("hex").GetString()!));
            if (step.GetProperty("error").ValueKind != JsonValueKind.Null)
            {
                var error = Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet, preLocalRole));
                Assert.Equal(step.GetProperty("error").GetString(), error.Message);
            }
            else
            {
                var observation = ServerProtocol.Decode(packet, preLocalRole);
                if (project)
                {
                    // Test only the prerequisite receive/local slices, not a production
                    // service coordinator. No observer is replaced with empty knowledge.
                    var updated = CombatKnowledgeReceiveReducer.Apply(player, companions, local.Battle, observation, preLocalRole);
                    player = updated.Player;
                    companions = CompanionReceiveReducer.ApplyBeforeLocal(updated.Companions, observation, preLocalRole);
                    local = new LocalStateCoordinator(new(local.Session, local.World, updated.Battle)).Apply(observation);
                    companions = CompanionReceiveReducer.ObserveLocalAttribute(companions, observation);
                    knowledge = EfficiencyKnowledgeProjector.Project(player, companions, local.Player);
                }
                var when = step.GetProperty("when");
                double time = when.ValueKind == JsonValueKind.Number ? when.GetDouble() : when.GetString() switch
                {
                    "nan" => double.NaN, "inf" => double.PositiveInfinity, "-inf" => double.NegativeInfinity,
                    _ => throw new InvalidOperationException("Unknown fixture time")
                };
                bool? offline = step.GetProperty("offline").ValueKind == JsonValueKind.Null ? null : step.GetProperty("offline").GetBoolean();
                state = EfficiencyReceiveReducer.Apply(state, knowledge, observation, time, offline);
            }
            EfficiencyParityTests.AssertSnapshot(step.GetProperty("expected"), state);
            AssertKnowledge(expectedKnowledge, knowledge);
            history.Add((state, step.GetProperty("expected")));
            knowledgeHistory.Add((knowledge, expectedKnowledge));
        }
        foreach (var (snapshot, expected) in history) EfficiencyParityTests.AssertSnapshot(expected, snapshot);
        foreach (var (actual, expected) in knowledgeHistory) AssertKnowledge(expected, actual);
    }

    private static void AssertKnowledge(EfficiencyKnowledgeSnapshot expected, EfficiencyKnowledgeSnapshot actual)
    {
        Assert.Equal(expected.RoleId, actual.RoleId);
        Assert.Equal(expected.PlayerName, actual.PlayerName);
        Assert.Equal(expected.PlayerStats, actual.PlayerStats);
        Assert.Equal(expected.Companions.Count, actual.Companions.Count);
        foreach (var (slot, profile) in expected.Companions) Assert.Equal(profile, actual.Companions[slot]);
    }

    [Fact]
    public void OracleHashesNormalizeOnlyByteCrLf()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/core/efficiency.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        using var hashes = JsonDocument.Parse(EfficiencyReceivePythonVectors.SourceSha256);
        foreach (var value in hashes.RootElement.EnumerateObject())
            Assert.Equal(value.Value.GetString(), LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName, value.Name))));
    }
}
