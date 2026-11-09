using System.Collections.Immutable;
using System.Numerics;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class MaintenanceKnowledgeTests
{
    [Theory]
    [MemberData(nameof(MaintenancePythonVectors.Cases), MemberType = typeof(MaintenancePythonVectors))]
    public void ActualPythonHelpersAndSelectionPrefixMatch(string name, string json)
    {
        Assert.False(string.IsNullOrEmpty(name));
        var vector = JsonNode.Parse(json)!; var input = vector["input"]!; var expected = vector["expected"]!;
        var items = input["items"]!.AsObject().ToDictionary(pair => ushort.Parse(pair.Key), pair =>
            new ItemDataRow(ushort.Parse(pair.Key), "synthetic", 0, 0, (ushort)N(pair.Value!, "restrict"), 0, 0,
                pair.Value!["special"] is null ? null : new ReviewedItemDetails
                    { Kind = (byte)N(pair.Value!, "kind"), Special = (byte)N(pair.Value!, "special"), FitType = (byte)N(pair.Value!, "fit_type") }));
        var player = new PlayerKnowledgeSnapshot { Equipment = new() { Equips = Equips(input["player"]!) } };
        var profiles = input["companions"]!.AsObject();
        var companions = new CompanionReceiveSnapshot
        {
            ActiveNpcId = input["active"]?.GetValue<uint>(), CompanionOrder = [.. profiles.Select(pair => ushort.Parse(pair.Key))],
            Companions = profiles.ToImmutableDictionary(pair => ushort.Parse(pair.Key), pair =>
            {
                var p = pair.Value!;
                return new CompanionProfileSnapshot(new((byte)N(p, "index"), (uint)N(p, "npc_id"), 0, 0, null, null,
                    0, 0, 0, 0, 0, null, 0, 0, null, null, [], [], null, 0, 0, 0, 0, null, 0), [], [])
                    { EquipmentOverrides = Equips(p) };
            })
        };
        var bag = Bag(input["inventory"]!);
        var targets = MaintenanceKnowledge.RepairTargets(items, player, companions, N(input, "threshold"));
        Assert.Equal(expected["targets"]!.AsArray().Count, targets.Length);
        for (var i = 0; i < targets.Length; i++)
        {
            var e = expected["targets"]![i]!; var actual = targets[i];
            Assert.Equal(N(e, "npc_index"), actual.NpcIndex); Assert.Equal(N(e, "equip_index"), actual.EquipIndex);
            Assert.Equal(N(e, "item_id"), actual.Equipment.ItemId); Assert.Equal((uint)N(e, "damage"), actual.Equipment.Damage);
            Assert.Same(actual.Equipment, MaintenanceKnowledge.Equipment(player, companions, actual.NpcIndex, actual.EquipIndex));
        }
        Assert.Null(MaintenanceKnowledge.Equipment(player, companions, 0, 0));
        Assert.Null(MaintenanceKnowledge.Equipment(player, companions, 999, 1));
        Assert.Null(MaintenanceKnowledge.Equipment(player, companions, 0, int.MaxValue));
        foreach (var repair in new[] { false, true })
        {
            var stock = MaintenanceKnowledge.BackpackStock(items, bag, repair);
            var rows = expected[repair ? "stock" : "all_stock"]!.AsObject().ToArray();
            Assert.Equal(rows.Length, stock.Length);
            for (var i = 0; i < rows.Length; i++)
            {
                Assert.Equal(ushort.Parse(rows[i].Key), stock[i].ItemId);
                Assert.Equal(new BigInteger(rows[i].Value!.GetValue<int>()), stock[i].Count);
            }
        }
        foreach (var pair in expected["slots"]!.AsObject())
            Assert.Equal(pair.Value!.GetValue<bool>(), MaintenanceKnowledge.SlotAvailable(bag, byte.Parse(pair.Key)));
        foreach (var pair in expected["repair"]!.AsObject())
            Assert.Equal(pair.Value!.GetValue<bool>(), MaintenanceKnowledge.IsRepair(items, ushort.Parse(pair.Key)));
        foreach (var pair in expected["cleanup"]!.AsObject())
            // Missing restriction in unreviewed synthetic input has no ItemData row equivalent.
            if (input["items"]![pair.Key]!["restrict"] is not null)
                Assert.Equal(pair.Value?.GetValue<string>(), MaintenanceKnowledge.CleanupAction(items, ushort.Parse(pair.Key))?.ToString().ToLowerInvariant());
        Assert.Null(MaintenanceKnowledge.CleanupAction(items, 999));
        var selected = targets.IsEmpty ? null : MaintenanceKnowledge.SelectRepairSupply(items, bag,
            [.. input["repair_items"]!.AsArray().Select(n => n!.GetValue<ushort>())]);
        Assert.Equal(expected["selected"]?.GetValue<byte>(), selected?.Index);
    }
    [Fact]
    public void TargetUsesSourceProfileIndexWhileEquipmentLookupUsesDictionarySlot()
    {
        var item = new ItemDataRow(20, "synthetic", 0, 0, 0, 0, 0, new() { Special = 0, FitType = 1 });
        var equip = new KnowledgeEquipment(20, Damage: 200);
        var profile = new CompanionProfileSnapshot(new(7, 9, 0, 0, null, null, 0, 0, 0, 0, 0, null, 0, 0,
            null, null, [], [], null, 0, 0, 0, 0, null, 0), [], []) { EquipmentOverrides = [equip] };
        var companions = new CompanionReceiveSnapshot { ActiveNpcId = 9, CompanionOrder = [2],
            Companions = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty.Add(2, profile) };
        var result = MaintenanceKnowledge.RepairTargets(new Dictionary<ushort, ItemDataRow> { [20] = item }, new(), companions, 50);
        Assert.Equal((ushort)7, Assert.Single(result).NpcIndex);
        Assert.Null(MaintenanceKnowledge.Equipment(new(), companions, 7, 1));
        Assert.Same(equip, MaintenanceKnowledge.Equipment(new(), companions, 2, 1));
    }
    private static ImmutableArray<KnowledgeEquipment>? Equips(JsonNode profile) => profile["equips"] is not { } equips ? null :
        [.. equips.AsArray().Select(row => new KnowledgeEquipment((ushort)N(row!, "item_id"), Damage: row!["damage"]?.GetValue<uint>(),
            OriginalRecord: row["locked"] is null && row["available_time"] is null && row["limited_time"] is null ? null : Item(row!, 0)))];
    internal static ItemSave Item(JsonNode row, byte index) => new(index, (ushort)N(row,"item_id"), (byte)Math.Clamp(N(row,"count"),0,255),
        (byte)Math.Clamp(N(row,"damage"),0,255), 1, (uint)(1000+index), null, null, 0,
        N(row,"available_time"), N(row,"limited_time"), 0, 0, 0, null, 0, 0, 0, [], N(row,"locked") != 0, 0, 0, null);
    internal static BagReceiveSnapshot Bag(JsonNode inv)
    {
        var rows = inv["items"]!.AsObject();
        ImmutableArray<ushort>? Slots(string key) => inv[key] is { } n ? [.. n.AsArray().Select(v => ushort.Parse(v!.GetValue<string>()))] : null;
        return new()
        {
            Ready = inv["ready"]?.GetValue<bool>() == true, Reliable = inv["reliable"]?.GetValue<bool>() == true,
            ItemOrder = [.. rows.Select(pair => byte.Parse(pair.Key))],
            Items = rows.ToImmutableDictionary(pair => byte.Parse(pair.Key), pair => new BagItemSnapshot(Item(pair.Value!,byte.Parse(pair.Key)),
                byte.Parse(pair.Key),N(pair.Value!,"count"),(uint)N(pair.Value!,"damage"))),
            Reserved = (inv["reserved"]?.AsObject() ?? []).ToImmutableDictionary(pair => ushort.Parse(pair.Key),pair => new BigInteger(pair.Value!.GetValue<int>())),
            AlchemySlots = Slots("alchemy_slots"), ExpeditionSlots = Slots("expedition_slots"), MaintenanceSlots = Slots("maintenance_slots"),
            Holds = [.. (inv["holds"]?.AsObject() ?? []).Select(pair => new StorageReservationGroup(pair.Key,
                [.. pair.Value!.AsArray().Select(row => new StorageReservationSnapshot(ushort.Parse(row!["index"]!.GetValue<string>()),new(10,1,1),1,1,3,
                    row["exclusive"]?.GetValue<bool>() == true,row["uncertain"]?.GetValue<bool>() == true))]))]
        };
    }
    private static int N(JsonNode row,string key) => row[key]?.GetValue<int>() ?? 0;
}
