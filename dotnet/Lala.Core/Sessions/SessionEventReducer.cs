using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions;

/// <summary>Confirmed S26 evidence. Ready alone does not imply reliable or spendable funds.</summary>
public sealed record SessionGoldSnapshot
{
    public bool Ready { get; init; }
    public bool Reliable { get; init; }
    public uint? Amount { get; init; }
    public BigInteger Revision { get; init; }
    public string? Source { get; init; }
}

public sealed record SessionEventFlowSnapshot
{
    public bool Blocked { get; init; }
    public bool AwaitingResponse { get; init; }
    public string? LastSource { get; init; }
    public BigInteger RequestsSent { get; init; }
    internal BigInteger? PermissionPacket { get; init; }
    internal bool PermissionTracked { get; init; }
}

/// <summary>Observed dialogue state only. Continue/choice states never authorize a command.</summary>
public sealed record SessionNpcDialogueSnapshot
{
    public bool Active { get; init; }
    public string Phase { get; init; } = "idle";
    public bool ChoiceContinuationPending { get; init; }
    public ImmutableArray<ushort> History { get; init; } = [];
    public BigInteger? EffectPacket { get; init; }
    public byte? EffectType { get; init; }
    public ushort? TextId { get; init; }
    public ushort? OptionIndex { get; init; }
    public NpcEffect? LastEffect { get; init; }
    public string? Reason { get; init; }
    // Caller-supplied interaction identity survives event updates, without implying verification.
    public ushort? Scene { get; init; }
    public uint? NpcId { get; init; }
    public ushort? NpcIndex { get; init; }
    public byte? SelectedChoice { get; init; }
}

/// <summary>
/// Immutable projection of only the fields used by state_session_events.py, not a complete
/// Python State or a transport session. PacketCount is supplied by the caller; this reducer
/// does not increment it. Collection inputs must be immutable, including nested attributes.
/// Absent optional Python fields are represented by null, empty history, or false pending.
/// </summary>
public sealed record SessionEventSnapshot
{
    internal Lala.Core.Gameplay.PostBattleState PostBattle {get;init;}=new();
    public string Phase { get; init; } = "disconnected";
    public ImmutableArray<RoleSnapshot> Roles { get; init; } = [];
    public SessionGoldSnapshot Gold { get; init; } = new();
    public SessionEventFlowSnapshot EventFlow { get; init; } = new();
    public SessionNpcDialogueSnapshot NpcDialogue { get; init; } = new();
    public bool InitialDataComplete { get; init; }
    public BigInteger PacketCount { get; init; }
    public BigInteger UnimplementedCount { get; init; }
    public ImmutableDictionary<string, ImmutableDictionary<string, long>> Attributes { get; init; } =
        ImmutableDictionary<string, ImmutableDictionary<string, long>>.Empty;
}

/// <summary>
/// Pure offline port of wlre/core/state_session_events.py using already-decoded ServerEvents.
/// Returns a new snapshot for handled changes, preserving every prior snapshot. Unrelated
/// events (including explicitly unsupported decoders) are no-ops. This is neither AccountSession
/// nor command authorization, and performs no I/O, sends, credential retention or lifecycle work.
/// </summary>
public static class SessionEventReducer
{
    public static SessionEventSnapshot Apply(SessionEventSnapshot state, ServerEvent observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation switch
        {
            LoginResultEvent login => state with { Phase = login.Result == 0 ? "authenticated" : "login_failed" },
            ServerLayoutEvent { Event: RoleListAvailableEvent roles } => state with
            {
                Phase = "role_selection", Roles = roles.Roles.IsDefault ? [] : roles.Roles, Gold = new()
            },
            GoldSnapshotEvent gold => state with
            {
                Gold = new() { Ready = true, Reliable = true, Amount = gold.Amount,
                    Revision = state.Gold.Revision + 1, Source = "S26-4" }
            },
            GoldDeltaEvent delta => ApplyGoldDelta(state, delta),
            GoldLimitEvent => state with { Gold = state.Gold with { Reliable = false, Source = "S26-3 金幣上限未知" } },
            MovementStopEvent stop => state with
            {
                EventFlow = state.EventFlow with { Blocked = true, LastSource = $"S6-2 kind={stop.Kind}" }
            },
            NpcEffectEvent effect => ApplyActive(state, effect.Sub, effect.NpcEffect),
            EventActiveEvent active => ApplyActive(state, active.Sub, null),
            EventContinuePermissionEvent permission => state with
            {
                EventFlow = state.EventFlow with { Blocked = true, AwaitingResponse = false, LastSource = $"S20-{permission.Sub}", PermissionPacket=state.PacketCount,PermissionTracked=true },
                NpcDialogue = state.NpcDialogue.Active && state.NpcDialogue.Phase is "requesting" or "awaiting_reply" or "awaiting_choice"
                    ? state.NpcDialogue with { Phase = "continue" } : state.NpcDialogue
            },
            EventEndEvent => state with
            {
                EventFlow = state.EventFlow with { Blocked = false, AwaitingResponse = false, LastSource = "S20-8" },
                NpcDialogue = state.NpcDialogue.Active
                    ? state.NpcDialogue with { Active = false, Phase = "ended", ChoiceContinuationPending = false } : state.NpcDialogue
            },
            EventRejectedEvent rejected when state.NpcDialogue.Active => state with
            {
                EventFlow = state.EventFlow with { Blocked = false, AwaitingResponse = false, LastSource = "S20-74" },
                NpcDialogue = state.NpcDialogue with { Active = false, Phase = "rejected", ChoiceContinuationPending = false, Reason = rejected.Reason }
            },
            InitialDataCompleteEvent => state with { InitialDataComplete = true },
            AttributeSetEvent attribute => ApplyAttribute(state, attribute),
            UnimplementedServerEvent => state with { UnimplementedCount = state.UnimplementedCount + 1 },
            _ => state
        };
    }

    private static SessionEventSnapshot ApplyGoldDelta(SessionEventSnapshot state, GoldDeltaEvent observation)
    {
        var gold = state.Gold;
        if (!gold.Ready || !gold.Reliable || gold.Amount is not { } amount)
            return state with { Gold = gold with { Ready = false, Reliable = false, Amount = null, Source = "S26 增減早於初始化" } };
        // Delta is signed 64-bit in the public event model. Widen before adding so even
        // synthetic Int64 extremes cannot wrap into a seemingly reliable UInt32 balance.
        Int128 value = (Int128)amount + observation.Delta;
        return value < 0 || value > uint.MaxValue
            ? state with { Gold = gold with { Reliable = false, Amount = null, Source = "S26 金幣增減溢位／不足" } }
            : state with { Gold = gold with { Amount = (uint)value, Revision = gold.Revision + 1, Source = $"S26-{observation.Sub}" } };
    }

    private static SessionEventSnapshot ApplyActive(SessionEventSnapshot state, byte sub, NpcEffect? effect)
    {
        var dialogue = state.NpcDialogue with { ChoiceContinuationPending = false };
        if (effect is not null)
        {
            if (dialogue.Active)
            {
                var history = dialogue.History.IsDefault ? ImmutableArray<ushort>.Empty : dialogue.History;
                if (effect.EffectType == 1)
                {
                    history = history.Add(effect.MeanNumber);
                    if (history.Length > 50) history = history.RemoveRange(0, history.Length - 50);
                }
                dialogue = dialogue with
                {
                    History = history, EffectPacket = state.PacketCount,
                    Phase = effect.EffectType switch { 1 => "talk", 6 => "choice_unavailable", _ => "effect_unavailable" },
                    EffectType = effect.EffectType,
                    TextId = effect.EffectType == 1 ? effect.MeanNumber : null,
                    OptionIndex = effect.EffectType == 6 ? effect.MeanNumber : null
                };
            }
            else dialogue = dialogue with { LastEffect = effect };
        }
        else if (dialogue.Active) dialogue = dialogue with { Phase = "effect_unavailable" };
        return state with
        {
            NpcDialogue = dialogue,
            EventFlow = state.EventFlow with { Blocked = true, AwaitingResponse = false, LastSource = $"S20-{sub}（事件處理尚未完成）",PermissionPacket=null,PermissionTracked=true }
        };
    }

    private static SessionEventSnapshot ApplyAttribute(SessionEventSnapshot state, AttributeSetEvent observation)
    {
        var values = state.Attributes.GetValueOrDefault(observation.Entity) ?? ImmutableDictionary<string, long>.Empty;
        string key = string.Create(CultureInfo.InvariantCulture, $"{observation.Kind}:{observation.Parameter}");
        return state with { Attributes = state.Attributes.SetItem(observation.Entity, values.SetItem(key, observation.Value)) };
    }
}
