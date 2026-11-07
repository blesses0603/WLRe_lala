using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Instances;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Instances;

public sealed class InstanceDecoderTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public static IEnumerable<object[]> Cases() => JsonDocument.Parse(PythonInstanceVectors.Json)
        .RootElement.EnumerateArray().Select(sample => new object[] { sample.GetProperty("label").GetString()!, sample.Clone() });
    public static IEnumerable<object[]> RecognizedCases() => Cases().Where(item =>
        ((JsonElement)item[1]).TryGetProperty("expected", out var expected) && expected.ValueKind != JsonValueKind.Null);

    [Theory, MemberData(nameof(Cases))]
    public void PythonParity(string label, JsonElement sample)
    {
        var packet = ReadPacket(sample);
        if (sample.TryGetProperty("error", out _))
        {
            Assert.Throws<ProtocolException>(() => InstanceDecoder.Decode(packet));
            Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet));
            return;
        }
        var actual = InstanceDecoder.Decode(packet);
        var expected = sample.GetProperty("expected");
        if (expected.ValueKind == JsonValueKind.Null)
        {
            Assert.Null(actual);
            Assert.IsType<UnimplementedServerEvent>(ServerProtocol.Decode(packet));
            return;
        }
        Assert.NotNull(actual);
        var dispatched = Assert.IsType<ServerInstanceEvent>(ServerProtocol.Decode(packet));
        Assert.Equal(packet.Main, dispatched.Main); Assert.Equal(packet.Sub, dispatched.Sub);
        Assert.True(JsonNode.DeepEquals(JsonSerializer.SerializeToNode(actual, actual.GetType(), Options), JsonSerializer.SerializeToNode(dispatched.Event, dispatched.Event.GetType(), Options)));
        var actualJson = JsonSerializer.SerializeToNode(actual, actual.GetType(), Options);
        var expectedJson = JsonNode.Parse(expected.GetRawText());
        Assert.True(JsonNode.DeepEquals(expectedJson, actualJson), $"{label}: expected {expectedJson}; actual {actualJson}");
    }

    [Theory, MemberData(nameof(RecognizedCases))]
    public void RecognizedPacketsRejectEveryIncompletePrefixAndUnparsedTail(string label, JsonElement sample)
    {
        Assert.NotEmpty(label);
        var packet = ReadPacket(sample);
        var payload = packet.Payload.ToArray();
        Assert.Throws<ProtocolException>(() => InstanceDecoder.Decode(new(packet.Main, packet.Sub,
            payload.Concat(new byte[] { 0 }).ToArray())));
        for (var size = 0; size < payload.Length; size++)
        {
            // S186-10 has no count prefix. Every complete 9-byte prefix (including
            // empty) is a valid receipt; it does not imply the reward was claimed.
            if (packet.Main == 186 && packet.Sub == 10 && size % 9 == 0)
            {
                var receipt = Assert.IsType<CoopRewardReceiptEvent>(InstanceDecoder.Decode(new(186, 10, payload.AsSpan(0, size))));
                Assert.Equal(size / 9, receipt.Awards.Length);
            }
            else
                Assert.Throws<ProtocolException>(() => InstanceDecoder.Decode(new(packet.Main, packet.Sub, payload.AsSpan(0, size))));
        }
    }

    [Fact]
    public void UnknownMainsAndSubtypesKeepOpaquePayloadsUninterpreted()
    {
        var mainSubtypes = new HashSet<int> { 1, 2, 3, 4, 5, 7, 9, 10, 12, 15, 17, 21 };
        var coopSubtypes = new HashSet<int> { 2, 3, 6, 10, 11, 13, 15, 17, 20 };
        for (var value = 0; value <= 255; value++)
        {
            if (value is not (85 or 186)) Assert.Null(InstanceDecoder.Decode(new(value, 1, new byte[] { 255, 254 })));
            if (!mainSubtypes.Contains(value)) Assert.Null(InstanceDecoder.Decode(new(85, value, new byte[] { 255, 254 })));
            if (!coopSubtypes.Contains(value)) Assert.Null(InstanceDecoder.Decode(new(186, value, new byte[] { 255, 254 })));
        }
    }

    [Theory]
    [InlineData(5)]
    [InlineData(9)]
    [InlineData(10)]
    [InlineData(21)]
    public void UnknownInnerKindsIgnoreOpaqueTailsButRequireTheDiscriminator(int sub)
    {
        var recognized = sub switch
        {
            5 => new HashSet<int> { 1, 2, 3, 4, 5 },
            9 => [1],
            10 => [1, 2, 3, 4, 5, 6],
            _ => [0, 1, 2, 3, 4, 5, 6, 98, 99, 100, 101, 102]
        };
        Assert.Throws<ProtocolException>(() => InstanceDecoder.Decode(new(85, sub)));
        for (var kind = 0; kind <= 255; kind++)
        {
            if (recognized.Contains(kind)) continue;
            Assert.Null(InstanceDecoder.Decode(new(85, sub, new byte[] { (byte)kind })));
            Assert.Null(InstanceDecoder.Decode(new(85, sub, new byte[] { (byte)kind, 255, 0, 254 })));
        }
    }

    [Fact]
    public void AllCoopResultCodesFollowOnlyTheSourceDefinedSpecialCases()
    {
        for (var code = 0; code <= 255; code++)
        {
            if (code is 17 or 18) continue;
            var payload = code is 16 or 19 ? new byte[] { (byte)code, 255, 255, 255, 255 } : [(byte)code];
            var result = Assert.IsType<CoopResultEvent>(InstanceDecoder.Decode(new(186, 2, payload)));
            Assert.Equal((byte)code, result.Code);
            Assert.Equal(code is 16 or 19 ? uint.MaxValue : (uint?)null, result.RoleId);
        }
    }

    [Fact]
    public void CoopHostIsTheFirstWireSlotEvenWhenItIsEmpty()
    {
        var writer = new PacketWriter().Raw(new byte[] { 1, 2, 99, 0, 255, 7, 8, 3 });
        foreach (var roleId in new uint[] { 0, 0xffffffff, 0xffffffff })
            writer.U32(roleId).U8(255).U32(1).U32(2).U32(3).U32(4);
        var members = Assert.IsType<CoopMembersEvent>(InstanceDecoder.Decode(new(186, 3, writer.Build())));
        Assert.Equal((uint?)0, members.HostId);
        Assert.Equal((byte)3, members.Capacity);
        Assert.Equal(new uint[] { uint.MaxValue, uint.MaxValue }, members.Members.Select(member => member.RoleId));
        Assert.True(members.Created && members.Joined && members.Standby);
        Assert.All(members.Members, member => Assert.Equal(new CoopInstanceMember(uint.MaxValue, 255, 1, 2, 3, 4), member));
        var empty = Assert.IsType<CoopMembersEvent>(InstanceDecoder.Decode(new(186, 3, new byte[8])));
        Assert.Null(empty.HostId);
        Assert.Empty(empty.Members);
    }

    [Fact]
    public void PlayerMatchKeepsFirstTeamThenSecondTeamOrderIncludingDuplicatesAndZero()
    {
        var writer = new PacketWriter().U8(18).U8(3);
        foreach (var roleId in new uint[] { 7, 0, 7, 3, uint.MaxValue, 1 }) writer.U32(roleId);
        var match = Assert.IsType<CoopMatchEvent>(InstanceDecoder.Decode(new(186, 2, writer.Build())));
        Assert.Equal((byte)3, match.OpponentCount);
        Assert.Equal(new uint[] { 7, 0, 7, 3, uint.MaxValue, 1 }, match.RosterRoleIds);
    }

    [Fact]
    public void BooleanComparisonsAreNotGeneralizedAcrossFields()
    {
        for (var flag = 0; flag <= 255; flag++)
        {
            var room = Assert.IsType<MainRoomListEvent>(InstanceDecoder.Decode(new(85, 1,
                new byte[] { 1, 0, 0, 0, 0, 0, (byte)flag, 0, 0 }))).Rooms[0];
            Assert.Equal(flag == 1, room.Public);
            var defeated = Assert.IsType<MainObjectiveDefeatedEvent>(InstanceDecoder.Decode(new(85, 10,
                new byte[] { 2, (byte)flag, 0 })));
            Assert.Equal(flag == 1, defeated.Defeated);
            var standby = Assert.IsType<CoopStandbyEvent>(InstanceDecoder.Decode(new(186, 20, new byte[] { (byte)flag })));
            Assert.Equal(flag != 0, standby.Standby);
        }
        foreach (var value in new uint[] { 0, 1, 2, 256, uint.MaxValue })
        {
            var payload = new PacketWriter().U8(1).U32(2).U32(3).U32(value).Build();
            Assert.Equal(value == 1, Assert.IsType<MainMemberLeftEvent>(InstanceDecoder.Decode(new(85, 12, payload))).Kicked);
        }
    }

    [Fact]
    public void EventsOwnImmutableSnapshotsAndEmptyRewardsMakeNoSuccessClaim()
    {
        var bytes = new PacketWriter().U8(5).U8(2).U32(4).U32(9).Build();
        var first = Assert.IsType<MainObjectiveRolesEvent>(InstanceDecoder.Decode(new(85, 10, bytes)));
        Array.Fill(bytes, (byte)0);
        Assert.Equal(new uint[] { 4, 9 }, first.RoleIds);
        Assert.Throws<NotSupportedException>(() => ((IList<uint>)first.RoleIds)[0] = 42);
        var changed = first with { RoleIds = ImmutableArray.Create<uint>(99) };
        Assert.Equal((uint)4, first.RoleIds[0]);
        Assert.Equal((uint)99, changed.RoleIds[0]);
        var rooms = Assert.IsType<MainRoomListEvent>(InstanceDecoder.Decode(new(85, 1, new byte[] { 0 })));
        Assert.Throws<NotSupportedException>(() => ((IList<MainInstanceRoom>)rooms.Rooms).Add(new(1, "", 0, "", false, 0)));
        var reward = Assert.IsType<CoopRewardReceiptEvent>(InstanceDecoder.Decode(new(186, 10)));
        Assert.Empty(reward.Awards);
        Assert.Equal("instance_reward_receipt", reward.Type);
        Assert.Equal("coop", reward.Mode);
    }

    private static Packet ReadPacket(JsonElement sample) => new(sample.GetProperty("main").GetInt32(),
        sample.GetProperty("sub").GetInt32(), Convert.FromHexString(sample.GetProperty("hex").GetString()!));
}
