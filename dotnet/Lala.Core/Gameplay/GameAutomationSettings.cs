using System.Collections.Immutable;
using Lala.Core.Battle;

namespace Lala.Core.Gameplay;

public sealed record GameAutomationSettings
{
    public AutoBattleProfile Player { get; init; } = AutoBattleProfile.PlayerDefaults;
    public AutoBattleProfile Partner { get; init; } = AutoBattleProfile.PartnerDefaults;
    public ImmutableArray<uint> RequiredParty { get; init; } = [];
    public decimal ExpeditionMinHours { get; init; }
    public int ExpeditionMinFaith { get; init; } = 80;
    public int ExpeditionMinSuccess { get; init; } = 75;
    public bool ExpeditionAutoClaim { get; init; } = true;
    public ushort? RestoreItem { get; init; }
    public bool DailyCube { get; init; } = true;
    public bool DailyRewards { get; init; } = true;
    public bool GuildSign { get; init; }
    public bool GuildDonate { get; init; }
    public int DonationSellId { get; init; } = 8;
    public int DonationTarget { get; init; } = 3;
    public int GoldBudget { get; init; } = 450;
    public bool ArkDispatch { get; init; } = true;
    public bool ArkQuestions { get; init; } = true;
    public bool ArkFights { get; init; }
    public int ArkHours { get; init; } = 1;
    public int StarBudget { get; init; } = 120;
    public bool StopOnPlayerDeath { get; init; }
    public bool StopOnPartnerDeath { get; init; }
    public bool FieldHeal { get; init; }
    public bool RepairEnabled {get;init;}
    public int RepairBelow {get;init;}=50;
    public ImmutableArray<ushort> RepairItems {get;init;}=[0,0];
    public bool CleanupEnabled {get;init;}
    public ImmutableArray<ushort> CleanupItems {get;init;}=[..Enumerable.Repeat((ushort)0,15)];
    public FieldRecoverySettings HpRecovery { get; init; } = new() { PlayerPercent = 60, PartnerPercent = 60 };
    public FieldRecoverySettings SpRecovery { get; init; } = new() { PlayerPercent = 30, PartnerPercent = 30 };
    public ImmutableArray<AlchemyIngredient> AlchemyMaterials { get; init; } = [];
    public string AlchemyMode { get; init; } = "none";
    public int AlchemyRuns { get; init; } = 1;
    public ImmutableArray<GameCraftPlanEntry> CraftPlan { get; init; } = [];
    public bool RestartCraftPlan { get; init; }
}
public sealed record GameAutomationStatus(string Kind, bool Enabled, string Message);
