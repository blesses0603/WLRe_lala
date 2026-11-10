using System.Collections.Immutable;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

internal static class GameplayPreferences
{
    internal static GameAutomationSettings Read(DesktopSession session)
    {
        var value = session.Preferences.ReadBattle(session.IdentityKey).Value;
        var expedition = session.Preferences.ReadExpedition(session.IdentityKey);
        var party = value["party_guard"]!;
        return new()
        {
            Player = Profile(BattleSettingsDraft.Profile(value, "player")), Partner = Profile(BattleSettingsDraft.Profile(value, "partner")),
            RequiredParty = BattleSettingsDraft.Bool(party["enabled"]) ? [..((JsonArray)party["members"]!).Select(row => checked((uint)BattleSettingsDraft.Number(row!["role_id"])))] : [],
            ExpeditionMinHours = expedition.MinHours, ExpeditionMinFaith = expedition.MinFaith, ExpeditionMinSuccess = expedition.MinSuccess,
            ExpeditionAutoClaim = expedition.AutoClaim, RestoreItem = expedition.RestoreItemId
            , StopOnPlayerDeath = BattleSettingsDraft.Bool(value["bPlayerDieCloseAI"]), StopOnPartnerDeath = BattleSettingsDraft.Bool(value["bNPCDieCloseAI"])
        };
    }
    private static AutoBattleProfile Profile(JsonObject p) => new()
    {
        DeadEnabled = BattleSettingsDraft.Bool(p["bDeadAction"]), Dead = Action(p["deadAction"]!),
        EnemyHpEnabled = BattleSettingsDraft.Bool(p["bEnemyHPAction"]), EnemyHp = Action(p["enemyHpAction"]!),
        LowHpEnabled = BattleSettingsDraft.Bool(p["bLowHpAction"]), LowHp = Action(p["lowHpAction"]!),
        LowSpEnabled = BattleSettingsDraft.Bool(p["bLowSpAction"]), LowSp = Action(p["lowSpAction"]!),
        RoundEnabled = BattleSettingsDraft.Bool(p["bRoundAction"]), RoundActions = Rows(p["roundAction"]!),
        RepeatEnabled = BattleSettingsDraft.Bool(p["bRepeatAction"]), RepeatActions = Rows(p["repeatAction"]!),
        OrderEnabled = BattleSettingsDraft.Bool(p["bOrderAction"]), OrderActions = Rows(p["orderAction"]!)
    };
    private static ImmutableArray<AutoBattleAction> Rows(JsonNode rows) => [..((JsonArray)rows).Select(row => Action(row!))];
    private static AutoBattleAction Action(JsonNode row) => new()
    {
        Id = BattleSettingsDraft.Int(row["id"]), Kind = (AutoBattleActionKind)BattleSettingsDraft.Int(row["kind"]),
        Target = (AutoBattleTargetPolicy)BattleSettingsDraft.Int(row["target"]),
        Notice = row["notice"] is null ? AutoBattleNotice.SameSide : (AutoBattleNotice)BattleSettingsDraft.Int(row["notice"]),
        Comparison = row["compareKind"] is null ? AutoBattleComparison.GreaterThan : (AutoBattleComparison)BattleSettingsDraft.Int(row["compareKind"]),
        Value = row["value"] is null ? new AutoBattleThreshold(0L) : new AutoBattleThreshold((double)BattleSettingsDraft.Number(row["value"])),
        UseNextSkill = BattleSettingsDraft.Bool(row["bUseNextSkill"])
    };
}
