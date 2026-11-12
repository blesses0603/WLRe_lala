using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World;
using Lala.Core.World.Eve;
using Xunit;

namespace Lala.Core.Tests.Automation;

public sealed class ShopInventoryCommandTests
{
    private static ItemSave Record(uint serial = 1234) => new(1, 20, 3, 0, 1, serial, null, null, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, [], false, 0, 0, null);
    private static OfflineRuntimeCandidate Catalog(ItemDataRow? item = null)
    {
        var interactions = new EveInteractionRow(7, 3, 0, [new(8, 20, 2, 3), new(0, 0, 0, 4)]);
        return new(new([new(101, [], [interactions])], false, true, 0, 1),
            new Dictionary<ushort, ItemDataRow> { [20] = item ?? new(20, "測試道具", 10, 3, 0, 0, 1,
                new() { Kind = 23, FitType = 8, Stackable = true }) },
            new Dictionary<ushort, TalkDataRow>(), new Dictionary<uint, string>(), null!, new Dictionary<ushort, StageDataRow>(),
            null!, new Dictionary<ushort, string>(), null!, new Dictionary<ushort, ExpeditionNpcData>(), new Dictionary<string, string>(), null!);
    }
    private static ServiceStateSnapshot State(bool shop = false) => new(local: new(
        new SessionEventSnapshot { Phase = "world_ready", InitialDataComplete = true,
            Gold = new() { Ready = true, Reliable = true, Amount = 100 }, EventFlow = new() { Blocked = shop },
            NpcDialogue = shop ? new() { Active = true, Phase = "choice_unavailable", Scene = 101, NpcIndex = 1, NpcId = 12,
                EffectType = 6, EffectPacket = 42, OptionIndex = 7 } : new() },
        new WorldEventSnapshot { Phase = "world_ready", Player = new(17, 0, 101, 20, 30, 0, 0, 0, 0, 0, 0, false, [], "測試", 0) }),
        bag: new() { Ready = true, Reliable = true, Capacity = 10, Items = ImmutableDictionary<byte, BagItemSnapshot>.Empty.Add(1, new(Record(), 1, 3, 0)), ItemOrder = [1] },
        playerKnowledge: new() { Ready = true, Stats = ImmutableDictionary<string, long>.Empty.Add("hp", 10).Add("level", 18) });
    private static GameAction Buy() => new("shop", "buy", 20, 8, 2, X: 7, Scene: 101, Key: "42", ExpectedPrice: 10);
    private static GameAction Item(string operation, int count = 1) => new("inventory_item", operation, 20, 1, count,
        Scene: 101, RecipientId: 17, ItemSerial: 1234, ItemSerialVersion: 1, ExpectedPrice: 3);
    private static ServiceStateSnapshot Balance(ServiceStateSnapshot s, uint balance, int count) => CommandState.With(s,
        local: new(s.Local.Session with { Gold = s.Local.Session.Gold with { Amount = balance } }, s.Local.World, s.Local.Battle),
        bag: s.Bag with { Items = count == 0 ? s.Bag.Items.Remove(1) : s.Bag.Items.SetItem(1, s.Bag.Items[1] with { Count = count }) });

    [Fact]
    public void Purchase_needs_live_shop_exact_offer_price_receipt_inventory_and_gold_in_either_order()
    {
        var s = State(true); var plan = ManualGameCommands.Plan(Buy(), s, Catalog(), 0, "test");
        Assert.Equal((byte)27, plan.Packet.Main); Assert.Equal((byte)1, plan.Packet.Sub);
        Assert.Equal(new byte[] { 8, 2, 0, 0, 0 }, plan.Packet.Payload.ToArray());
        Assert.False(plan.Acknowledged(Balance(s, 80, 5)));
        plan.ObserveReceipt!(new(1, 23, 2, "bag_add", "", ItemId: 20, Count: 2));
        Assert.False(plan.Acknowledged(Balance(s, 80, 5)));
        plan.ObserveReceipt(new(2, 27, 1, "shop_purchase_result", "", Code: 0));
        Assert.False(plan.Acknowledged(Balance(s, 100, 5)));
        Assert.False(plan.Acknowledged(Balance(s, 80, 3)));
        Assert.True(plan.Acknowledged(Balance(s, 80, 5)));
        var reversed = ManualGameCommands.Plan(Buy(), s, Catalog(), 0, "test");
        reversed.ObserveReceipt!(new(1, 27, 1, "shop_purchase_result", "", Code: 0));
        reversed.ObserveReceipt(new(2, 23, 2, "bag_add", "", ItemId: 20, Count: 2));
        Assert.True(reversed.Acknowledged(Balance(s, 80, 5)));
    }
    [Theory]
    [InlineData("closed")][InlineData("effect")][InlineData("offer")][InlineData("price")][InlineData("scene")]
    [InlineData("money")][InlineData("space")][InlineData("unknown_gold")][InlineData("battle")]
    public void Purchase_rejects_stale_context_or_insufficient_resources_before_write(string mode)
    {
        var s = State(mode != "closed"); var action = Buy();
        action = mode switch { "effect" => action with { Key = "41" }, "offer" => action with { Index = 7 },
            "price" => action with { ExpectedPrice = 9 }, "scene" => action with { Scene = 102 }, _ => action };
        if (mode == "money") s = Balance(s, 19, 3);
        if (mode == "space") s = CommandState.With(s, bag: s.Bag with { Capacity = 1 });
        if (mode == "unknown_gold") s = CommandState.With(s, local: new(s.Local.Session with { Gold = new() }, s.Local.World, s.Local.Battle));
        if (mode == "battle") s = CommandState.With(s, local: new(s.Local.Session, s.Local.World, s.Local.Battle with { Active = true }));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(action, s, Catalog(), 0, "test"));
    }
    [Fact]
    public void Known_purchase_refusal_survives_receipt_folding_without_becoming_unknown_settlement()
    {
        var watch = new GameReceiptWatch(ManualGameCommands.Plan(Buy(), State(true), Catalog(), 0, "test"));
        watch.Arm(10); watch.Observe(new(9, 27, 1, "shop_purchase_result", "", Code: 0));
        Assert.False(watch.Acknowledged(State(true)));
        watch.Observe(new(11, 27, 1, "shop_purchase_result", "", Code: 1));
        Assert.Throws<GameActionRefusedException>(() => watch.Acknowledged(State(true)));
        Assert.Throws<ProtocolException>(() => watch.Acknowledged(Balance(State(true),80,5)));
    }
    [Theory][InlineData("discard", 23, 124)][InlineData("sell", 27, 3)][InlineData("use", 23, 15)]
    public void Item_operations_require_exact_identity_matching_result_and_actual_consumption(string operation, int main, int sub)
    {
        var s = State(); var plan = ManualGameCommands.Plan(Item(operation), s, Catalog(), 0, "test");
        Assert.Equal(main, plan.Packet.Main); Assert.Equal(sub, plan.Packet.Sub);
        var next = Balance(s, operation == "sell" ? 103u : 100u, 2);
        Assert.False(plan.Acknowledged(next));
        if (operation == "use") plan.ObserveReceipt!(new(1, 23, 15, "item_use_result", "", ItemId: 20, Index: 0, Code: 2));
        else plan.ObserveReceipt!(new(1, (byte)main, (byte)sub, operation == "sell" ? "bag_sell" : "bag_delete", "", Index: 1, Count: 1));
        Assert.False(plan.Acknowledged(s)); Assert.True(plan.Acknowledged(next));
        Assert.Throws<ProtocolException>(() => plan.Acknowledged(CommandState.With(next, bag: next.Bag with
            { Items = next.Bag.Items.SetItem(1, new(Record(9876), 1, 2, 0)) })));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(Item(operation) with { ItemSerial = 0 }, s, Catalog(), 0, "test"));
    }
    [Fact]
    public void Manual_discard_is_independent_of_sale_classification_but_respects_lock_reservation_and_restrictions()
    {
        var s = State(); var item = Catalog().Items[20];
        Assert.NotNull(ManualGameCommands.Plan(Item("discard"), s, Catalog(item with { Restrict = 16 }), 0, "test"));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(Item("discard"), s, Catalog(item with { Restrict = 128 }), 0, "test"));
        foreach (var bag in new[] { s.Bag with { Reserved = s.Bag.Reserved.Add(1, 1) }, s.Bag with { Reliable = false },
            s.Bag with { Items = s.Bag.Items.SetItem(1, s.Bag.Items[1] with { OriginalRecord = Record() with { Locked = true } }) } })
            Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(Item("discard"), CommandState.With(s, bag: bag), Catalog(), 0, "test"));
    }
    [Theory][InlineData(1, 0)][InlineData(11, 0)][InlineData(8, 130)][InlineData(8, 146)][InlineData(8, 66)]
    public void Equipment_and_dedicated_ui_items_never_fall_through_to_generic_use(byte fit, byte special)
    {
        var row = Catalog().Items[20] with { ReviewedDetails = new() { Kind = 25, FitType = fit, Special = special } };
        Assert.False(GameInventoryOperations.IsOrdinaryConsumable(row));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(Item("use"), State(), Catalog(row), 0, "test"));
    }
    [Fact]
    public void Cooperative_claim_requires_award_details_and_real_item_admission_even_if_chest_closed()
    {
        var s = State(); var receipt = new CooperativeRewardReceipt(s.Bag);
        Assert.False(receipt.Acknowledged(s.Bag));
        receipt.Observe(new(1, 186, 10, "instance_reward_receipt", "") { InstanceAwards = [new(10, 20, 2)] });
        Assert.False(receipt.Acknowledged(s.Bag)); Assert.True(receipt.Acknowledged(Balance(s, 100, 5).Bag));
        Assert.Throws<ProtocolException>(() => receipt.Observe(new(2, 186, 10, "instance_reward_receipt", "") { InstanceAwards = [new(10, 20, 3)] }));
        Assert.Throws<ProtocolException>(() => new CooperativeRewardReceipt(s.Bag).Observe(new(1, 186, 10, "instance_reward_receipt", "")));
    }

    [Fact]
    public void Cooperative_free_reward_accepts_two_empty_slots_and_does_not_treat_chest_closure_as_item_success()
    {
        var s = State();
        var coop = s.Instances.Coop.MapValue.SetItem("reward", StateValue.Map(("open_reward", StateValue.Scalar(1)), ("reward_mark", StateValue.Scalar(1))));
        s = CommandState.With(s, instances: s.Instances with { Coop = StateValue.Map(coop) }, bag: s.Bag with { Capacity = 3 });
        var plan = ManualGameCommands.Plan(new("instance", "claim", Key: "coop"), s, Catalog(), 0, "test");
        Assert.Equal((byte)186, plan.Packet.Main); Assert.Equal((byte)10, plan.Packet.Sub);
        Assert.False(plan.Acknowledged(s));
        var closed = CommandState.With(s, instances: s.Instances with { Coop = StateValue.Map(coop.SetItem("reward", StateValue.Map(("open_reward", StateValue.Scalar(0))))) });
        Assert.False(plan.Acknowledged(closed));
        plan.ObserveReceipt!(new(1,186,10,"instance_reward_receipt",""){InstanceAwards=[new(10,20,2)]});
        Assert.False(plan.Acknowledged(closed)); Assert.True(plan.Acknowledged(Balance(closed,100,5)));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(new("instance","claim",Key:"coop"),
            CommandState.With(s,bag:s.Bag with{Capacity=2}),Catalog(),0,"test"));
    }

    [Fact]
    public void Cooperative_reward_sale_metadata_is_not_a_room_entry_fee()
    {
        var seed=Catalog();
        var stage=new StageDataRow(200,0,0,4,1,1,10,0,10,0,0,1,1,100,100,0,0);
        var dungeon=new DungeonDataRow(5,2,1,200,0,0,0,0,0,0,0,0,[],[],[]);
        var cooperative=new CooperativeEventDataRow(9,0,0,0,1,0,0,999,[],new(0,0,0));
        var bound=new BoundInstanceCatalogRow(dungeon,stage,"測試副本",0,[],cooperative,true);
        var c=new OfflineRuntimeCandidate(seed.EveIndexes,seed.Items,seed.Talks,seed.Texts,seed.Recipes,seed.Stages,seed.Doors,seed.SceneNames,
            seed.Expedition,seed.Npcs,seed.SourceSha256,seed.PortalObservations,optionalInstances:new([bound],[cooperative],[]));
        var plan=ManualGameCommands.Plan(new("instance","create",5,Count:2,Key:"coop"),State(),c,0,"test");
        Assert.Equal(new byte[]{2,1,9,1,0,0,0,0,0},plan.Packet.Payload.ToArray());
        Assert.Equal((byte)186,plan.Packet.Main);Assert.Equal((byte)1,plan.Packet.Sub);
    }
}
