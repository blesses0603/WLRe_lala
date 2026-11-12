using System.Collections.Immutable;

namespace Lala.Core.Catalogs;

public sealed record ExpeditionRecommendation(ImmutableArray<ushort> Condition, ushort Bonus);
public sealed record ExpeditionReward(byte Kind, uint Id, uint Value);
public sealed record ExpeditionTaskData(ushort Id, byte Area, uint AreaName, byte Difficulty,
    uint NameId, uint DescriptionId, ushort Minutes, byte FaithCost, ushort SuccessRate,
    ImmutableArray<ushort> Condition, ImmutableArray<ExpeditionRecommendation> Recommendations,
    uint ExpeditionExp, ImmutableArray<ExpeditionReward> Rewards, ushort SpecialRate,
    ExpeditionReward SpecialReward, int Exp, string? Name = null, string? AreaLabel = null);
public sealed record ExpeditionLevelData(byte Teams, byte Difficulty, ushort Reduction);
public sealed record ExpeditionNpcData(byte Element, byte Kind, ushort Original);

/// <summary>Owned, immutable offline rows and content digests. Digests are not source authority.</summary>
public sealed class ExpeditionCatalogData
{
    internal ExpeditionCatalogData(IReadOnlyDictionary<ushort, ExpeditionTaskData> tasks,
        IReadOnlyDictionary<byte, ExpeditionLevelData> levels, IReadOnlyDictionary<string, string> hashes)
        => (Tasks, Levels, SourceSha256) = (tasks, levels, hashes);
    public IReadOnlyDictionary<ushort, ExpeditionTaskData> Tasks { get; }
    public IReadOnlyDictionary<byte, ExpeditionLevelData> Levels { get; }
    public IReadOnlyDictionary<string, string> SourceSha256 { get; }
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    public bool RuntimeAdmitted => false;
}

/// <summary>Only six supplied raw tables. This is not the ten-table runtime or verified source provenance.</summary>
public sealed class OfflineRuntimeTableData
{
    internal OfflineRuntimeTableData(IReadOnlyDictionary<ushort, TalkDataRow> talks,
        IReadOnlyDictionary<uint, string> texts, ExpeditionCatalogData expedition,
        IReadOnlyDictionary<ushort, ExpeditionNpcData> npcs)
        => (Talks, Texts, Expedition, Npcs) = (talks, texts, expedition, npcs);
    public IReadOnlyDictionary<ushort, TalkDataRow> Talks { get; }
    public IReadOnlyDictionary<uint, string> Texts { get; }
    public ExpeditionCatalogData Expedition { get; }
    public IReadOnlyDictionary<ushort, ExpeditionNpcData> Npcs { get; }
    public string SourceKind => "supplied_offline_tables";
    public bool HasVerifiedProvenance => false;
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    public bool RuntimeAdmitted => false;
}
