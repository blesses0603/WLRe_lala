using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Tests.Inventory;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class AutoBattleParityTests
{
    [Theory]
    [MemberData(nameof(AutoBattlePythonVectors.Cases),MemberType = typeof(AutoBattlePythonVectors))]
    public void ActualRetainedPythonChooserMatchesWithoutMutatingInputs(int caseId,string json)
    {
        var input = JsonNode.Parse(json)!;var context = BattleCommandParityTests.Context(input);
        var actor = BattleCommandParityTests.Actor(input["actor"]!);var profile = Profile(input["profile"]!);
        var beforeBag = LiveInventoryParityTests.Project(context.Resources.Inventory,context.Resources.Companions).ToJsonString();
        var beforePlayer = JsonSerializer.Serialize(context.Resources.Player);var beforeUnits = JsonSerializer.Serialize(context.Resources.Units);
        var beforeActor = JsonSerializer.Serialize(actor);var beforeCatalog = JsonSerializer.Serialize(context.Resources.Catalog);var beforeProfile = JsonSerializer.Serialize(profile);
        var result = AutoBattleRuleChooser.Choose(context,actor,profile);
        var actual = Project(result);
        LazyAssert.True(JsonNode.DeepEquals(input["expected"],actual),() => $"Case {caseId}: {input["label"]}\nExpected: {input["expected"]}\nActual: {actual}\nInput: {input}");
        Assert.Equal(result.Success,result.Reason is not null);Assert.Equal(result.Success,result.ReasonKey is not null);
        Assert.Equal(beforeBag,LiveInventoryParityTests.Project(context.Resources.Inventory,context.Resources.Companions).ToJsonString());
        Assert.Equal(beforePlayer,JsonSerializer.Serialize(context.Resources.Player));Assert.Equal(beforeUnits,JsonSerializer.Serialize(context.Resources.Units));
        Assert.Equal(beforeActor,JsonSerializer.Serialize(actor));Assert.Equal(beforeCatalog,JsonSerializer.Serialize(context.Resources.Catalog));Assert.Equal(beforeProfile,JsonSerializer.Serialize(profile));
    }

    [Fact]
    public void SourceHashesNormalizeOnlyCrLfBytes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName,"wlre/services/battle/auto_battle.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path,hash) in AutoBattlePythonVectors.Read()["source_sha256"]!.AsObject())
            Assert.Equal(hash!.GetValue<string>(),LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName,path))));
    }
    internal static JsonObject Project(AutoBattleChoice result) => new()
    {
        ["action"] = result.Intent is { } intent ? BattleCommandParityTests.Project(intent) : null,
        ["reason"] = result.ReasonText,
        ["error"] = result.Error is { } error ? new JsonObject { ["type"] = error.Type,["message"] = error.Message } : null
    };
    internal static AutoBattleProfile Profile(JsonNode input) => new()
    {
        DeadEnabled = input["bDeadAction"]!.GetValue<bool>(),Dead = Action(input["deadAction"]!),
        EnemyHpEnabled = input["bEnemyHPAction"]!.GetValue<bool>(),EnemyHp = Action(input["enemyHpAction"]!),
        LowHpEnabled = input["bLowHpAction"]!.GetValue<bool>(),LowHp = Action(input["lowHpAction"]!),
        LowSpEnabled = input["bLowSpAction"]!.GetValue<bool>(),LowSp = Action(input["lowSpAction"]!),
        RoundEnabled = input["bRoundAction"]!.GetValue<bool>(),RoundActions = Rows(input["roundAction"]!),
        RepeatEnabled = input["bRepeatAction"]!.GetValue<bool>(),RepeatActions = Rows(input["repeatAction"]!),
        OrderEnabled = input["bOrderAction"]!.GetValue<bool>(),OrderActions = Rows(input["orderAction"]!)
    };
    private static ImmutableArray<AutoBattleAction> Rows(JsonNode input) => [.. input.AsArray().Select(row => Action(row!))];
    private static AutoBattleAction Action(JsonNode input) => new()
    {
        Id = input["id"]!.GetValue<int>(),Kind = (AutoBattleActionKind)input["kind"]!.GetValue<int>(),Target = (AutoBattleTargetPolicy)input["target"]!.GetValue<int>(),
        Notice = (AutoBattleNotice)(input["notice"]?.GetValue<int>() ?? 1),Comparison = (AutoBattleComparison)(input["compareKind"]?.GetValue<int>() ?? 1),
        Value = input["value"] is JsonValue value ? value.TryGetValue<long>(out var integer) ? new(integer) : new(value.GetValue<double>()) : default,
        UseNextSkill = input["bUseNextSkill"]?.GetValue<bool>() ?? false
    };
}
