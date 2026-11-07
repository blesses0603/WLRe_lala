using System.Text.Json;
using Lala.Core.Battle;
using Lala.Core.Protocol;
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
        var history = new List<(EfficiencySnapshot Snapshot, JsonElement Expected)>();
        foreach (var step in document.RootElement.EnumerateArray())
        {
            var knowledge = EfficiencyParityTests.Knowledge(step.GetProperty("knowledge"));
            var packet = new Packet(step.GetProperty("main").GetInt32(), step.GetProperty("sub").GetInt32(),
                Convert.FromHexString(step.GetProperty("hex").GetString()!));
            if (step.GetProperty("error").ValueKind != JsonValueKind.Null)
            {
                var error = Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet, knowledge.RoleId));
                Assert.Equal(step.GetProperty("error").GetString(), error.Message);
            }
            else
            {
                var observation = ServerProtocol.Decode(packet, knowledge.RoleId);
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
            history.Add((state, step.GetProperty("expected")));
        }
        foreach (var (snapshot, expected) in history) EfficiencyParityTests.AssertSnapshot(expected, snapshot);
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
