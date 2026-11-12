using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatActionCandidateParityTests
{
    [Theory]
    [MemberData(nameof(CombatActionCandidatePythonVectors.Cases),MemberType = typeof(CombatActionCandidatePythonVectors))]
    public void PureCandidatesMatchPythonOrRejectUnsupportedResourceKeys(int caseId,string json)
    {
        var input = JsonNode.Parse(json)!;
        var context = Context(input); var actor = Actor(input["actor"]!); var normal = Normal(input["normal"]!);
        var beforeBag = LiveInventoryParityTests.Project(context.Inventory,context.Companions).ToJsonString();
        var beforePlayer = JsonSerializer.Serialize(context.Player); var beforeActor = JsonSerializer.Serialize(actor);
        var beforeCatalog = JsonSerializer.Serialize(context.Catalog); var beforeUnits = JsonSerializer.Serialize(context.Units);
        var unsupportedResource = input["kind"]!.GetValue<string>() == "food" &&
            (input["args"]!["resource"]?.GetValue<string>() ?? "hp") is not ("hp" or "sp");
        Assert.Equal(unsupportedResource,input["typed_resource_rejection"]!.GetValue<bool>());
        if (unsupportedResource)
        {
            // Preserve the real Python observation in the fixture, but explicitly verify
            // the documented typed-domain rejection rather than claim string-error parity.
            Assert.Equal("resource",Assert.Throws<ArgumentException>(() => Run(input,context,actor,normal)).ParamName);
        }
        else
        {
            var result = Run(input,context,actor,normal);
            LazyAssert.True(JsonNode.DeepEquals(input["expected"],Project(result)), () => $"Case {caseId}\nExpected: {input["expected"]}\nActual: {Project(result)}\nInput: {input}");
        }
        Assert.Equal(beforeBag,LiveInventoryParityTests.Project(context.Inventory,context.Companions).ToJsonString());
        Assert.Equal(beforePlayer,JsonSerializer.Serialize(context.Player)); Assert.Equal(beforeActor,JsonSerializer.Serialize(actor));
        Assert.Equal(beforeCatalog,JsonSerializer.Serialize(context.Catalog)); Assert.Equal(beforeUnits,JsonSerializer.Serialize(context.Units));
    }

    [Fact]
    public void SourceHashesNormalizeOnlyCrLfBytes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName,"wlre/services/items/combat_resources.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path,hash) in CombatActionCandidatePythonVectors.Read()["source_sha256"]!.AsObject())
            Assert.Equal(hash!.GetValue<string>(),LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName,path))));
    }

    internal static CombatResourceActionCandidate Run(JsonNode input,CombatResourceActionContext context,CombatResourceActor actor,NormalAttackCatalogSnapshot normal)
    {
        var args = input["args"]!; var slot = args["target_slot"]?.GetValue<string>(); var kind = args["target_kind"]?.GetValue<int>() ?? 1;
        return input["kind"]!.GetValue<string>() switch
        {
            "learned" => CombatResourceActionCandidates.Learned(context,actor,args["sid"]?.GetValue<uint>() ?? 1001,slot,kind,args["next_skill"]?.GetValue<bool>() ?? false),
            "best" => CombatResourceActionCandidates.BestSkill(context,actor,normal,slot,kind),
            "food" => CombatResourceActionCandidates.Food(context,actor,args["resource"]?.GetValue<string>() ?? "hp",args["item_id"]?.GetValue<ushort>(),slot,
                args["field"]?.GetValue<bool>() ?? false,args["index"]?.GetValue<int>()),
            _ => throw new InvalidOperationException()
        };
    }

    internal static CombatResourceActionContext Context(JsonNode input)
    {
        var state = input["state"]!; var raw = input["catalog"]!;
        var catalog = CombatResourceParityTests.Catalog(raw);
        catalog = catalog with
        {
            Items = catalog.Items.ToImmutableDictionary(pair => pair.Key,pair => pair.Value with { Restrict = raw["items"]![pair.Key.ToString(CultureInfo.InvariantCulture)]?["restrict"]?.GetValue<long>() ?? 0 }),
            ElementWeights = raw["element_weights"]!.AsObject().ToImmutableDictionary(pair => long.Parse(pair.Key,CultureInfo.InvariantCulture),
                pair => pair.Value!.AsObject().ToImmutableDictionary(weight => long.Parse(weight.Key,CultureInfo.InvariantCulture),weight => weight.Value!.GetValue<double>()))
        };
        return new()
        {
            LocalRoleId = state["player"]?["role_id"]?.GetValue<uint>(),
            Player = CombatResourceParityTests.Player(state["knowledge"]!["player"]),
            Companions = CombatResourceParityTests.Companions(state["knowledge"]!["companions"],null),
            Inventory = LiveInventoryParityTests.ReadBag(state["inventory"]!),
            InventoryContext = new() { ItemNames = input["names"]!.AsObject().ToImmutableDictionary(pair => BigInteger.Parse(pair.Key,CultureInfo.InvariantCulture),pair => pair.Value!.GetValue<string>()) },
            Catalog = catalog, WarStyle = state["battle"]?["war_style"]?.GetValue<long>(),
            Units = [.. state["battle_units"]!.AsObject().Select(pair => new CombatResourceBattleEntry(pair.Key,Actor(pair.Value!)))]
        };
    }
    internal static CombatResourceActor Actor(JsonNode input)
    {
        var actor = CombatResourceParityTests.Actor(input);
        return actor with { Stats = input["element"] is { } element ? actor.Stats.SetItem("element",element.GetValue<long>()) : actor.Stats,
            ChangeBodyId = input["change_body_id"]?.GetValue<uint>() ?? 0 };
    }
    internal static NormalAttackCatalogSnapshot Normal(JsonNode input) => new(
        input["items"]!.AsObject().Select(pair => KeyValuePair.Create(int.Parse(pair.Key,CultureInfo.InvariantCulture),pair.Value!.GetValue<int>())),
        input["npcs"]!.AsObject().Select(pair => KeyValuePair.Create(uint.Parse(pair.Key,CultureInfo.InvariantCulture),new NormalAttackNpc(
            pair.Value!["kind"]!.GetValue<int>(),pair.Value["bodyType"]!.GetValue<int>(),pair.Value["normalAttackKind"]!.GetValue<int>()))));
    internal static JsonObject Project(CombatResourceActionCandidate result)
    {
        JsonObject? action = null;
        if (result.Intent is { } intent)
        {
            action = new()
            {
                ["type"] = intent.Kind switch { CombatResourceActionKind.LearnedSkill => "learned_action",CombatResourceActionKind.NormalAttack => "battle_action",CombatResourceActionKind.BattleItem => "battle_item",_ => "field_item" },
                ["col"] = intent.Col,["row"] = intent.Row,["actor_pid"] = intent.ActorPid,["target_col"] = intent.TargetCol,["target_row"] = intent.TargetRow
            };
            if (intent.SkillId is { } skill) action["skill_id"] = skill;
            if (intent.Kind == CombatResourceActionKind.NormalAttack) action["mode"] = "normal";
            else action["resource_reservations"] = new JsonArray([.. intent.Allocations.Select(row => (JsonNode)new JsonObject
                { ["index"] = row.Index,["item_id"] = JsonNode.Parse(row.ItemId.ToString(CultureInfo.InvariantCulture)),["count"] = JsonNode.Parse(row.Count.ToString(CultureInfo.InvariantCulture)) })]);
            if (intent.ItemId is { } item) action["item_id"] = item;
            if (intent.BagIndex is { } index) action["bag_index"] = index;
            if (intent.Resource is { } resource) action["resource"] = resource;
        }
        return new() { ["action"] = action,["error"] = result.Error is { } error ? new JsonObject { ["type"] = error.Type,["message"] = error.Message } : null };
    }
}
