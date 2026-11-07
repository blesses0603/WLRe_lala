using System.Collections.Frozen;
using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Decoded social data, never authorization to send or publish. Diagnostic formatting
/// is metadata-only; consumers must deliberately select content fields for display.</summary>
public abstract record SocialPacketEvent(byte Main, byte Sub) : SocialEvent(Main, Sub)
{
    public sealed override string ToString() => $"{Type} (S{Main}-{Sub})";
}

public sealed record ChatResultEvent(byte Result, string Text) : SocialPacketEvent(2, 13)
{
    public override string Type => "chat_result";
}
public sealed record ChatNoticeEvent(byte Sub, string Text, uint? RoleId = null) : SocialPacketEvent(2, Sub)
{
    public override string Type => "chat_notice";
}
public sealed record ChatProfileEvent(byte Sub, uint RoleId, string Name, bool Online) : SocialPacketEvent(2, Sub)
{
    public override string Type => "chat_profile";
}
public sealed record ChatAnnouncementEvent(string Text, uint AnnouncementIndex) : SocialPacketEvent(2, 0)
{
    public override string Type => "chat_message";
    public string Channel => "系統";
    public uint RoleId => 0;
}
public sealed record ChatMessageEvent(byte Sub, string Channel, uint RoleId,
    ImmutableArray<ItemSave> Items, string Text, uint ReplyId, uint? TargetId = null,
    ushort? ServerId = null, string? Name = null, ushort? ReplyServer = null,
    string? ReplyText = null, bool? ReplyAt = null, ImmutableArray<ushort>? ReplyItems = null)
    : SocialPacketEvent(2, Sub)
{
    public override string Type => "chat_message";
}

public sealed record GuildMember(uint RoleId, string Name)
{
    public override string ToString() => nameof(GuildMember);
}
public sealed record GuildRosterEvent(string Name, string Chief, uint Serial,
    FrozenDictionary<uint, GuildMember> Members, byte Level) : SocialPacketEvent(39, 2)
{
    public override string Type => "guild_roster";
}
public sealed record GuildMemberProfileEvent(uint RoleId, string Name) : SocialPacketEvent(39, 60)
{
    public override string Type => "guild_member_profile";
}
public sealed record GuildMemberRemovedEvent(uint RoleId) : SocialPacketEvent(39, 6)
{
    public override string Type => "guild_member_removed";
}
public sealed record GuildMemberAddedEvent(uint RoleId) : SocialPacketEvent(39, 8)
{
    public override string Type => "guild_member_added";
}
public sealed record GuildLeaveResultEvent(byte Result, uint RoleId) : SocialPacketEvent(39, 7)
{
    public override string Type => "guild_leave_result";
}
public sealed record GuildDisbandResultEvent(byte Result) : SocialPacketEvent(39, 10)
{
    public override string Type => "guild_disband_result";
}

public sealed record GuildSignStateEvent(byte State) : SocialPacketEvent(39, 85)
{
    public override string Type => "guild_sign_state";
}
public sealed record GuildSignResultEvent(byte Result) : SocialPacketEvent(39, 86)
{
    public override string Type => "guild_sign_result";
}
public sealed record GuildDonateStateEvent(byte Remaining, bool Allow) : SocialPacketEvent(39, 87)
{
    public override string Type => "guild_donate_state";
}
public sealed record GuildActionErrorEvent(byte Code) : SocialPacketEvent(39, 15)
{
    public override string Type => "guild_action_error";
}
public sealed record UiSellNoticeEvent() : SocialPacketEvent(10, 5)
{
    public override string Type => "ui_sell_notice";
}
public sealed record UiSellUpdateEvent(byte Index, byte Count) : SocialPacketEvent(10, 5)
{
    public override string Type => "ui_sell_update";
}
public sealed record UiSellSnapshotEvent(FrozenDictionary<byte, byte> Counts) : SocialPacketEvent(10, 5)
{
    public override string Type => "ui_sell_snapshot";
}
public sealed record UiSellDayResetEvent() : SocialPacketEvent(10, 5)
{
    public override string Type => "ui_sell_day_reset";
}
