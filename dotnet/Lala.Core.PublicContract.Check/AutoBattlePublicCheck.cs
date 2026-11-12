using System.Collections.Immutable;
using Lala.Core.Battle;
using Lala.Core.Inventory;

// Compiled and run by the external consumer assembly, which has no friend access.
internal static class AutoBattlePublicCheck
{
    public static void Run()
    {
        var actor = new CombatResourceActor { Pid = 7,Col = 1,Row = 1,Stats = ImmutableDictionary<string,long>.Empty.Add("hp",100),Equips = [new(0),new(0),new(0)] };
        var enemy = new CombatResourceActor { Pid = 101,Col = 3,Row = 1,Stats = ImmutableDictionary<string,long>.Empty.Add("hp",40) };
        var context = new BattleCommandContext
        {
            Resources = new() { LocalRoleId = 7,Units = [new("1:1",actor),new("3:1",enemy)] },
            NormalCatalog = new([KeyValuePair.Create(0,0)],[])
        };
        var rules = new AutoBattleProfile
        {
            LowHpEnabled = false,EnemyHpEnabled = true,
            EnemyHp = new() { Id = 60021,Comparison = AutoBattleComparison.LessThan,Value = 50L },
            RoundEnabled = true,RoundActions = [new() { Id = 60041 }]
        };
        var result = AutoBattleRuleChooser.Choose(context,actor,rules);
        Require(result.Success && result.Reason == AutoBattleReason.EnemyHp && result.ReasonKey == "enemyHpAction");
        Require(result.Intent is { Kind: BattleCommandKind.Defend,ActorPid: 7 } && result.Intent.Allocations.IsEmpty);
        Require(result.ReasonText == "敵方HP條件");
        var fallback = AutoBattleRuleChooser.Choose(context,actor,rules with { EnemyHpEnabled = false,RoundEnabled = false,OrderEnabled = false });
        Require(fallback.Success && fallback.Reason == AutoBattleReason.Fallback && fallback.Intent is { TargetCol: 3,TargetRow: 1 });
        Require(context.Round == 0 && !context.Active && context.Resources.Inventory.Reserved.IsEmpty && context.Resources.Inventory.Holds.IsEmpty);
        Require(actor.Hp == 100 && enemy.Hp == 40 && rules.RoundActions.Length == 1);
        Console.WriteLine("Public pure AutoBattle chooser contract passed; synthetic observations only.");
    }
    private static void Require(bool condition) { if (!condition) throw new InvalidOperationException("AutoBattle public contract failed."); }
}
