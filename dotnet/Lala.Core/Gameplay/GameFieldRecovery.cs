using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

public sealed record FieldRecoverySettings
{
    public bool Enabled { get; init; } = true;
    public ImmutableArray<ushort> Items { get; init; } = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
    public string Storage { get; init; } = "off";
    public bool OtherItems { get; init; } = true;
    public int PlayerPercent { get; init; } = 60;
    public int PartnerPercent { get; init; } = 60;
    internal void Validate()
    {
        if (Items.IsDefault || Items.Length != 10 || Storage is not ("off" or "first" or "after") || PlayerPercent is < 0 or > 100 || PartnerPercent is < 0 or > 100)
            throw new ProtocolException("野外補給設定無效。");
    }
}

/// <summary>Display-only eligible backpack choices; not a reservation or send permission.</summary>
public sealed record FieldRecoveryItem(ushort ItemId, int Count, long Hp, long Sp);
public static class FieldRecoveryPlanning
{
    internal static void ValidateItems(GameAutomationSettings settings, OfflineRuntimeCandidate catalogs)
    {
        var catalog = ManualGameCommands.ResourceCatalog(catalogs);
        foreach (var (resource, config) in new[] { ("hp", settings.HpRecovery), ("sp", settings.SpRecovery) })
            foreach (ushort item in config.Items.Where(id => id != 0))
                if (CombatResourceKnowledge.HealEffects(item, catalog).GetValueOrDefault(resource) <= 0)
                    throw new ProtocolException("指定的 " + resource.ToUpperInvariant() + " 補品效果尚未核對，未套用自動功能。");
    }
    public static ImmutableArray<FieldRecoveryItem> AvailableItems(ServiceStateSnapshot state, OfflineRuntimeCandidate catalogs, string resource)
    {
        if (resource is not ("hp" or "sp")) throw new ArgumentException("Unknown recovery resource.", nameof(resource));
        if (!state.Bag.Ready || !state.Bag.Reliable) return [];
        var catalog = ManualGameCommands.ResourceCatalog(catalogs);
        return [..state.Bag.Items.Values.Where(i => MaintenanceKnowledge.SlotAvailable(state.Bag, i.Index) && state.Bag.AlchemySlots?.Contains(i.Index) != true)
            .GroupBy(i => i.ItemId).OrderBy(g => g.Key).Select(g =>
            {
                var effects = CombatResourceKnowledge.HealEffects(g.Key, catalog);
                return new FieldRecoveryItem(g.Key, g.Sum(i => i.Count), effects.GetValueOrDefault("hp"), effects.GetValueOrDefault("sp"));
            }).Where(i => (resource == "hp" ? i.Hp : i.Sp) > 0 && !catalog.Items[i.ItemId].Attributes.Any(a => a.Kind is 25 or 26 && a.Value is not (0 or 100) && a.Value < 100))];
    }

    internal static GameAction? Next(ServiceStateSnapshot state, OfflineRuntimeCandidate catalogs, GameAutomationSettings settings)
    {
        if (!settings.FieldHeal || state.Player is null || state.Local.Battle.Active == true || state.Local.Session.EventFlow.Blocked ||state.Local.Session.PostBattle.Pending|| state.Activities.Count != 0) return null;
        var catalog = ManualGameCommands.ResourceCatalog(catalogs);
        var field = CombatResourceKnowledge.FieldContext(state.PlayerKnowledge, state.Companions, state.Player, catalog);
        var context = new CombatResourceActionContext { Player = state.PlayerKnowledge, Companions = state.Companions, LocalRoleId = state.Player.RoleId,
            Units = [..field.Units.Select(u => new CombatResourceBattleEntry(BattleCommandPlanner.Slot(u), u))], Inventory = state.Bag, Catalog = catalog };
        foreach (var unit in field.Units)
        {
            if (unit.Hp is not > 0 || unit.Pid is not { } pid || unit.NpcIndex is not >= 0 or > 255) continue;
            foreach (var resource in new[] { "hp", "sp" })
            {
                var config = resource == "hp" ? settings.HpRecovery : settings.SpRecovery;
                if (!config.Enabled && config.Storage != "first") continue;
                int percent = unit.NpcIndex == 0 ? config.PlayerPercent : config.PartnerPercent;
                if (!unit.Stats.TryGetValue(resource, out long current) || !unit.Stats.TryGetValue("max_" + resource, out long maximum) || maximum <= 0 || (BigInteger)current * 100 >= (BigInteger)maximum * percent) continue;
                GameAction? Storage()
                {
                    var value = state.Recovery.Resources.GetValueOrDefault(resource)?.Value ?? throw new ProtocolException(resource.ToUpperInvariant() + " 儲存槽尚未同步，已暫停補給及徘徊。");
                    int amount = (int)BigInteger.Min(BigInteger.Min(value, ushort.MaxValue), (BigInteger)maximum - current);
                    return amount > 0 ? new("field_storage", resource, pid, unit.NpcIndex.Value, amount, Scene: state.Player.Scene) : null;
                }
                GameAction? Food(ushort? item)
                {
                    var candidate = CombatResourceActionCandidates.Food(context, field.Actor, resource, item, BattleCommandPlanner.Slot(unit), true);
                    return candidate.Success ? new("field_item", resource, candidate.Intent!.ItemId!.Value, candidate.Intent.BagIndex!.Value, unit.NpcIndex.Value,
                        Scene: state.Player.Scene, RecipientId: pid) : null;
                }
                if (config.Storage == "first" && Storage() is { } first) return first;
                if (config.Enabled)
                {
                    foreach (ushort item in config.Items.Where(id => id != 0)) if (Food(item) is { } food) return food;
                    if (config.Storage == "after" && Storage() is { } after) return after;
                    if (config.OtherItems && Food(null) is { } other) return other;
                }
                throw new ProtocolException(resource.ToUpperInvariant() + " 補給不足，已暫停補給及徘徊；請補充指定物品或儲存槽。");
            }
        }
        return null;
    }
}

internal static partial class ManualGameCommands
{
    private static bool FieldRecipientRestored(ServiceStateSnapshot next, CombatResourceCatalog catalog, uint owner, uint? recipient, int npcIndex, string resource, long original) =>
        next.Player?.RoleId == owner && next.Local.Battle.Active != true && CombatResourceKnowledge.FieldContext(next.PlayerKnowledge, next.Companions, next.Player, catalog).Units
            .Any(u => u.NpcIndex == npcIndex && u.Pid == recipient && u.Hp > 0 && u.Stats.TryGetValue(resource, out long value) && value > original);

    private static GameActionPlan FieldStorage(GameAction action, ServiceStateSnapshot state, OfflineRuntimeCandidate catalogs)
    {
        Require(action.Operation is "hp" or "sp" && action.Index is >= 0 and <= 255 && action.Count is >= 1 and <= 65535, "儲存槽補給參數無效。");
        string resource = action.Operation;
        var catalog = ResourceCatalog(catalogs);
        var field = CombatResourceKnowledge.FieldContext(state.PlayerKnowledge, state.Companions, state.Player, catalog);
        var unit = field.Units.SingleOrDefault(u => u.NpcIndex == action.Index && u.Pid == action.Target);
        Require(unit is not null && unit.Hp > 0 && unit.Stats.ContainsKey(resource) && unit.Stats.GetValueOrDefault("max_" + resource) > unit.Stats[resource], "補給對象或 HP／SP 尚未確認。");
        var before = state.Recovery.Resources.GetValueOrDefault(resource);
        Require(before?.Value is { } balance && balance >= action.Count && action.Count <= (BigInteger)unit.Stats["max_" + resource] - unit.Stats[resource], "儲存槽數量不足、尚未同步或超過缺少量。");
        bool used = false;
        bool Consumed(ServiceStateSnapshot next) => used && next.Recovery.Resources.GetValueOrDefault(resource)?.Value is { } value &&
            (value == before.Value - action.Count || value == before.Value);
        return new(new(23, 147, new PacketWriter().U8(resource == "hp" ? 3 : 4).U8(1).U8(action.Index).U16(action.Count).Build()), "field_supply", "使用藥水儲存槽",
            s => s, next => Consumed(next) && FieldRecipientRestored(next, catalog, state.Player!.RoleId, unit.Pid, action.Index, resource, unit.Stats[resource]),
            next =>
            {
                Require(Consumed(next) && FieldRecipientRestored(next, catalog, state.Player!.RoleId, unit.Pid, action.Index, resource, unit.Stats[resource]), "補給完成前對象或餘額已改變。");
                var current = next.Recovery.Resources.GetValueOrDefault(resource);
                if (current?.Value is not { } balance) throw new ProtocolException("儲存槽回覆不完整。");
                // The matching S23-208 used receipt authorizes one debit. An already
                // received absolute/debit balance must never be debited again.
                if (balance == before.Value - action.Count) return next;
                if (!used || balance != before.Value) throw new ProtocolException("儲存槽餘額變動未能關聯，停止接續。");
                return CommandState.With(next, recovery: next.Recovery with { Resources = next.Recovery.Resources.SetItem(resource, new(balance - action.Count, current.Revision + 1)) });
            })
        {
            ObserveReceipt = receipt =>
            {
                if (receipt.Type == "potion_used" && receipt.Resource == resource && !receipt.Targets.IsDefault && receipt.Targets.Contains((byte)action.Index)) used = true;
            }
        };
    }
}
