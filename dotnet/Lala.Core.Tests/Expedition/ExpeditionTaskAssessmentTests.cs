using System.Collections.Immutable;
using System.Numerics;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Catalogs.RuntimeCandidate;
using Xunit;
using ExpeditionReward = Lala.Core.Catalogs.ExpeditionReward;

namespace Lala.Core.Tests.Expedition;

public sealed class ExpeditionTaskAssessmentTests
{
    public static IEnumerable<object[]> Cases()
    {
        using var json = JsonDocument.Parse(PythonExpeditionAssessmentVectors.Json);
        return json.RootElement.EnumerateArray().Select((v, i) => new object[] { i, v.Clone() }).ToArray();
    }
    internal static ItemDataRow Item(ushort id, bool stackable = true, byte special = 0, params ItemAttribute[] attributes) =>
        new(id, "synthetic", 0, 0, 0, 0, 0, new() { Stackable = stackable, Special = special, Attributes = Array.AsReadOnly(attributes) });
    internal static BagItemSnapshot BagItem(byte index, ushort id, int count = 1, bool locked = false, double available = 0, double limited = 0) =>
        new(new(index, id, 1, 0, 0, 1, null, null, 0, available, limited, 0, 0, 0, null, 0, 0, 0, [], locked, 0, 0, null), index, count, 0);
    internal static ExpeditionTaskData TaskData() => new(1, 1, 0, 1, 0, 0, 5, 40, 600, [1, 1, 0],
        [new([5, 20, 0], 400), new([0, 0, 0], 0), new([0, 0, 0], 0), new([0, 0, 0], 0)],
        0, [new(0, 0, 0), new(0, 0, 0), new(0, 0, 0)], 0, new(0, 0, 0), 0);
    internal static ExpeditionOutpostState Role(byte index = 1, int faith = 20) =>
        new(index, 100, 0, new(1, 2, 3, 4, 5, 20, 0, 0), faith, 0, 0, 0, 0);
    internal static OfflineRuntimeCandidate Candidate(ExpeditionTaskData? task = null,
        IReadOnlyDictionary<ushort, ItemDataRow>? items = null, bool includeLevel = true, bool includeNpc = true)
    {
        // Internal synthetic composition for calculation only. Does not exercise pinned
        // ItemData decoding, source trust or production resource admission.
        var original = OfflineRuntimeCandidateDecoder.Decode(CandidatePortalIntegrationTests.Inputs(
            CandidatePortalOracleCases.Read(1)), CandidatePortalIntegrationTests.Version);
        return new(original.EveIndexes, items ?? ImmutableDictionary<ushort, ItemDataRow>.Empty,
            original.Talks, original.Texts, original.Recipes, original.Stages, original.Doors, original.SceneNames,
            new(ImmutableDictionary<ushort, ExpeditionTaskData>.Empty.Add(1, task ?? TaskData()),
                includeLevel ? ImmutableDictionary<byte, ExpeditionLevelData>.Empty.Add(1, new(1, 1, 500)) : ImmutableDictionary<byte, ExpeditionLevelData>.Empty,
                ImmutableDictionary<string, string>.Empty),
            includeNpc ? ImmutableDictionary<ushort, ExpeditionNpcData>.Empty.Add(100, new(1, 0, 100)) : ImmutableDictionary<ushort, ExpeditionNpcData>.Empty,
            original.SourceSha256, original.PortalObservations);
    }
    internal static ServiceStateSnapshot State(ExpeditionOutpostState? role = null, BagReceiveSnapshot? bag = null) =>
        new(expedition: new() { OutpostReady = true, Level = 1, Roles = ImmutableDictionary<byte, ExpeditionOutpostState>.Empty.Add(1, role ?? Role()) },
            bag: bag ?? new() { Ready = true, Reliable = true, Capacity = 1 });
    internal static AccountRuntimePublicationSnapshot Basis(ServiceStateSnapshot state, OfflineRuntimeCandidate? candidate) =>
        new(new(Guid.NewGuid(), 1, 1, AccountConnectionPhase.ReceivingHeld, null, null, []),
            new(new(Guid.NewGuid(), 9, AccountReceivePhase.Running, state), candidate), false);

    [Theory, MemberData(nameof(Cases))]
    public void Helper_measurements_match_actual_python_manager(int index, JsonElement value)
    {
        _ = index;
        var items = value.GetProperty("items").EnumerateObject().ToDictionary(p => ushort.Parse(p.Name), p =>
            Item(ushort.Parse(p.Name), value.GetProperty("rules").GetProperty(p.Name).GetBoolean(), p.Value.GetProperty("special").GetByte(),
                p.Value.GetProperty("attributes").EnumerateArray().Select(a => new ItemAttribute(a.GetProperty("kind").GetUInt16(),
                    a.GetProperty("effect").GetByte(), a.GetProperty("value").GetInt32())).ToArray()));
        foreach (var gain in value.GetProperty("gains").EnumerateObject())
            Assert.Equal(gain.Value.GetInt64(), ExpeditionTaskInspection.FaithGain(items[ushort.Parse(gain.Name)]));
        var q = value.GetProperty("quest");
        static ExpeditionReward Reward(JsonElement r) => new(r.GetProperty("kind").GetByte(), r.GetProperty("id").GetUInt32(), r.GetProperty("value").GetUInt32());
        var task = TaskData() with { Minutes = q.GetProperty("minutes").GetUInt16(), Rewards = [.. q.GetProperty("rewards").EnumerateArray().Select(Reward)], SpecialReward = Reward(q.GetProperty("special_reward")) };
        Assert.Equal(value.GetProperty("duration").GetInt32(), ExpeditionTaskInspection.DurationSeconds(task.Minutes, value.GetProperty("level").GetProperty("reduction").GetUInt16()));
        var issues = new List<ExpeditionAssessmentIssue>();
        long? expected = value.GetProperty("need").ValueKind == JsonValueKind.Null ? null : value.GetProperty("need").GetInt64();
        Assert.Equal(expected, ExpeditionTaskInspection.RewardSlots(task, items, issues));
        var inv = value.GetProperty("inventory");
        ImmutableArray<ushort> Slots(string name) => [.. inv.GetProperty(name).EnumerateArray().Select(v => ushort.Parse(v.GetString()!))];
        var bag = new BagReceiveSnapshot
        {
            Ready = true, Reliable = true, Capacity = 20,
            Items = inv.GetProperty("items").EnumerateObject().ToImmutableDictionary(p => byte.Parse(p.Name), p =>
                BagItem(byte.Parse(p.Name), p.Value.GetProperty("item_id").GetUInt16(), p.Value.GetProperty("count").GetInt32(),
                    p.Value.GetProperty("locked").GetBoolean(), p.Value.GetProperty("available_time").GetDouble(), p.Value.GetProperty("limited_time").GetDouble())),
            Reserved = inv.GetProperty("reserved").EnumerateObject().ToImmutableDictionary(p => ushort.Parse(p.Name), p => new BigInteger(p.Value.GetInt32())),
            AlchemySlots = Slots("alchemy_slots"), ExpeditionSlots = Slots("expedition_slots"), MaintenanceSlots = Slots("maintenance_slots")
        };
        var actual = ExpeditionTaskInspection.RecoveryStock(bag, items, issues);
        Assert.True(actual.Complete); Assert.Empty(actual.Unknown);
        Assert.Equal(value.GetProperty("stock").EnumerateObject().OrderBy(p => ushort.Parse(p.Name)).Select(p => (ushort.Parse(p.Name), new BigInteger(p.Value.GetInt64()))),
            actual.Stock.Select(r => (r.ItemId, r.AvailableCount)));
    }

    [Fact]
    public void Exact_historical_basis_selected_team_and_known_zero_measurements_are_preserved()
    {
        var state = State(); var candidate = Candidate(); var basis = Basis(state, candidate);
        var result = ExpeditionTaskInspection.Inspect(basis, 1, [1]);
        Assert.Same(basis, result.Basis); Assert.Same(state, result.Basis.Publication!.Receive.State);
        Assert.Same(candidate, result.Basis.Publication.Catalogs);
        Assert.Equal(180, result.DurationSeconds); Assert.Equal(0, result.RewardEmptySlots); Assert.Equal(1, result.ObservedFreeSlots);
        Assert.True(result.ConditionMet); Assert.Equal(1000, result.Success!.Points); Assert.True(result.Success.Complete);
        Assert.Equal(20, Assert.Single(result.RoleFaith).Deficit); Assert.True(result.RecoveryStockComplete); Assert.Empty(result.RecoveryStock);
        Assert.Empty(result.Issues); Assert.True(result.ResourceHeld); Assert.False(result.CanSendCommands);
        Assert.Equal(nameof(ExpeditionTaskAssessment), result.ToString());
        Assert.Empty(typeof(ExpeditionTaskAssessment).GetConstructors());
    }

    [Fact]
    public void Missing_evidence_is_never_known_zero_or_no_team()
    {
        var basis = Basis(new(), Candidate());
        var result = ExpeditionTaskInspection.Inspect(basis, 1, [1]);
        Assert.Null(result.DurationSeconds); Assert.Null(result.ObservedFreeSlots); Assert.Null(result.ConditionMet); Assert.Null(result.Success);
        Assert.False(result.RecoveryStockComplete); Assert.Contains(ExpeditionAssessmentIssue.OutpostUnknown, result.Issues);
        Assert.Contains(ExpeditionAssessmentIssue.ExpeditionLevelUnknown, result.Issues);
        Assert.Contains(ExpeditionAssessmentIssue.BagUnknown, result.Issues);
        result = ExpeditionTaskInspection.Inspect(Basis(State(), null), 1, [1]);
        Assert.Contains(ExpeditionAssessmentIssue.CatalogsUnavailable, result.Issues); Assert.Null(result.RewardEmptySlots);
        result = ExpeditionTaskInspection.Inspect(Basis(State(), Candidate(includeLevel: false)), 1, [1]);
        Assert.Contains(ExpeditionAssessmentIssue.LevelDefinitionMissing, result.Issues); Assert.Null(result.DurationSeconds);
        result = ExpeditionTaskInspection.Inspect(Basis(State(), Candidate()), 2, [1]);
        Assert.Contains(ExpeditionAssessmentIssue.TaskUnavailable, result.Issues);
        result = ExpeditionTaskInspection.Inspect(Basis(State(), Candidate()), 1, [2]);
        Assert.Contains(ExpeditionAssessmentIssue.SelectedRoleMissing, result.Issues); Assert.Null(result.ConditionMet); Assert.Null(result.Success);
        Assert.Null(Assert.Single(result.RoleFaith).Deficit);
    }

    [Fact]
    public void Selection_is_bounded_and_malformed_task_is_typed()
    {
        var basis = Basis(State(), Candidate());
        foreach (ImmutableArray<byte> slots in new ImmutableArray<byte>[] { default, [], [0], [1, 1], [1, 2, 3, 4, 5] })
            Assert.Equal(new[] { ExpeditionAssessmentIssue.InvalidSelection }, ExpeditionTaskInspection.Inspect(basis, 1, slots).Issues);
        Assert.Equal(new[] { ExpeditionAssessmentIssue.InvalidSelection }, ExpeditionTaskInspection.Inspect(basis, 0, [1]).Issues);
        var invalid = Candidate(TaskData() with { Recommendations = [.. Enumerable.Repeat(new Lala.Core.Catalogs.ExpeditionRecommendation([0, 0, 0], 0), 1000)] });
        Assert.Contains(ExpeditionAssessmentIssue.InvalidCatalogData, ExpeditionTaskInspection.Inspect(Basis(State(), invalid), 1, [1]).Issues);
    }

    [Theory]
    [InlineData("faith")][InlineData("level")][InlineData("str")][InlineData("con")][InlineData("int")][InlineData("wis")][InlineData("agi")]
    public void Signed_negative_role_values_remain_unsupported_without_clamping(string field)
    {
        var role = Role(); role = field switch
        {
            "faith" => role with { Faith = -1 }, "level" => role with { Stats = role.Stats with { Level = -1 } },
            "str" => role with { Stats = role.Stats with { Str = -1 } }, "con" => role with { Stats = role.Stats with { Con = -1 } },
            "int" => role with { Stats = role.Stats with { Int = -1 } }, "wis" => role with { Stats = role.Stats with { Wis = -1 } },
            _ => role with { Stats = role.Stats with { Agi = -1 } }
        };
        var result = ExpeditionTaskInspection.Inspect(Basis(State(role), Candidate()), 1, [1]);
        Assert.Contains(ExpeditionAssessmentIssue.UnsupportedRoleValues, result.Issues); Assert.Null(result.ConditionMet); Assert.Null(result.Success);
        Assert.Equal(role.Faith, result.RoleFaith[0].Faith);
        if (field == "faith") Assert.Null(result.RoleFaith[0].Deficit);
    }

    [Fact]
    public void Reward_need_uses_reviewed_catalog_not_server_stack_flags_and_never_pools_rewards()
    {
        var task = TaskData() with { Rewards = [new(10, 1, 201), new(10, 1, 1), new(11, 1, uint.MaxValue)], SpecialReward = new(10, 1, 1), SpecialRate = 0 };
        var items = ImmutableDictionary<ushort, ItemDataRow>.Empty.Add(1, Item(1));
        var bag = new BagReceiveSnapshot { Ready = true, Reliable = true, Capacity = 1, Items = ImmutableDictionary<byte, BagItemSnapshot>.Empty.Add(1, BagItem(1, 1)), ServerStackable = ImmutableDictionary<ushort, bool>.Empty.Add(1, false) };
        var result = ExpeditionTaskInspection.Inspect(Basis(State(bag: bag), Candidate(task, items)), 1, [1]);
        Assert.Equal((long)uint.MaxValue + 4, result.RewardEmptySlots); Assert.Equal(0, result.ObservedFreeSlots);
        var unreviewed = items.SetItem(1, items[1] with { ReviewedDetails = null });
        result = ExpeditionTaskInspection.Inspect(Basis(State(bag: bag), Candidate(task, unreviewed)), 1, [1]);
        Assert.Null(result.RewardEmptySlots); Assert.False(result.RecoveryStockComplete); Assert.Equal(new ushort[] { 1 }, result.UnknownRecoveryItemIds);
        Assert.Contains(ExpeditionAssessmentIssue.RewardItemDetailsUnknown, result.Issues);
        result = ExpeditionTaskInspection.Inspect(Basis(State(), Candidate(task with { SpecialReward = new(99, 0, 0) }, items)), 1, [1]);
        Assert.Null(result.RewardEmptySlots); Assert.Contains(ExpeditionAssessmentIssue.UnsupportedRewardKind, result.Issues);
    }

    [Fact]
    public void Unknown_npc_metadata_is_not_invented_and_success_completeness_is_independent()
    {
        var task = TaskData() with { Condition = [2, 1, 1], SuccessRate = 1000, Recommendations = [new([2, 1, 1], 10)] };
        var result = ExpeditionTaskInspection.Inspect(Basis(State(), Candidate(task, includeNpc: false)), 1, [1]);
        Assert.Null(result.ConditionMet); Assert.True(result.Success!.Complete); Assert.Null(result.Success.Recommendations[0].Met);
        Assert.Equal(100m, result.Success.Percent);
    }

    [Theory]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public void Recovery_partial_stock_excludes_item_and_reservation_locks_and_nonzero_times(bool exclusive, bool uncertain)
    {
        var item = Item(1, true, 0, new ItemAttribute(64, 0, 130));
        var items = ImmutableDictionary<ushort, ItemDataRow>.Empty.Add(1, item);
        var bag = new BagReceiveSnapshot
        {
            Ready = true, Reliable = true, Capacity = 10,
            Items = Enumerable.Range(1, 10).ToImmutableDictionary(i => (byte)i, i => BagItem((byte)i, 1, 10))
                .SetItem(3, BagItem(3, 1, 10, locked: true))
                .SetItem(4, BagItem(4, 1, 10, available: -1))
                .SetItem(5, BagItem(5, 1, 10, limited: 1))
                .SetItem(10, BagItem(10, 2, 10)),
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 3).Add(2, 100),
            AlchemySlots = [6], ExpeditionSlots = [7], MaintenanceSlots = [8],
            Holds = [new("other", [new(9, new(1, 1, 0), 0, 0, 10, exclusive, uncertain)])]
        };
        var issues = new List<ExpeditionAssessmentIssue>();
        var result = ExpeditionTaskInspection.RecoveryStock(bag, items, issues);
        Assert.False(result.Complete); Assert.Equal(new ushort[] { 2 }, result.Unknown);
        Assert.Equal(new ExpeditionRecoveryItem(1, 30, 7), Assert.Single(result.Stock));
        Assert.Contains(ExpeditionAssessmentIssue.RecoveryItemDetailsUnknown, issues);
        Assert.Equal(10, bag.Items[1].Count); Assert.Equal(3, bag.Reserved[1]); Assert.Single(bag.Holds);
        // Unknown effect on an unavailable slot cannot add stock, so known zero is valid.
        result = ExpeditionTaskInspection.RecoveryStock(bag with { ExpeditionSlots = [1, 7, 10] }, items, []);
        Assert.True(result.Complete); Assert.Empty(result.Stock); Assert.Empty(result.Unknown);
        result = ExpeditionTaskInspection.RecoveryStock(bag with { Reliable = false }, items, []);
        Assert.False(result.Complete); Assert.Empty(result.Stock);
        Assert.Null(ExpeditionTaskInspection.FreeSlots(bag with { Capacity = null }, []));
        Assert.Null(ExpeditionTaskInspection.FreeSlots(bag with { Capacity = 0 }, []));
        foreach (byte? capacity in new byte?[] { null, 0 })
        {
            var withUnknownCapacity = ExpeditionTaskInspection.RecoveryStock(bag with { Capacity = capacity }, items, []);
            Assert.Equal(new ExpeditionRecoveryItem(1, 30, 7), Assert.Single(withUnknownCapacity.Stock));
        }
    }

    [Fact]
    public void Imported_invalid_or_oversized_reservations_are_typed_without_running_availability()
    {
        var items = ImmutableDictionary<ushort, ItemDataRow>.Empty.Add(1, Item(1, true, 0, new ItemAttribute(64, 0, 130)));
        var bag = new BagReceiveSnapshot { Ready = true, Reliable = true, Items = ImmutableDictionary<byte, BagItemSnapshot>.Empty.Add(1, BagItem(1, 1, 10)) };
        foreach (var invalid in new[]
        {
            bag with { Holds = default },
            bag with { Holds = [new("test", [null!])] },
            bag with { AlchemySlots = default(ImmutableArray<ushort>) },
            bag with { ExpeditionSlots = default(ImmutableArray<ushort>) },
            bag with { MaintenanceSlots = default(ImmutableArray<ushort>) },
            bag with { Holds = [.. Enumerable.Repeat(new StorageReservationGroup("test", []), 257)] },
            bag with { Holds = [new("test", [.. Enumerable.Repeat(new StorageReservationSnapshot(1, new(1, 1, 0), 1, 1, 10, false, false), 257)])] },
            bag with { AlchemySlots = [.. Enumerable.Repeat((ushort)1, 257)] },
            bag with { Reserved = bag.Reserved.Add(1, -1) },
            bag with { Items = bag.Items.SetItem(1, BagItem(1, 1, -1)) }
        })
        {
            var issues = new List<ExpeditionAssessmentIssue>();
            var result = ExpeditionTaskInspection.RecoveryStock(invalid, items, issues);
            Assert.False(result.Complete); Assert.Empty(result.Stock);
            Assert.Contains(ExpeditionAssessmentIssue.InvalidBagData, issues);
        }
    }

    [Fact]
    public void Recovery_metadata_last_faith_attribute_and_special_flag_are_not_guessed()
    {
        Assert.Null(ExpeditionTaskInspection.FaithGain(Item(1) with { ReviewedDetails = null }));
        Assert.Equal(0, ExpeditionTaskInspection.FaithGain(Item(1, true, 1, new ItemAttribute(64, 0, 200))));
        Assert.Equal(0, ExpeditionTaskInspection.FaithGain(Item(1, true, 0, new ItemAttribute(64, 0, 200), new ItemAttribute(64, 0, 99))));
        Assert.Equal(30, ExpeditionTaskInspection.FaithGain(Item(1, true, 0, new ItemAttribute(64, 1, 110), new ItemAttribute(27, 0, 999), new ItemAttribute(64, 2, 130))));
        Assert.Equal((long)int.MaxValue - 100, ExpeditionTaskInspection.FaithGain(Item(1, true, 0, new ItemAttribute(64, 0, int.MaxValue))));
        Assert.Equal(0, ExpeditionTaskInspection.FaithGain(Item(1, true, 0, new ItemAttribute(64, 0, int.MinValue))));
    }
}
