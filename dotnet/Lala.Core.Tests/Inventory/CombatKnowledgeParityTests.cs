using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatKnowledgeParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> NpcSkills =
        new Dictionary<uint, ImmutableArray<uint>> { [1] = [1001, 0, 1002, 1001, 0], [2] = [1002] }.ToImmutableDictionary();
    private static readonly CombatKnowledgeCatalog[] Catalogs =
    [
        new(),
        new() { SkillKeys = new Dictionary<ushort, uint> { [1] = 1001, [2] = 1002, [3] = 1001, [4] = 0 }.ToImmutableDictionary(),
            ItemFitTypes = new Dictionary<ushort, int> { [42] = 3, [43] = 11, [44] = 0, [45] = 9 }.ToImmutableDictionary() },
        new() { SkillKeys = new Dictionary<ushort, uint> { [1] = 2001, [2] = 1002, [3] = 1001 }.ToImmutableDictionary(),
            ItemFitTypes = new Dictionary<ushort, int> { [42] = 3, [43] = 11, [44] = 0, [45] = 9, [99] = 3, [100] = 2 }.ToImmutableDictionary() },
        new() { ItemFitTypes = new Dictionary<ushort, int> { [99] = 3, [100] = 2 }.ToImmutableDictionary() }
    ];

    [Theory]
    [MemberData(nameof(CombatKnowledgePythonVectors.Sequences), MemberType = typeof(CombatKnowledgePythonVectors))]
    public void EveryReceiveTransitionAndRetainedHistoryMatchesPython(string name, string json)
    {
        var player = PlayerKnowledgeSnapshot.Empty;
        var companions = CompanionReceiveSnapshot.Empty;
        var battle = BattleEventSnapshot.Empty;
        var session = new SessionEventSnapshot();
        var catalog = 0;
        uint? role = 7;
        var history = new List<(PlayerKnowledgeSnapshot, CompanionReceiveSnapshot, BattleEventSnapshot, SessionEventSnapshot, JsonNode)>();
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            if (step!["operation"] is { } operation)
            {
                if (operation["reset"] is not null)
                {
                    player = PlayerKnowledgeSnapshot.Empty; companions = CompanionReceiveSnapshot.Empty;
                    battle = BattleEventSnapshot.Empty; session = new(); role = 7;
                }
                else if (operation["catalog"] is { } selected) catalog = selected.GetValue<int>();
                else if (operation.AsObject().ContainsKey("role")) role = operation["role"]?.GetValue<uint>();
                else
                {
                    var packet = new Packet(operation["main"]!.GetValue<int>(), operation["sub"]!.GetValue<int>(),
                        Convert.FromHexString(operation["hex"]!.GetValue<string>()));
                    if (step["error"] is { } error)
                    {
                        var exception = Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet, role));
                        Assert.Equal(error.GetValue<string>(), exception.Message);
                    }
                    else
                    {
                        var decoded = ServerProtocol.Decode(packet, role);
                        var result = CombatKnowledgeReceiveReducer.Apply(player, companions, battle, decoded, role, Catalogs[catalog]);
                        player = result.Player;
                        companions = CompanionReceiveReducer.Apply(result.Companions, decoded, role, NpcSkills);
                        battle = BattleEventReducer.Apply(result.Battle, decoded, role);
                        if (decoded is AttributeSetEvent { Entity: not null } attribute && !attribute.Entity.StartsWith("follow:", StringComparison.Ordinal))
                            session = SessionEventReducer.Apply(session, decoded);
                    }
                }
            }
            var expected = step["expected"]!;
            AssertJson(expected, Project(player, companions, battle, session), $"{name}, step {index++}");
            history.Add((player, companions, battle, session, expected));
        }
        foreach (var (oldPlayer, oldCompanions, oldBattle, oldSession, expected) in history)
            AssertJson(expected, Project(oldPlayer, oldCompanions, oldBattle, oldSession), name + " immutable history");
    }

    [Fact]
    public void PythonOracleSourcesMatchByteOnlyCrLfNormalizedHashes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/services/items/combat_resources.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, hash) in JsonNode.Parse(CombatKnowledgePythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName, path))));
    }

    internal static JsonObject Project(PlayerKnowledgeSnapshot player, CompanionReceiveSnapshot companions, BattleEventSnapshot battle, SessionEventSnapshot session)
    {
        var p = new JsonObject { ["ready"] = player.Ready, ["skills"] = JsonSerializer.SerializeToNode(player.Skills, Options),
            ["stats"] = JsonSerializer.SerializeToNode(player.Stats, Options) };
        if (player.ServerSkillRecords is { } records) p["server_skill_records"] = JsonSerializer.SerializeToNode(records, Options);
        if (player.RemovedSkillIds is { } removed) p["removed_skill_ids"] = Strings(removed);
        if (player.Equipment.Equips is { } equips) p["equips"] = Equipment(equips);
        if (player.Equipment.UnresolvedEquips is { } unresolved) p["unresolved_equips"] = new JsonArray([.. unresolved.Select(value => (JsonNode)Item(value))]);
        if (player.Equipment.DeferredEquipUpdates is { } deferred)
            p["deferred_equip_updates"] = new JsonArray([.. deferred.Select(value => JsonSerializer.SerializeToNode(value, value.GetType(), Options))]);
        if (player.Equipment.EquipmentNeedsSnapshot is { } needs) p["equipment_needs_snapshot"] = needs;
        var oldProjection = LiveInventoryParityTests.Project(BagReceiveSnapshot.Empty, companions);
        var profiles = oldProjection["companions"]!.DeepClone().AsObject();
        foreach (var (slot, profile) in companions.Companions)
            if (profile.EquipmentOverrides is { } current) profiles[slot.ToString()]!["equips"] = Equipment(current);
        var units = new JsonObject();
        foreach (var unit in battle.Units)
        {
            var value = JsonSerializer.SerializeToNode(unit.Layout, Options)!.AsObject();
            value["hp"] = unit.Hp; value["sp"] = unit.Sp;
            value["equips"] = JsonSerializer.SerializeToNode(unit.Equips, Options);
            if (!unit.Attributes.IsEmpty) value["attributes"] = JsonSerializer.SerializeToNode(unit.Attributes, Options);
            if (unit.Exited) value["exited"] = true;
            units[unit.Slot.ToString()] = value;
        }
        var attributes = oldProjection["attributes"]!.DeepClone().AsObject();
        foreach (var (key, value) in session.Attributes) attributes[key] = JsonSerializer.SerializeToNode(value, Options);
        return new() { ["player"] = p, ["player_skill_order"] = Strings(player.SkillOrder), ["companions"] = profiles,
            ["companion_order"] = oldProjection["companion_order"]!.DeepClone(), ["units"] = units,
            ["unit_order"] = new JsonArray([.. battle.Units.Select(value => (JsonNode)JsonValue.Create(value.Slot.ToString())!)]),
            ["attributes"] = attributes };
    }

    private static JsonArray Strings(ImmutableArray<uint> values) => new([.. values.Select(value => (JsonNode)JsonValue.Create(value.ToString())!)]);
    internal static JsonArray Equipment(ImmutableArray<KnowledgeEquipment> values) => new([.. values.Select(value =>
    {
        var row = value.OriginalRecord is { } original ? Item(original) : new JsonObject();
        row["item_id"] = value.ItemId;
        if (value.DesignId is { } design) row["design_id"] = design;
        if (value.Damage is { } damage) row["damage"] = damage;
        return (JsonNode)row;
    })]);
    private static JsonObject Item(ItemSave item)
    {
        var row = JsonSerializer.SerializeToNode(item, Options)!.AsObject();
        row["index"] = item.Index;
        return row;
    }
    private static void AssertJson(JsonNode expected, JsonNode actual, string label) =>
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{label}: expected {expected}; actual {actual}");
}
