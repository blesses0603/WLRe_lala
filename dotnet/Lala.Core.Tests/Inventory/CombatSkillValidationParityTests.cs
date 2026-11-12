using System.Collections.Immutable;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatSkillValidationParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    [Theory]
    [MemberData(nameof(CombatSkillValidationPythonVectors.Cases), MemberType = typeof(CombatSkillValidationPythonVectors))]
    public void PureSkillDiagnosticsAndDisplayRowsMatchRealPython(string kind,string json)
    {
        var input = JsonNode.Parse(json)!; var state = input["state"]!;
        var catalog = CombatResourceParityTests.Catalog(input["catalog"]!);
        var player = CombatResourceParityTests.Player(state["knowledge"]!["player"]);
        var companions = CombatResourceParityTests.Companions(state["knowledge"]!["companions"],null);
        var actor = CombatResourceParityTests.Actor(input["actor"]);
        var role = state["player"]?["role_id"]?.GetValue<uint>();
        var bag = LiveInventoryParityTests.ReadBag(state["inventory"]!);
        var context = new InventoryPlanningContext { ItemNames = input["names"]!.AsObject()
            .ToImmutableDictionary(p => BigInteger.Parse(p.Key),p => p.Value!.GetValue<string>()) };
        var beforeBag = LiveInventoryParityTests.Project(bag,CompanionReceiveSnapshot.Empty).ToJsonString();
        var beforeActor = JsonSerializer.Serialize(actor,Options); var beforePlayer = JsonSerializer.Serialize(player,Options);
        var result = kind == "reasons" ? JsonSerializer.SerializeToNode(
            CombatResourceKnowledge.SkillReasons(player,companions,role,actor,input["skill_id"]!.GetValue<uint>(),catalog,bag,context),Options) :
            JsonSerializer.SerializeToNode(CombatResourceKnowledge.SkillRows(player,companions,role,actor,catalog,bag,context),Options);
        LazyAssert.True(JsonNode.DeepEquals(input["expected"],result), () => $"{kind}\nExpected: {input["expected"]}\nActual: {result}\nInput: {input}");
        Assert.Equal(beforeBag,LiveInventoryParityTests.Project(bag,CompanionReceiveSnapshot.Empty).ToJsonString());
        Assert.Equal(beforeActor,JsonSerializer.Serialize(actor,Options)); Assert.Equal(beforePlayer,JsonSerializer.Serialize(player,Options));
    }

    [Fact]
    public void OracleSourcesUseByteOnlyCrLfNormalizedHashes()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName,"wlre/services/items/combat_resources.py"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path,hash) in JsonNode.Parse(CombatSkillValidationPythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(),LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(root.FullName,path))));
    }
}
