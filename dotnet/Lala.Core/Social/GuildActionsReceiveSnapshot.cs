using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Sessions;

namespace Lala.Core.Social;

/// <summary>Opaque observed runtime token from current_catalog_token. Neither the attempted
/// flag nor an identity string establishes provenance or permission to use a catalog.</summary>
public sealed record GuildActionsCatalogToken(bool Attempted, string? IdentityKey)
{
    public override string ToString() => nameof(GuildActionsCatalogToken);
}

/// <summary>Imported evidence of a previously selected quote, never a new quote or authority
/// to reserve/spend gold. Count is not a byte: the expected acknowledgement can be 256.</summary>
public sealed record GuildDonationQuote(BigInteger Price, byte PriceKind, ushort SellId,
    byte SaveIndex, int Count, byte? ItemIndex = null)
{
    public override string ToString() => nameof(GuildDonationQuote);
}

/// <summary>Caller-supplied evidence only. No API here starts an action, constructs a request,
/// reserves funds, retries a request or infers missing pending evidence from a receipt.</summary>
public abstract record GuildActionPending(uint Role, uint Guild, GuildActionsCatalogToken? Token,
    BigInteger Epoch, double Due)
{
    public sealed override string ToString() => nameof(GuildActionPending);
}
public sealed record GuildSignPending(uint Role, uint Guild, GuildActionsCatalogToken? Token,
    BigInteger Epoch, double Due, bool SignAck = false) : GuildActionPending(Role, Guild, Token, Epoch, Due);
public sealed record GuildDonationPending(uint Role, uint Guild, GuildActionsCatalogToken? Token,
    BigInteger Epoch, double Due, GuildDonationQuote Quote, byte BeforeRemaining, uint GoldBefore,
    bool GoldAck = false, bool SellAck = false, bool RemainingAck = false)
    : GuildActionPending(Role, Guild, Token, Epoch, Due);

/// <summary>Immutable projection of social/guild_actions.py defaults and receive state.
/// Enabled, Allow, readiness, prices and acknowledgements describe source observations,
/// never authorization. Monetary values/epochs retain Python integer arithmetic. Only an
/// explicit S10-5 day reset clears budgets; a sign-state transition cannot infer a new day.</summary>
public sealed record GuildActionsReceiveSnapshot
{
    public static GuildActionsReceiveSnapshot Empty { get; } = new();
    public bool SignEnabled { get; init; } = true;
    public bool DonateEnabled { get; init; } = true;
    public ushort SellId { get; init; } = 8;
    public int Target { get; init; } = 3;
    public BigInteger Budget { get; init; } = 450;
    public BigInteger SettingsRevision { get; init; }
    public BigInteger Reserved { get; init; }
    public BigInteger Confirmed { get; init; }
    public GuildActionPending? Pending { get; init; }
    public bool Uncertain { get; init; }
    public uint? Role { get; init; }
    public uint? Guild { get; init; }
    public byte? SignState { get; init; }
    public byte? Remaining { get; init; }
    public bool Allow { get; init; }
    public bool SignAttempted { get; init; }
    public bool CountsReady { get; init; }
    public ImmutableDictionary<byte, byte> Counts { get; init; } = ImmutableDictionary<byte, byte>.Empty;
    public BigInteger Epoch { get; init; }
    public GuildActionsCatalogToken? CatalogToken { get; init; }
    public bool CatalogReady { get; init; }
    public BigInteger? Price { get; init; }
    public int? Donated { get; init; }
    public string Status { get; init; } = "等待組織成員、簽到與捐獻狀態同步";
    public override string ToString() => nameof(GuildActionsReceiveSnapshot);
}

/// <summary>Explicit post-observer/post-local context, in State.apply's source order:
/// apply_guild runs with the old player; dispatch_local then updates player/gold; only then
/// apply_actions reads these values. The reducer does not run or own those other domains.</summary>
public sealed record GuildActionsReceiveContext(uint? PlayerRoleId, GuildEventSnapshot Guild,
    SessionGoldSnapshot Gold)
{
    public bool ValidMember => Guild.Ready && Guild.Serial is not (null or 0) &&
        PlayerRoleId is { } role && Guild.Members.ContainsKey(role);
    public override string ToString() => nameof(GuildActionsReceiveContext);
}
