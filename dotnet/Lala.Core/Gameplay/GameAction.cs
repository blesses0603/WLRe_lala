using System.Collections.Immutable;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

/// <summary>A semantic intent. Raw packets and arbitrary protocol numbers are never host inputs.</summary>
public sealed record AlchemyIngredient(byte Index, ushort ItemId, byte Count, uint Serial, byte SerialVersion);
public sealed record GameAction(string Kind, string Operation = "", uint Target = 0, int Index = 0,
    int Count = 1, int X = 0, int Y = 0, ushort Scene = 0,
    ImmutableDictionary<string, int>? Values = null, string? Key = null, Lala.Core.Battle.AutoBattleProfile? BattleProfile = null,
    ImmutableArray<AlchemyIngredient> Ingredients = default, uint? RecipientId = null, System.Numerics.BigInteger? BattleCount = null,
    uint? ItemSerial = null, byte? ItemSerialVersion = null, uint? ExpectedPrice = null);

public sealed record GameActionStatus(string Label, string Message, bool Pending = false, bool Uncertain = false);

internal sealed record GameActionPlan(Packet Packet, string Domain, string Label,
    Func<ServiceStateSnapshot, ServiceStateSnapshot> Begin,
    Func<ServiceStateSnapshot, bool> Acknowledged,
    Func<ServiceStateSnapshot, ServiceStateSnapshot>? Finish = null)
{
    internal Func<ServiceStateSnapshot, ServiceStateSnapshot>? AfterWrite { get; init; }
    internal bool AwaitAcknowledgement { get; init; } = true;
    internal Action<GameServerEvent>? ObserveReceipt { get; init; }
    internal Func<ServiceStateSnapshot, bool>? RefusalUnchanged { get; init; }
    internal bool ContinueNpcChoice { get; init; }
    internal Lala.Core.Inventory.BagItemSnapshot? BattleItem {get;init;}
}

internal static class CommandState
{
    internal static ServiceStateSnapshot With(ServiceStateSnapshot s,
        LocalStateSnapshot? local = null,
        Lala.Core.Automation.TimeCubeState? cube = null,
        Lala.Core.Automation.DailyTaskState? daily = null,
        Lala.Core.Battle.AttributeAllocationSnapshot? points = null,
        Lala.Core.World.Tent.TentReceiveSnapshot? tent = null,
        Lala.Core.Social.PartyEventSnapshot? party = null,
        Lala.Core.Battle.EfficiencySnapshot? efficiency = null,
        Lala.Core.Inventory.PotionStorageSnapshot? recovery = null,
        Lala.Core.Instances.InstanceReceiveSnapshot? instances = null,
        Lala.Core.Social.GuildActionsReceiveSnapshot? guildActions = null,
        Lala.Core.Social.Ark.ArkReceiveSnapshot? ark = null,
        Lala.Core.Inventory.BagReceiveSnapshot? bag = null) => new(
        local ?? s.Local, daily ?? s.DailyTasks, cube ?? s.TimeCube, recovery ?? s.Recovery, s.Guild,
        s.Activities, s.Storage, s.Expedition, s.Observation, s.Crafting, bag??s.Bag, s.Companions,
        party ?? s.Party, instances ?? s.Instances, tent ?? s.Tent, s.PlayerKnowledge,
        points ?? s.AttributeAllocation, s.ShopEvidence, efficiency ?? s.Efficiency,
        guildActions ?? s.GuildActions, ark ?? s.Ark, s.Chat);
}
