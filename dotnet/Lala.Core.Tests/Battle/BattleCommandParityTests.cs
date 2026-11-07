using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Tests.Inventory;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class BattleCommandParityTests
{
    private static readonly JsonSerializerOptions SnapshotOptions = new() { Converters = { new ExactIntegerConverter() } };
    private sealed class ExactIntegerConverter : JsonConverter<BigInteger>
    {
        public override BigInteger Read(ref Utf8JsonReader reader,Type typeToConvert,JsonSerializerOptions options) => throw new NotSupportedException();
        public override void Write(Utf8JsonWriter writer,BigInteger value,JsonSerializerOptions options) => writer.WriteRawValue(value.ToString(CultureInfo.InvariantCulture));
        public override void WriteAsPropertyName(Utf8JsonWriter writer,BigInteger value,JsonSerializerOptions options) => writer.WritePropertyName(value.ToString(CultureInfo.InvariantCulture));
    }

    [Theory]
    [MemberData(nameof(BattleCommandPythonVectors.Cases),MemberType = typeof(BattleCommandPythonVectors))]
    public void PureRoundAndActionSelectionMatchRetainedPython(int caseId,string json)
    {
        var input = JsonNode.Parse(json)!; var context = Context(input); var actor = Actor(input["actor"]!); var target = Actor(input["target"]!);
        var before = JsonSerializer.Serialize(context,SnapshotOptions); var beforeActor = JsonSerializer.Serialize(actor); var beforeTarget = JsonSerializer.Serialize(target);
        var typed = input["kind"]!.GetValue<string>() switch
        {
            "identity" when actor.Pid is null => "identity_missing_pid",
            "action" when actor.Pid is null && input["args"]!["mode"]!.GetValue<string>() == "defend" => "action_missing_pid",
            "action" when actor.Pid is null && input["args"]!["mode"]!.GetValue<string>() is "heal_hp" or "heal_sp" &&
                CombatResourceActionCandidates.Food(context.Resources,actor,input["args"]!["mode"]!.GetValue<string>() == "heal_hp" ? "hp" : "sp").Success => "action_missing_pid",
            "action" when actor.Pid is null && input["args"]!["mode"]!.GetValue<string>() == "auto_skill" &&
                CombatResourceActionCandidates.BestSkill(context.Resources,actor,context.NormalCatalog).Success => "action_missing_pid",
            "owned" when context.Resources.Units.Any(row => row.Actor.Pid is null && row.Actor.MasterId == context.Resources.LocalRoleId) => "owned_missing_pid",
            "catch" when context.Resources.LocalRoleId is null => "capture_missing_role",
            _ => null
        };
        Assert.Equal(typed,input["typed_rejection"]?.GetValue<string>());
        if (typed is not null) Assert.Throws<ArgumentException>(() => Run(input,context,actor,target));
        else
        {
            var result = Run(input,context,actor,target);
            Assert.True(JsonNode.DeepEquals(input["expected"],result),$"Case {caseId}: {input["label"]}\nExpected: {input["expected"]}\nActual: {result}\nInput: {input}");
        }
        Assert.Equal(before,JsonSerializer.Serialize(context,SnapshotOptions)); Assert.Equal(beforeActor,JsonSerializer.Serialize(actor)); Assert.Equal(beforeTarget,JsonSerializer.Serialize(target));
    }

    [Fact]
    public void SourceHashesNormalizeOnlyCrLfBytes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName,"wlre/services/battle/battle_commands.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path,hash) in BattleCommandPythonVectors.Read()["source_sha256"]!.AsObject())
            Assert.Equal(hash!.GetValue<string>(),LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName,path))));
    }

    internal static BattleCommandContext Context(JsonNode input)
    {
        var resources = CombatActionCandidateParityTests.Context(input);
        var state = input["state"]!; var normal = input["normal"]!;
        return new()
        {
            Resources = resources with { Units = [.. state["battle_units"]!.AsObject().Select(pair => new CombatResourceBattleEntry(pair.Key,Actor(pair.Value!)))] },
            NormalCatalog = CombatActionCandidateParityTests.Normal(normal),
            CaptureCatalog = new()
            {
                CatchableNpcs = normal["npcs"]!.AsObject().ToImmutableDictionary(pair => uint.Parse(pair.Key,CultureInfo.InvariantCulture),pair => pair.Value!["canCatch"]?.GetValue<bool>() ?? false),
                NetBonuses = normal["catch_nets"]!.AsObject().ToImmutableDictionary(pair => ushort.Parse(pair.Key,CultureInfo.InvariantCulture),pair => pair.Value!.GetValue<long>())
            },
            Active = state["battle"]?["active"]?.GetValue<bool>() ?? false,
            Round = state["battle"]?["round"]?.GetValue<long>() ?? 0,
            CommandedSlots = [.. (state["battle"]?["commands"]?.AsObject() ?? []).Select(pair => pair.Key)]
        };
    }
    internal static CombatResourceActor Actor(JsonNode input)
    {
        var actor = CombatActionCandidateParityTests.Actor(input);
        foreach (var key in new[] {"level","degree"})
            if (input[key] is { } value) actor = actor with { Stats = actor.Stats.SetItem(key,value.GetValue<long>()) };
        return actor;
    }
    private static JsonObject Run(JsonNode input,BattleCommandContext context,CombatResourceActor actor,CombatResourceActor target)
    {
        var args = input["args"]!; var slot = args["target_slot"]?.GetValue<string>();
        switch (input["kind"]!.GetValue<string>())
        {
            case "round":
                return Project(BattleCommandPlanner.PlanRound(context,
                    args["modes"]?.AsObject().ToDictionary(pair => pair.Key,pair => pair.Value!.GetValue<string>()),slot,
                    args["excluded"]?.AsArray().Select(value => value!.GetValue<string>())));
            case "action":
                var action = BattleCommandPlanner.Action(context,actor,args["mode"]!.GetValue<string>(),slot);
                return Result(action.Intent is { } intent ? Project(intent) : null,action.Error);
            case "catch": return Result(JsonValue.Create(BattleCommandPlanner.CatchAllowed(context,actor,target)));
            case "slot": return Result(JsonValue.Create(BattleCommandPlanner.Slot(actor)));
            case "identity":
                var identity = BattleCommandPlanner.Identity(actor);return Result(new JsonArray(JsonValue.Create(identity.Pid),JsonValue.Create(identity.MasterId)));
            case "owned":
                var owned = BattleCommandPlanner.OwnedUnits(context.Resources,args["living"]?.GetValue<bool>() ?? true);
                return Result(new JsonArray([.. owned.Select(unit => (JsonNode)JsonValue.Create(context.Resources.Units.First(entry => ReferenceEquals(entry.Actor,unit)).Slot)!)]));
            default: throw new InvalidOperationException();
        }
    }
    internal static JsonObject Project(BattleRoundPlan result) => Result(result.Success ? new JsonArray([.. result.Intents.Select(value => (JsonNode)Project(value))]) : null,result.Error);
    private static JsonObject Result(JsonNode? value,InventoryPlanningError? error = null) => new()
    {
        ["value"] = value,["error"] = error is null ? null : new JsonObject { ["type"] = error.Type,["message"] = error.Message }
    };
    internal static JsonObject Project(BattleCommandIntent intent)
    {
        var action = new JsonObject
        {
            ["type"] = intent.Kind switch { BattleCommandKind.LearnedSkill => "learned_action",BattleCommandKind.BattleItem => "battle_item",_ => "battle_action" },
            ["col"] = intent.Col,["row"] = intent.Row,["actor_pid"] = intent.ActorPid,["target_col"] = intent.TargetCol,["target_row"] = intent.TargetRow
        };
        if (intent.SkillId is { } skill) action["skill_id"] = skill;
        if (intent.Kind is BattleCommandKind.Normal or BattleCommandKind.Defend or BattleCommandKind.Escape or BattleCommandKind.Catch)
            action["mode"] = intent.Kind.ToString().ToLowerInvariant();
        else action["resource_reservations"] = new JsonArray([.. intent.Allocations.Select(row => (JsonNode)new JsonObject
            { ["index"] = row.Index,["item_id"] = JsonNode.Parse(row.ItemId.ToString(CultureInfo.InvariantCulture)),["count"] = JsonNode.Parse(row.Count.ToString(CultureInfo.InvariantCulture)) })]);
        if (intent.ItemId is { } item) action["item_id"] = item;
        if (intent.BagIndex is { } index) action["bag_index"] = index;
        if (intent.Resource is { } resource) action["resource"] = resource;
        return action;
    }
}
