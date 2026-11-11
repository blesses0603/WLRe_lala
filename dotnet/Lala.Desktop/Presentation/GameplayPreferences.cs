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
        var assistant = session.Preferences.ReadAssistant(session.IdentityKey);
        return new()
        {
            Player = Profile(BattleSettingsDraft.Profile(value, "player")), Partner = Profile(BattleSettingsDraft.Profile(value, "partner")),
            FieldHeal = BattleSettingsDraft.Bool(value["field_heal"]), HpRecovery = Recovery(value["recovery"]!["hp"]!), SpRecovery = Recovery(value["recovery"]!["sp"]!),
            RepairEnabled=BattleSettingsDraft.Bool(value["maintenance"]!["repair_enabled"]),RepairBelow=BattleSettingsDraft.Int(value["maintenance"]!["repair_below"]),
            RepairItems=[..((JsonArray)value["maintenance"]!["repair_items"]!).Select(v=>checked((ushort)BattleSettingsDraft.Int(v)))],
            CleanupEnabled=BattleSettingsDraft.Bool(value["maintenance"]!["cleanup_enabled"]),CleanupItems=[..((JsonArray)value["maintenance"]!["cleanup_items"]!).Select(v=>checked((ushort)BattleSettingsDraft.Int(v)))],
            RequiredParty = BattleSettingsDraft.Bool(party["enabled"]) ? [..((JsonArray)party["members"]!).Select(row => checked((uint)BattleSettingsDraft.Number(row!["role_id"])))] : [],
            ExpeditionMinHours = expedition.MinHours, ExpeditionMinFaith = expedition.MinFaith, ExpeditionMinSuccess = expedition.MinSuccess,
            ExpeditionAutoClaim = expedition.AutoClaim, RestoreItem = expedition.RestoreItemId,
            DailyCube = assistant.Cube, DailyRewards = assistant.Rewards, GuildSign = assistant.GuildSign, GuildDonate = assistant.GuildDonate,
            DonationSellId = assistant.DonationPlan, DonationTarget = assistant.DonationTarget, GoldBudget = assistant.GoldBudget,
            ArkDispatch = assistant.ArkDispatch, ArkQuestions = assistant.ArkQuestions, ArkFights = assistant.ArkFights, ArkHours = assistant.ArkHours, StarBudget = assistant.StarBudget,
            StopOnPlayerDeath = BattleSettingsDraft.Bool(value["bPlayerDieCloseAI"]), StopOnPartnerDeath = BattleSettingsDraft.Bool(value["bNPCDieCloseAI"])
        };
    }
    private static FieldRecoverySettings Recovery(JsonNode config) => new()
    {
        Enabled = BattleSettingsDraft.Bool(config["enabled"]), OtherItems = BattleSettingsDraft.Bool(config["other_items"]),
        Storage = config["storage"]!.GetValue<string>(), PlayerPercent = BattleSettingsDraft.Int(config["player_percent"]), PartnerPercent = BattleSettingsDraft.Int(config["partner_percent"]),
        Items = [..((JsonArray)config["items"]!).Select(v => checked((ushort)BattleSettingsDraft.Int(v)))]
    };
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
