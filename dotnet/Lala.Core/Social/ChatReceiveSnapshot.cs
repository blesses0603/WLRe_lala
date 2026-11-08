using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;

namespace Lala.Core.Social;

public enum ChatNameScopeKind { Local, CrossUnknown, Server }

/// <summary>Numeric server zero is distinct from both local and unknown cross-server identity.</summary>
public readonly record struct ChatNameScope
{
    private ChatNameScope(ChatNameScopeKind kind, ushort? serverId) { Kind = kind; ServerId = serverId; }
    public ChatNameScopeKind Kind { get; }
    public ushort? ServerId { get; }
    public static ChatNameScope Local => default;
    public static ChatNameScope CrossUnknown => new(ChatNameScopeKind.CrossUnknown, null);
    public static ChatNameScope Server(ushort serverId) => new(ChatNameScopeKind.Server, serverId);
    public static ChatNameScope ForMessage(ChatMessageEvent message) => message.ServerId is { } server
        ? Server(server) : message.Channel == "跨服" ? CrossUnknown : Local;
    public override string ToString() => nameof(ChatNameScope);
}

public readonly record struct ChatNameIdentity(uint RoleId, ChatNameScope Scope)
{
    public override string ToString() => nameof(ChatNameIdentity);
}

/// <summary>Immutable session-only labels, oldest-to-newest learn order. Labels are observations,
/// not verified identity or address resolution. There is deliberately no send/resolve operation.</summary>
public sealed class ChatNameBook
{
    public const int MaximumNames = 4096;
    public static ChatNameBook Empty { get; } = new(ImmutableDictionary<ChatNameIdentity, string>.Empty, []);
    internal ChatNameBook(ImmutableDictionary<ChatNameIdentity, string> names, ImmutableArray<ChatNameIdentity> order)
    { Names = names; LearnOrder = order; }
    public ImmutableDictionary<ChatNameIdentity, string> Names { get; }
    public ImmutableArray<ChatNameIdentity> LearnOrder { get; }
    public string Name(uint roleId, ChatNameScope scope = default) =>
        Names.TryGetValue(new(roleId, scope), out var name) ? name : roleId.ToString(CultureInfo.InvariantCulture);
    public override string ToString() => $"ChatNameBook (count={Names.Count})";
}

/// <summary>A receipt, not a sent/delivered/read acknowledgement. Event deliberately exposes
/// full private content for a host to select for display; default diagnostics are redacted.</summary>
public sealed record ChatReceiveObservation(SocialPacketEvent Event, double ObservedAt, uint? OwnRoleId)
{
    public override string ToString() => nameof(ChatReceiveObservation);
}

public sealed record ChatReceiveMessage(ChatReceiveObservation Receipt, uint RoleId, ChatNameScope Scope, string Name)
{
    public override string ToString() => nameof(ChatReceiveMessage);
}

/// <summary>Bounded receive-only projection. Messages retain the latest 200 message/announcement
/// receipts, oldest first, including duplicates. LatestFeedback and LatestProfile each retain
/// only one observation, separately from messages. No readiness, delivery or action authority.
/// Fresh runtime attempts start empty; role/scene/catalog changes do not clear this state.</summary>
public sealed class ChatReceiveSnapshot
{
    public const int MaximumMessages = 200;
    public static ChatReceiveSnapshot Empty { get; } = new([], ChatNameBook.Empty, null, null, 0);
    internal ChatReceiveSnapshot(ImmutableArray<ChatReceiveMessage> messages, ChatNameBook names,
        ChatReceiveObservation? latestFeedback, ChatReceiveObservation? latestProfile, BigInteger receivedMessageCount)
    { Messages = messages; Names = names; LatestFeedback = latestFeedback; LatestProfile = latestProfile; ReceivedMessageCount = receivedMessageCount; }
    public ImmutableArray<ChatReceiveMessage> Messages { get; }
    public ChatNameBook Names { get; }
    public ChatReceiveObservation? LatestFeedback { get; }
    public ChatReceiveObservation? LatestProfile { get; }
    public BigInteger ReceivedMessageCount { get; }
    public BigInteger DroppedMessageCount => ReceivedMessageCount - Messages.Length;
    public override string ToString() => $"ChatReceiveSnapshot (messages={Messages.Length}, names={Names.Names.Count})";
}
