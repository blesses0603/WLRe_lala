using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static async Task<OfflineRuntimeCandidate> RecoveryCatalog()
    {
        var c = (await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var items = new Dictionary<ushort, ItemDataRow>
        {
            [20] = new(20, "HP 補品", 0, 0, 0, 0, 0, new() { Kind = 23, Attributes = [new(25, 0, 150)] }),
            [21] = new(21, "SP 補品", 0, 0, 0, 0, 0, new() { Kind = 32, Attributes = [new(26, 0, 125)] }),
            [22] = new(22, "效果未知", 0, 0, 0, 0, 0, null),
            [23] = new(23, "有負面效果", 0, 0, 0, 0, 0, new() { Kind = 23, Attributes = [new(25, 0, 150), new(26, 0, 50)] })
        };
        return new(c.EveIndexes, items, c.Talks, c.Texts, c.Recipes, c.Stages, c.Doors, c.SceneNames, c.Expedition, c.Npcs, c.SourceSha256, c.PortalObservations);
    }
    private static ItemSave RecoveryItem(byte index, ushort item = 20) => new(index, item, 3, 0, 1, 1234, null, null, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, [], false, 0, 0, null);
    private static ServiceStateSnapshot RecoveryState(long hp = 20, long sp = 100, int count = 3, uint serial = 1234, int balance = 500)
    {
        var seed = GameState();
        var item = RecoveryItem(1) with { Serial = serial };
        return new(local: seed.Local, playerKnowledge: new() { Ready = true, Stats = ImmutableDictionary<string, long>.Empty.Add("hp", hp).Add("max_hp", 100).Add("sp", sp).Add("max_sp", 100) },
            bag: new() { Ready = true, Reliable = true, Capacity = 10, Items = count == 0 ? [] : ImmutableDictionary<byte, BagItemSnapshot>.Empty.Add(1, new(item, 1, count, 0)), ItemOrder = count == 0 ? [] : [1] },
            recovery: RecoveryReducer.Apply(PotionStorageSnapshot.Empty, new PotionBalanceEvent("hp", balance)));
    }

    [Fact]
    public async Task Field_recovery_selects_verified_priorities_and_storage_order_without_mutating_state()
    {
        var c = await RecoveryCatalog(); var state = RecoveryState();
        var settings = new GameAutomationSettings { FieldHeal = true, HpRecovery = new() { Items = [20, 0, 0, 0, 0, 0, 0, 0, 0, 0], OtherItems = false, Storage = "first" } };
        Assert.Null(FieldRecoveryPlanning.Next(state, c, settings with { FieldHeal = false }));
        var storage = FieldRecoveryPlanning.Next(state, c, settings)!;
        Assert.Equal(("field_storage", 80, 0), (storage.Kind, storage.Count, storage.Index));
        Assert.Equal(state.Player!.RoleId, storage.Target);
        var food = FieldRecoveryPlanning.Next(state, c, settings with { HpRecovery = settings.HpRecovery with { Storage = "after" } })!;
        Assert.Equal(("field_item", 20u, 1, 0), (food.Kind, food.Target, food.Index, food.Count));
        Assert.Equal(state.Player.RoleId, food.RecipientId);
        Assert.Null(FieldRecoveryPlanning.Next(RecoveryState(hp: 60), c, settings)); // Threshold is strictly below.
        Assert.Null(FieldRecoveryPlanning.Next(RecoveryState(hp: 0), c, settings)); // No revival.
        var depleted = RecoveryState(count: 0);
        Assert.Equal("field_storage", FieldRecoveryPlanning.Next(depleted, c, settings with { HpRecovery = settings.HpRecovery with { Storage = "after" } })!.Kind);
        Assert.Throws<ProtocolException>(() => FieldRecoveryPlanning.Next(depleted, c, settings with { HpRecovery = settings.HpRecovery with { Storage = "off" } }));
        var unknown = CommandState.With(state, recovery: PotionStorageSnapshot.Empty);
        Assert.Throws<ProtocolException>(() => FieldRecoveryPlanning.Next(unknown, c, settings));
        var disabled = settings with { HpRecovery = settings.HpRecovery with { Enabled = false, Storage = "after" } };
        Assert.Null(FieldRecoveryPlanning.Next(state, c, disabled));
        Assert.Equal(3, state.Bag.Items[1].Count); Assert.Equal(500, state.Recovery.Resources["hp"].Value);
        Assert.Single(FieldRecoveryPlanning.AvailableItems(state, c, "hp"));
        Assert.Empty(FieldRecoveryPlanning.AvailableItems(state, c, "sp"));
    }

    [Fact]
    public async Task Field_item_requires_same_serial_target_and_real_health_increase()
    {
        var c = await RecoveryCatalog(); var state = RecoveryState();
        var action = new GameAction("field_item", "hp", 20, 1, 0, RecipientId: state.Player!.RoleId);
        var plan = ManualGameCommands.Plan(action, state, c, 10, "synthetic");
        Assert.False(plan.Acknowledged(RecoveryState(hp: 70))); // Healing alone cannot consume a bag item.
        Assert.False(plan.Acknowledged(RecoveryState(count: 2))); // Consumption alone cannot restore health.
        Assert.False(plan.Acknowledged(RecoveryState(hp: 70, count: 2, serial: 999))); // Same item ID in a replaced slot is not the source.
        Assert.True(plan.Acknowledged(RecoveryState(hp: 70, count: 2)));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { RecipientId = 999 }, state, c, 10, "synthetic"));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Operation = "unknown" }, state, c, 10, "synthetic"));
        Assert.Throws<ProtocolException>(() => plan.ObserveReceipt!(new(1, 23, 15, "item_use_result", "", Code: 4)));
    }

    [Fact]
    public async Task Field_storage_matches_resource_recipient_and_debits_once_after_confirmed_restoration()
    {
        var c = await RecoveryCatalog(); var state = RecoveryState();
        var action = new GameAction("field_storage", "hp", state.Player!.RoleId, 0, 80);
        var plan = ManualGameCommands.Plan(action, state, c, 10, "synthetic");
        Assert.Equal(new byte[] { 3, 1, 0, 80, 0 }, plan.Packet.Payload.ToArray());
        Assert.Equal((23, 147), ((int)plan.Packet.Main, (int)plan.Packet.Sub));
        Assert.False(plan.Acknowledged(RecoveryState(hp: 100, balance: 420)));
        plan.ObserveReceipt!(new(1, 23, 208, "potion_used", "", Resource: "sp", Targets: [0]));
        plan.ObserveReceipt!(new(2, 23, 208, "potion_used", "", Resource: "hp", Targets: [1]));
        Assert.False(plan.Acknowledged(RecoveryState(hp: 100)));
        plan.ObserveReceipt!(new(3, 23, 208, "potion_used", "", Resource: "hp", Targets: [0]));
        Assert.False(plan.Acknowledged(state));
        Assert.True(plan.Acknowledged(RecoveryState(hp: 100)));
        var done = plan.Finish!(RecoveryState(hp: 100));
        Assert.Equal(420, done.Recovery.Resources["hp"].Value);
        Assert.Same(done, plan.Finish(done)); // No double debit on an already-confirmed balance.
        Assert.False(plan.Acknowledged(RecoveryState(hp: 100, balance: 450)));
        Assert.False(plan.Acknowledged(RecoveryState(hp: 100, balance: 600)));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Count = 81 }, state, c, 10, "synthetic"));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action with { Target = 999 }, state, c, 10, "synthetic"));
    }

    [Fact]
    public async Task Field_recovery_tracks_active_companion_identity_and_rejects_unverified_or_reserved_supplies()
    {
        var c = await RecoveryCatalog();
        ServiceStateSnapshot Companion(long hp = 10, uint npc = 60013)
        {
            var state = RecoveryState(hp: 100);
            var data = new CompanionSnapshot(1, npc, 0, 1, (int)hp, 100, 0, 0, 0, 0, 0, null, 100, 1, null, "合成夥伴", [], [], null, 0, 0, 0, 0, null, 0);
            var companions = new CompanionReceiveSnapshot { Ready = true, ActiveNpcId = npc, CompanionOrder = [1], Companions = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty.Add(1,
                new(data, [], []) { StatOverrides = ImmutableDictionary<string, long>.Empty.Add("max_hp", 100).Add("max_sp", 100) }) };
            var projected = new ServiceStateSnapshot(companions: companions);
            return new(local: new(state.Local.Session with { Attributes = projected.Local.Session.Attributes }, state.Local.World, state.Local.Battle),
                playerKnowledge: state.PlayerKnowledge, bag: state.Bag, recovery: state.Recovery, companions: companions);
        }
        var state = Companion();
        var settings = new GameAutomationSettings { FieldHeal = true, HpRecovery = new() { OtherItems = true, PartnerPercent = 50 } };
        var action = FieldRecoveryPlanning.Next(state, c, settings)!;
        Assert.Equal(("field_item", 1, 60013u), (action.Kind, action.Count, action.RecipientId));
        var plan = ManualGameCommands.Plan(action, state, c, 10, "synthetic");
        var restored = Companion(hp: 60);
        ServiceStateSnapshot Spent(ServiceStateSnapshot s) => new(local: s.Local, playerKnowledge: s.PlayerKnowledge, companions: s.Companions, recovery: s.Recovery,
            bag: s.Bag with { Items = s.Bag.Items.SetItem(1, s.Bag.Items[1] with { Count = 2 }) });
        Assert.True(plan.Acknowledged(Spent(restored)));
        Assert.False(plan.Acknowledged(Spent(Companion(hp: 60, npc: 60014))));
        Assert.Null(FieldRecoveryPlanning.Next(Companion(hp: 0), c, settings));
        var reserved = new ServiceStateSnapshot(local: state.Local, playerKnowledge: state.PlayerKnowledge, companions: state.Companions,
            bag: state.Bag with { Reserved = state.Bag.Reserved.SetItem(1, 3) });
        Assert.Empty(FieldRecoveryPlanning.AvailableItems(reserved, c, "hp"));
        Assert.Throws<ProtocolException>(() => FieldRecoveryPlanning.Next(reserved, c, settings));
        Assert.Throws<ProtocolException>(() => FieldRecoveryPlanning.ValidateItems(settings with { HpRecovery = settings.HpRecovery with { Items = [22, 0, 0, 0, 0, 0, 0, 0, 0, 0] } }, c));
        Assert.Throws<ProtocolException>(() => new FieldRecoverySettings { PlayerPercent = 101 }.Validate());
        Assert.Throws<ProtocolException>(() => new FieldRecoverySettings { Items = [] }.Validate());
        Assert.Throws<ProtocolException>(() => new FieldRecoverySettings { Storage = "guess" }.Validate());
    }
}
