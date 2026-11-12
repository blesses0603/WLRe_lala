using System.Globalization;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Social;

public sealed class GuildEventParityTests
{
    [Theory]
    [MemberData(nameof(GuildEventPythonVectors.Sequences), MemberType = typeof(GuildEventPythonVectors))]
    public void EveryTransitionAndHistoricalSnapshotMatchesRetainedPython(string name, string json)
    {
        var state = GuildEventSnapshot.Empty;
        uint? ownRoleId = null;
        var historical = new List<(GuildEventSnapshot State, JsonNode Expected)>();
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            var before = state;
            if (step!["message"] is { } message)
            {
                var packet = new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                    Convert.FromHexString(message["hex"]!.GetValue<string>()));
                if (step["error"] is { } error)
                {
                    Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() =>
                    {
                        var observation = ServerProtocol.Decode(packet, ownRoleId);
                        state = GuildEventReducer.Apply(state, observation, ownRoleId);
                    }).Message);
                    Assert.Same(before, state);
                }
                else
                {
                    var observation = ServerProtocol.Decode(packet, ownRoleId);
                    state = GuildEventReducer.Apply(state, observation, ownRoleId);
                    if (observation is ServerSocialEvent social)
                        Assert.True(JsonNode.DeepEquals(Project(state),
                            Project(GuildEventReducer.Apply(before, social.Event, ownRoleId))));
                    if (observation is ServerLayoutEvent { Event: WorldPlayerEvent world })
                        ownRoleId = world.Player.RoleId;
                }
            }
            Assert.Equal(step!["own_role_id"]?.GetValue<uint>(), ownRoleId);
            var expected = step["expected"]!;
            AssertSnapshot(expected, state, $"{name}, step {index++}");
            historical.Add((state, expected));
        }
        // Old snapshots, including nested member names, remain unchanged by all later events.
        foreach (var (snapshot, expected) in historical) AssertSnapshot(expected, snapshot, name + " historical");
    }

    private static void AssertSnapshot(JsonNode expected, GuildEventSnapshot actual, string label)
    {
        var projection = Project(actual);
        LazyAssert.True(JsonNode.DeepEquals(expected, projection), () => $"{label}: expected {expected}; actual {projection}");
    }

    private static JsonObject Project(GuildEventSnapshot state)
    {
        if (!state.Ready)
        {
            Assert.Null(state.Name);
            Assert.Null(state.Serial);
            Assert.Null(state.Level);
            Assert.Empty(state.Members);
            return new();
        }
        var members = new JsonObject();
        foreach (var (roleId, member) in state.Members)
            members[roleId.ToString(CultureInfo.InvariantCulture)] = new JsonObject
            {
                ["role_id"] = member.RoleId, ["name"] = member.Name
            };
        return new()
        {
            ["ready"] = state.Ready, ["name"] = state.Name, ["serial"] = state.Serial,
            ["level"] = state.Level, ["members"] = members
        };
    }
}
