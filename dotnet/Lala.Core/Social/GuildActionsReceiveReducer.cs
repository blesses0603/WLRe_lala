using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Pure receive-only port of guild_actions.defaults/apply_actions/reset_day.
/// Decode completely before applying. Context MUST be the already reduced guild and
/// post-local player/gold, unlike observers earlier in State.apply. Late/duplicate packets
/// retain source behavior; unbound S39 observations are discarded, not buffered. Receipt
/// acknowledgements do not complete pending actions here. No scheduler, lifecycle, catalog
/// lookup, planner, request construction, reservation, spending, sending or retry exists.</summary>
public static class GuildActionsReceiveReducer
{
    public static GuildActionsReceiveSnapshot Apply(GuildActionsReceiveSnapshot state,
        ServerEvent observation, GuildActionsReceiveContext afterLocal)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(afterLocal);
        switch (observation)
        {
            case ServerLayoutEvent { Event: RoleListAvailableEvent }:
                return GuildActionsReceiveSnapshot.Empty;
            case ServerLayoutEvent { Event: WorldPlayerEvent world }:
                return (state.Role is { } role && role != world.Player.RoleId
                    ? GuildActionsReceiveSnapshot.Empty : state) with { Role = world.Player.RoleId };
            case ServerSocialEvent social:
                return Apply(state, social.Event, afterLocal);
            case GoldDeltaEvent or GoldSnapshotEvent or GoldLimitEvent
                when state.Pending is GuildDonationPending pending:
                return observation is GoldDeltaEvent delta && delta.Delta == -pending.Quote.Price &&
                    !pending.GoldAck && afterLocal.Gold.Reliable &&
                    afterLocal.Gold.Amount is { } amount && amount == pending.GoldBefore - pending.Quote.Price
                    ? state with { Pending = pending with { GoldAck = true } }
                    : StopUncertain(state, "捐獻期間金幣異動無法唯一確認");
            default:
                return state;
        }
    }

    public static GuildActionsReceiveSnapshot Apply(GuildActionsReceiveSnapshot state,
        SocialEvent observation, GuildActionsReceiveContext afterLocal)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(afterLocal);
        if (observation is GuildRosterEvent)
        {
            if (!afterLocal.ValidMember)
            {
                if (state.Pending is not null) state = StopUncertain(state, "組織成員身分已失效");
                state = state with { Guild = null, SignState = null, Remaining = null, Allow = false };
            }
            else if (state.Guild is { } guild && guild != afterLocal.Guild.Serial)
            {
                if (state.Pending is not null) state = StopUncertain(state, "組織身分變動");
                // Python deliberately overwrites the uncertainty status here, but not its latch.
                state = state with { Guild = afterLocal.Guild.Serial, SignState = null, Remaining = null,
                    Allow = false, DonateEnabled = false, SignAttempted = false,
                    Status = "已變更組織，捐獻停用，等待新狀態" };
            }
            else state = state with { Guild = afterLocal.Guild.Serial, Role = afterLocal.PlayerRoleId };
        }
        if (observation is GuildLeaveResultEvent or GuildDisbandResultEvent or GuildMemberRemovedEvent &&
            !afterLocal.ValidMember)
        {
            if (state.Pending is not null) state = StopUncertain(state, "已離開組織");
            state = state with { Guild = null, SignState = null, Remaining = null, Allow = false, DonateEnabled = false };
        }
        switch (observation)
        {
            case UiSellSnapshotEvent snapshot:
                state = state with { Counts = snapshot.Counts.ToImmutableDictionary(), CountsReady = true };
                break;
            case UiSellUpdateEvent update:
                if (update.Index != 0) state = state with { Counts = state.Counts.SetItem(update.Index, update.Count) };
                if (state.Pending is GuildDonationPending donation && update.Index != 0 && donation.Quote.SaveIndex == update.Index)
                {
                    if (update.Count == donation.Quote.Count + 1)
                        state = state with { Pending = donation with { SellAck = true } };
                    else if (update.Count != donation.Quote.Count)
                        state = StopUncertain(state, "捐獻消費次數變動不符");
                }
                break;
            case UiSellDayResetEvent:
                state = ResetDay(state) with { Counts = Enumerable.Range(1, 100).ToImmutableDictionary(i => (byte)i, _ => (byte)0), CountsReady = true };
                break;
        }
        if (observation.Type.StartsWith("guild_", StringComparison.Ordinal) &&
            (!afterLocal.ValidMember || state.Guild != afterLocal.Guild.Serial)) return state;
        switch (observation)
        {
            case GuildSignStateEvent sign:
                if (state.SignState == 2 && sign.State == 1)
                    state = state.Pending is not null ? StopUncertain(state, "操作期間簽到狀態重置")
                        : state with { SignAttempted = false };
                return state with { SignState = sign.State };
            case GuildSignResultEvent result when state.Pending is GuildSignPending sign:
                return result.Result switch
                {
                    0 => state with { Pending = sign with { SignAck = true } },
                    1 => state with { Pending = null, SignState = 3, Status = "新加入組織，今日不可簽到" },
                    2 => state with { Pending = null, SignState = 2, Status = "今日已簽到" },
                    _ => StopUncertain(state, "組織簽到結果未支援")
                };
            case GuildDonateStateEvent donated:
                state = state with { Remaining = donated.Remaining, Allow = donated.Allow };
                if (state.Pending is not GuildDonationPending pending) return state;
                if (pending.RemainingAck && donated.Remaining != pending.BeforeRemaining - 1)
                    return StopUncertain(state, "已確認的捐獻次數又發生變動");
                if (donated.Remaining == pending.BeforeRemaining - 1)
                    return state with { Pending = pending with { RemainingAck = true } };
                return donated.Remaining != pending.BeforeRemaining
                    ? StopUncertain(state, "捐獻剩餘次數變動不符") : state;
            case GuildActionErrorEvent error when state.Pending is not null:
                return StopUncertain(state, "伺服器拒絕組織操作（代碼 " + error.Code.ToString(CultureInfo.InvariantCulture) + "）");
            default:
                return state;
        }
    }

    private static GuildActionsReceiveSnapshot ResetDay(GuildActionsReceiveSnapshot state) => state.Pending is not null
        ? StopUncertain(state, "組織操作期間收到週期重置")
        : state with { Epoch = state.Epoch + 1, SignState = null, Remaining = null, Allow = false,
            SignAttempted = false, Reserved = 0, Confirmed = 0, Status = "新週期，等待組織簽到與捐獻狀態" };

    private static GuildActionsReceiveSnapshot StopUncertain(GuildActionsReceiveSnapshot state, string note) =>
        state with { Pending = null, Uncertain = true, Status = note + "；停止重送，請重新登入同步" };
}
