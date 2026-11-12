using System.Collections.Immutable;
using System.Collections.Frozen;
using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Social.Chat;

public sealed class ChatReceiveTests
{
    private static ServerSocialEvent Message(uint role = 7, string name = "", string text = "private-chat", byte sub = 1,
        string channel = "世界", ushort? server = null) => new(new ChatMessageEvent(sub, channel, role, [], text, 0, ServerId: server, Name: name));
    private static ServiceStateSnapshot Apply(ServiceStateCoordinator coordinator, ServerEvent value, double time = 123) =>
        coordinator.Apply(value, new(coordinator.Snapshot(), new(time)));
    private static ServerLayoutEvent World(uint role, string name) => new(new WorldPlayerEvent(new(role, 0, 101, 1, 2,
        0, 0, 0, 0, 0, 0, false, [], name, 0)));

    public static IEnumerable<object[]> Vectors() => JsonDocument.Parse(ChatPythonVectors.Json).RootElement.EnumerateArray()
        .Select(v => new object[] { v.GetProperty("name").GetString()!, v.GetRawText() });

    [Theory]
    [MemberData(nameof(Vectors))]
    public void PythonNamesReceiptBoundAndHistoricalLabelsMatch(string _, string json)
    {
        using var document = JsonDocument.Parse(json); var vector = document.RootElement;
        var coordinator = new ServiceStateCoordinator();
        foreach (var step in vector.GetProperty("steps").EnumerateArray())
        {
            uint role = step.GetProperty("role").GetUInt32(); string name = step.GetProperty("name").GetString()!;
            if (step.GetProperty("kind").GetString() == "profile") Apply(coordinator, new ServerSocialEvent(new ChatProfileEvent(18, role, name, true)));
            else
            {
                string channel = step.GetProperty("channel").GetString()!;
                ushort? server = step.GetProperty("server").ValueKind == JsonValueKind.Null ? null : step.GetProperty("server").GetUInt16();
                Apply(coordinator, Message(role, name, sub: channel == "跨服" ? (byte)(server is null ? 27 : 28) : (byte)1, channel: channel, server: server));
            }
        }
        var state = coordinator.Snapshot().Chat;
        Assert.Equal(vector.GetProperty("names").GetInt32(), state.Names.Names.Count);
        Assert.Equal(vector.GetProperty("received").GetInt32(), state.ReceivedMessageCount);
        Assert.Equal(vector.GetProperty("labels").EnumerateArray().Select(v => v.GetString()), state.Messages.Select(row => row.Name));
        Assert.Equal(vector.GetProperty("order").EnumerateArray().Select(v => new ChatNameIdentity(v[1].GetUInt32(), Scope(v[0]))), state.Names.LearnOrder);
        foreach (var query in vector.GetProperty("queries").EnumerateArray())
            Assert.Equal(query.GetProperty("label").GetString(), state.Names.Name(query.GetProperty("role").GetUInt32(), Scope(query.GetProperty("scope"))));
    }

    private static ChatNameScope Scope(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null => ChatNameScope.Local,
        JsonValueKind.String => ChatNameScope.CrossUnknown,
        _ => ChatNameScope.Server(value.GetUInt16())
    };

    [Fact]
    public void OracleSourcesHaveNotDrifted()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "WLRE_Client.py"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var source in JsonDocument.Parse(ChatPythonVectors.SourceSha256).RootElement.EnumerateObject())
        {
            var bytes = System.Text.Encoding.UTF8.GetBytes(File.ReadAllText(Path.Combine(root.FullName, source.Name)).Replace("\r\n", "\n", StringComparison.Ordinal));
            Assert.Equal(source.Value.GetString(), Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
        }
    }

    [Fact]
    public void ProfilesRefreshNamesWithoutMutatingOldMessagesAndFeedbackDoesNotClaimDelivery()
    {
        var state = new ServiceStateCoordinator();
        Apply(state, World(42, "own"));
        var first = Apply(state, Message());
        var updated = Apply(state, new ServerSocialEvent(new ChatProfileEvent(18, 7, "\tNew\n", false)));
        Assert.Equal("7", Assert.Single(first.Chat.Messages).Name);
        Assert.Equal("New", Assert.Single(updated.Chat.Messages).Name);
        Assert.Equal("\tNew\n", Assert.IsType<ChatProfileEvent>(updated.Chat.LatestProfile!.Event).Name);
        Assert.False(Assert.IsType<ChatProfileEvent>(updated.Chat.LatestProfile.Event).Online);
        Assert.Equal(42u, Assert.Single(first.Chat.Messages).Receipt.OwnRoleId);
        var result = Apply(state, new ServerSocialEvent(new ChatResultEvent(0, "receipt-only")));
        var notice = Apply(state, new ServerSocialEvent(new ChatNoticeEvent(21, "offline", 7)));
        Assert.IsType<ChatResultEvent>(result.Chat.LatestFeedback!.Event);
        Assert.IsType<ChatNoticeEvent>(notice.Chat.LatestFeedback!.Event);
        Assert.Single(notice.Chat.Messages);
        Assert.Same(updated.Chat.LatestProfile, notice.Chat.LatestProfile);
        Apply(state, World(43, "changed-own"));
        Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent([])));
        var held = state.Apply(new HeartbeatRequestEvent(), new(state.Snapshot(), new(999) { ResourceHeld = false }));
        Assert.Equal(42u, Assert.Single(held.Chat.Messages).Receipt.OwnRoleId);
        Assert.Single(held.Chat.Messages);
        Assert.False(held.IsCompleteState);
    }

    [Fact]
    public void RawNestedItemsRepliesAndAnnouncementsRemainCompleteAndImmutable()
    {
        var item = new ItemSave(1, 2, 3, 4, 0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
            [new(1, 1), new(2, 2), new(3, 3), new(4, 4)], true, 18, 19, 20);
        var message = new ChatMessageEvent(28, "跨服", 7, [item], "\nRaw text 😀", 8, 9, 0, "\tName\n", 1, "\rRaw reply", true, [2, 3]);
        var coordinator = new ServiceStateCoordinator();
        var snapshot = Apply(coordinator, new ServerSocialEvent(message)).Chat;
        var receipt = Assert.Single(snapshot.Messages);
        Assert.Equal("Name", receipt.Name);
        Assert.Same(message, receipt.Receipt.Event);
        Assert.Throws<NotSupportedException>(() => ((IList<ItemSave>)message.Items)[0] = item with { Count = 0 });
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)item.Plugins)[0] = new(0, 0));
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)message.ReplyItems!.Value)[0] = 0);
        Assert.Throws<NotSupportedException>(() => ((IList<ChatReceiveMessage>)snapshot.Messages).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ChatNameIdentity, string>)snapshot.Names.Names).Clear());
        Apply(coordinator, new ServerSocialEvent(message with { Text = "later" }));
        Assert.Equal("\nRaw text 😀", Assert.IsType<ChatMessageEvent>(snapshot.Messages[0].Receipt.Event).Text);
        var announcement = new ChatAnnouncementEvent(new string('a', ChatReceiveReducer.MaximumAnnouncementCharacters), 123);
        var after = Apply(coordinator, new ServerSocialEvent(announcement));
        Assert.Same(announcement, after.Chat.Messages[^1].Receipt.Event);
        Assert.Equal("系統", after.Chat.Messages[^1].Name);
    }

    [Fact]
    public void InvalidTypedPayloadOrPacketNeverPublishesPartialNamesOrCount()
    {
        var coordinator = new ServiceStateCoordinator();
        Apply(coordinator, Message(name: "saved")); var before = coordinator.Snapshot();
        var good = (ChatMessageEvent)Message().Event;
        var badItem = new ItemSave(1, 2, 3, 4, 0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, default, true, 18, 19, 20);
        SocialPacketEvent[] invalid = [good with { Text = new string('x', 128) }, good with { Text = "\ud800" },
            good with { Name = new string('x', 128) }, good with { ReplyText = new string('x', 128) }, good with { Items = default },
            good with { Items = [badItem] }, good with { Items = [badItem with { Plugins = [new(1, 1), new(2, 2), new(3, 3), null!] }] },
            good with { Items = ImmutableArray.CreateRange(Enumerable.Repeat(badItem, 256)) }, good with { ReplyItems = default(ImmutableArray<ushort>) },
            good with { ReplyItems = ImmutableArray.CreateRange(Enumerable.Repeat((ushort)0, 256)) }, good with { Channel = new string('x', 999) },
            new ChatAnnouncementEvent(new string('x', ChatReceiveReducer.MaximumAnnouncementCharacters + 1), 0),
            new ChatProfileEvent(18, 8, new string('x', 128), true), new ChatNoticeEvent(21, new string('x', 128))];
        foreach (var value in invalid)
        {
            Assert.Throws<ProtocolException>(() => Apply(coordinator, new ServerSocialEvent(value)));
            Assert.Same(before, coordinator.Snapshot());
        }
        Assert.Throws<ProtocolException>(() => coordinator.Apply(new Packet(2, 1, [7, 0, 0, 0, 0, 2, 1]), new(before, new(1))));
        Assert.Same(before, coordinator.Snapshot());
    }

    [Fact]
    public void PostLocalNamesUseOwnNearbyGuildEventPrecedenceAndDeterministicRoleOrder()
    {
        var coordinator = new ServiceStateCoordinator();
        var own = Apply(coordinator, World(42, "own"));
        Assert.Equal("own", own.Chat.Names.Name(42));
        Apply(coordinator, new ServerSocialEvent(new NearbyPlayerEvent(new(42, 0, 0, 1, 101, 1, 2, 0, 0, "nearby"))));
        var roster = new Dictionary<uint, GuildMember> { [42] = new(42, "guild"), [9] = new(9, "nine"), [2] = new(2, "two") };
        var guild = Apply(coordinator, new ServerSocialEvent(new GuildRosterEvent("", "", 1, roster.ToFrozenDictionary(), 1)));
        Assert.Equal("guild", guild.Chat.Names.Name(42));
        Assert.Equal(new uint[] { 2, 9, 42 }, guild.Chat.Names.LearnOrder.Select(key => key.RoleId));
        var explicitName = Apply(coordinator, Message(42, "event"));
        Assert.Equal("event", explicitName.Chat.Names.Name(42));
        Assert.Equal("event", Assert.Single(explicitName.Chat.Messages).Name);
        var unrelated = Apply(coordinator, new HeartbeatRequestEvent());
        Assert.Same(explicitName.Chat, unrelated.Chat);
        var refreshed = Apply(coordinator, Message(7));
        Assert.Equal("guild", refreshed.Chat.Names.Name(42));
        Assert.Equal("event", Assert.Single(explicitName.Chat.Messages).Name); // old publication stays immutable
        var profile = Apply(coordinator, new ServerSocialEvent(new GuildMemberProfileEvent(42, "updated-guild")));
        Assert.Equal("updated-guild", profile.Chat.Names.Name(42));
    }

    [Fact]
    public void MessageEvictionRetainsExactNewestRawRowsAndDoesNotInventMissingWhisperIdentity()
    {
        var coordinator = new ServiceStateCoordinator();
        for (int i = 0; i < 205; i++) Apply(coordinator, Message(text: i.ToString(System.Globalization.CultureInfo.InvariantCulture)));
        var bounded = coordinator.Snapshot();
        Assert.Equal(200, bounded.Chat.Messages.Length);
        Assert.Equal(5, bounded.Chat.DroppedMessageCount);
        Assert.Equal("5", Assert.IsType<ChatMessageEvent>(bounded.Chat.Messages[0].Receipt.Event).Text);
        Assert.Equal("204", Assert.IsType<ChatMessageEvent>(bounded.Chat.Messages[^1].Receipt.Event).Text);
        var unknown = coordinator.Apply(new Packet(2, 3, [7, 0, 0, 0, 255]), new(bounded, new(1)));
        Assert.IsType<ChatNoticeEvent>(unknown.Chat.LatestFeedback!.Event);
        Assert.Equal(205, unknown.Chat.ReceivedMessageCount);
        var announcement = coordinator.Apply(new Packet(2, 0, [1, 0, 0, 0, 255]), new(unknown, new(1)));
        Assert.Equal("收到系統公告（此公告文字編碼尚未確認）", Assert.IsType<ChatAnnouncementEvent>(announcement.Chat.Messages[^1].Receipt.Event).Text);
    }

    [Fact]
    public async Task EveryNewDiagnosticIsContentFreeAndHistoricalRowsCanBeReadAcrossThreads()
    {
        var coordinator = new ServiceStateCoordinator();
        var state = Apply(coordinator, Message(123456789, "private-name", "private-text", server: 12345)).Chat;
        var row = Assert.Single(state.Messages);
        var text = string.Join(" ", state, state.Names, row, row.Receipt, row.Scope, new ChatNameIdentity(123456789, row.Scope));
        foreach (string secret in new[] { "private", "123456789", "12345" }) Assert.DoesNotContain(secret, text);
        Assert.Equal("private-name", await Task.Run(() => state.Messages[0].Name));
    }
}
