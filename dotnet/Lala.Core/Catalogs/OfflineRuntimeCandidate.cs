using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.World.Eve;
using Lala.Core.World.Portals;

namespace Lala.Core.Catalogs;

/// <summary>
/// Immutable structural composition of ten supplied table payloads. Neither this object nor its
/// hashes establish official provenance, fresh-source stability, database admission or readiness.
/// Optional skills and NPC metadata require reviewed bytes; event/convey observations never authorize routes or packets.
/// </summary>
public sealed class OfflineRuntimeCandidate
{
    internal OfflineRuntimeCandidate(EveV115Indexes indexes, IReadOnlyDictionary<ushort, ItemDataRow> items,
        IReadOnlyDictionary<ushort, TalkDataRow> talks, IReadOnlyDictionary<uint, string> texts,
        RuntimeRecipeCandidate recipes, IReadOnlyDictionary<ushort, StageDataRow> stages,
        EveDoorProjection doors, IReadOnlyDictionary<ushort, string> sceneNames,
        ExpeditionCatalogData expedition, IReadOnlyDictionary<ushort, ExpeditionNpcData> npcs,
        IReadOnlyDictionary<string, string> hashes, OfflineRuntimePortalObservations portalObservations,
        IReadOnlyDictionary<ushort, SkillDataRow>? optionalSkills = null,
        DailyTaskCatalogPreview? optionalDailyCatalog = null, InstanceCatalogPreview? optionalInstances = null,
        ImmutableDictionary<uint, CombatResourceNpc>? reviewedNpcs = null)
        => (EveIndexes, Items, Talks, Texts, Recipes, Stages, Doors, SceneNames, Expedition, Npcs, SourceSha256, PortalObservations, OptionalSkills, OptionalDailyCatalog, OptionalInstances, ReviewedNpcs) =
            (indexes, items, talks, texts, recipes, stages, doors, sceneNames, expedition, npcs, hashes, portalObservations, optionalSkills, optionalDailyCatalog, optionalInstances, reviewedNpcs);
    /// <summary>Reviewed optional skill rows, or null when missing, unsupported or not read back.
    /// Point-in-time catalog data only; never command authority.</summary>
    public IReadOnlyDictionary<ushort, SkillDataRow>? OptionalSkills { get; }
    internal OfflineRuntimeCandidate WithOptionalSkills(ReadOnlySpan<byte> raw, CancellationToken token)
        => CopyWithSkills(SkillDataParser.Parse(raw, token));
    internal OfflineRuntimeCandidate WithoutOptionalSkills() => CopyWithSkills(null);
    private OfflineRuntimeCandidate CopyWithSkills(IReadOnlyDictionary<ushort, SkillDataRow>? skills)
        => new(EveIndexes, Items, Talks, Texts, Recipes, Stages, Doors, SceneNames, Expedition, Npcs,
            SourceSha256, PortalObservations, skills, OptionalDailyCatalog, OptionalInstances, ReviewedNpcs);
    /// <summary>Same-version daily/weekly definitions, or null if either optional table or
    /// its cross-references are unavailable. No planner input token or command authority.</summary>
    public DailyTaskCatalogPreview? OptionalDailyCatalog { get; }
    internal OfflineRuntimeCandidate WithOptionalDailyCatalog(ReadOnlySpan<byte> tasks, ReadOnlySpan<byte> rewards,
        CancellationToken token)
    {
        var catalog = DailyTaskCatalogBinder.Bind(DailyTaskDataParser.ParseTasks(tasks, token),
            DailyTaskDataParser.ParseRewards(rewards, token),
            Texts.ToDictionary(pair => pair.Key, pair => (string?)pair.Value),
            Items.Keys.Select(id => (uint)id).ToHashSet(), token);
        return CopyWithDailyCatalog(catalog);
    }
    internal OfflineRuntimeCandidate WithoutOptionalDailyCatalog() => CopyWithDailyCatalog(null);
    private OfflineRuntimeCandidate CopyWithDailyCatalog(DailyTaskCatalogPreview? catalog)
        => new(EveIndexes, Items, Talks, Texts, Recipes, Stages, Doors, SceneNames, Expedition, Npcs,
            SourceSha256, PortalObservations, OptionalSkills, catalog, OptionalInstances, ReviewedNpcs);
    /// <summary>Same-version dungeon/co-op definitions. Null means unavailable; entries
    /// and declared normal-dungeon maps are read-only observations, never room/entry permission.</summary>
    public InstanceCatalogPreview? OptionalInstances { get; }
    internal OfflineRuntimeCandidate WithOptionalInstances(ReadOnlySpan<byte> dungeons, ReadOnlySpan<byte> cooperative,
        CancellationToken token)
        => CopyWithInstances(InstanceCatalogParser.Bind(dungeons, cooperative, Stages,
            Texts.ToDictionary(pair => pair.Key, pair => (string?)pair.Value),
            Items.Keys.Select(id => (uint)id).ToHashSet(), token));
    internal OfflineRuntimeCandidate WithoutOptionalInstances() => CopyWithInstances(null);
    private OfflineRuntimeCandidate CopyWithInstances(InstanceCatalogPreview? catalog)
        => new(EveIndexes, Items, Talks, Texts, Recipes, Stages, Doors, SceneNames, Expedition, Npcs,
            SourceSha256, PortalObservations, OptionalSkills, OptionalDailyCatalog, catalog, ReviewedNpcs);
    public EveV115Indexes EveIndexes { get; }
    public IReadOnlyDictionary<ushort, ItemDataRow> Items { get; }
    public IReadOnlyDictionary<ushort, TalkDataRow> Talks { get; }
    public IReadOnlyDictionary<uint, string> Texts { get; }
    public RuntimeRecipeCandidate Recipes { get; }
    public IReadOnlyDictionary<ushort, StageDataRow> Stages { get; }
    public EveDoorProjection Doors { get; }
    public OfflineRuntimePortalObservations PortalObservations { get; }
    public IReadOnlyDictionary<ushort, string> SceneNames { get; }
    public ExpeditionCatalogData Expedition { get; }
    public IReadOnlyDictionary<ushort, ExpeditionNpcData> Npcs { get; }
    /// <summary>Names and five skill slots from the fixed reviewed NpcData digest, or null for
    /// unsupported bytes. Derived from required source bytes, never a separate optional table.
    /// Point-in-time observations only; not source provenance or command permission.</summary>
    public ImmutableDictionary<uint, CombatResourceNpc>? ReviewedNpcs { get; }
    public IReadOnlyDictionary<string, string> SourceSha256 { get; }
    public string SourceKind => "supplied_offline_tables";
    public bool RequiredTablesStructurallyComplete => true;
    public bool HasVerifiedProvenance => false;
    public bool RuntimeAdmitted => false;
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    public ImmutableArray<string> UnavailableOptionalSources =>
        [.. (OptionalSkills is null ? new[] { "SkillData" } : Array.Empty<string>()), "portal_metadata", "images",
            .. (OptionalDailyCatalog is null ? new[] { "daily" } : Array.Empty<string>()), "guild", "Ark", "combat", "normal_attacks",
            "portraits", "emoji", "smallmaps", "battle_talk",
            .. (OptionalInstances is null ? new[] { "instances" } : Array.Empty<string>())];
}

/// <summary>
/// Dynamic-branch structural bindings only, without verified-context input, cache, source admission
/// or installation. Does not implement static 1275 fixed hash/count runtime admission. ItemData's
/// reviewed package/version digest checks remain mandatory and cannot be supplied by callers.
/// </summary>
public static class OfflineRuntimeCandidateDecoder
{
    public const int MaxSourceBytes = 16 * 1024 * 1024;
    public static ImmutableArray<string> Sources { get; } =
        ["Eve", "ItemData_C", "TalkData_C", "TextData_C", "SmithData_C", "ScenesData_C",
            "AdventureData_C", "AdventureLvData_C", "NpcData_C", "NpcCareerData_C"];

    public static OfflineRuntimeCandidate Decode(IReadOnlyDictionary<string, ReadOnlyMemory<byte>> supplied,
        string packageVersion, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(supplied);
        ArgumentNullException.ThrowIfNull(packageVersion);
        // The source extracts all ten assets before parsing any table. Snapshot every required
        // payload in that order. Missing is distinct from present-empty. Unrelated keys are ignored.
        var sources = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        foreach (string name in Sources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!supplied.TryGetValue(name, out var raw))
                throw new CatalogDecodeException("Missing offline raw table: " + name);
            if (raw.Length > MaxSourceBytes)
                throw new CatalogDecodeException("Oversized offline raw table: " + name);
            sources.Add(name, raw.ToArray());
        }
        cancellationToken.ThrowIfCancellationRequested();
        var eve = sources["Eve"];
        EveV115Indexes npcs, interactions;
        try
        {
            npcs = EveV115Parser.Parse(eve, cancellationToken);
            interactions = npcs;
        }
        catch (EveDecodeException)
        {
            // Source combined-index fallback preserves which per-feature limit failed first.
            npcs = EveV115Parser.Parse(eve, EveV115Parser.NpcSource, cancellationToken);
            interactions = EveV115Parser.Parse(eve, EveV115Parser.InteractionSource, cancellationToken);
        }
        // A successfully returned candidate requires both indexes. Fallback parses preserve
        // errors; if both succeed their full-layout parse has already validated the same bytes.
        var indexes = ReferenceEquals(npcs, interactions) ? npcs : new EveV115Indexes(
            npcs.Scenes.Select((scene, index) => scene with { Interactions = interactions.Scenes[index].Interactions }).ToImmutableArray(),
            true, true, npcs.NpcRecordCount, interactions.InteractionRecordCount);
        var items = ItemDataParser.ParseForRuntimeCandidate(sources["ItemData_C"], packageVersion, cancellationToken);
        RuntimeCandidateBindings.CheckShopItems(indexes, items, cancellationToken);
        var talks = TalkDataParser.Parse(sources["TalkData_C"], cancellationToken);
        var texts = TextDataParser.Parse(sources["TextData_C"], cancellationToken);
        var recipes = RuntimeCandidateBindings.Recipes(sources["SmithData_C"], items, cancellationToken);
        var stages = StageDataParser.Parse(sources["ScenesData_C"], cancellationToken);
        var doors = EveDoorParser.ParseLayout(eve, cancellationToken);
        // Python reconciles event exits even without optional StageMap/EveDoorLinks/route tables.
        // Only owned decoded rows participate. No optional keys in supplied can inject evidence.
        // Bind precharges per-door event expansion under its fixed default work budget.
        var portals = OfflineBoundaryPortals.Bind(stageRaw: null, linkRaw: null, doors, stages,
            cancellationToken: cancellationToken);
        // Typed OpenUsed is always an integer; Recipes already validates every product/material.
        if (stages.Count == 0 || talks.Count == 0 || texts.Count == 0)
            throw new CatalogDecodeException("1275 場景或對話原始資料缺失");
        var expedition = ExpeditionCatalogParser.ParseCatalog(sources["AdventureData_C"], sources["AdventureLvData_C"], cancellationToken);
        var expeditionNpcs = ExpeditionCatalogParser.ParseNpcs(sources["NpcData_C"], sources["NpcCareerData_C"], cancellationToken);
        var named = ExpeditionCatalogParser.BindNames(expedition, texts, strictRuntimeNames: true, cancellationToken);
        var expeditionHashes = ExpeditionCatalogParser.CopyHashes(expedition.SourceSha256);
        expeditionHashes["NpcData_C"] = ExpeditionCatalogParser.Hash(sources["NpcData_C"], cancellationToken);
        expeditionHashes["NpcCareerData_C"] = ExpeditionCatalogParser.Hash(sources["NpcCareerData_C"], cancellationToken);
        var hashes = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string name in Sources) hashes.Add(name, ExpeditionCatalogParser.Hash(sources[name], cancellationToken));
        // The coverage pass follows the required-table cross-checks, like the source runtime.
        // Missing optional assets remain missing; event-only coverage is never full readiness.
        var coverage = OfflinePortalCoverage.Audit(doors, stages, portals: portals, cancellationToken: cancellationToken);
        ImmutableDictionary<uint, CombatResourceNpc>? reviewedNpcs = null;
        // The hash is computed above from this owned required payload, not supplied by a caller.
        // Skip unsupported versions without failing otherwise valid required-table preparation.
        if (hashes["NpcData_C"] == NormalAttackCatalogParser.ReviewedNpcSha256)
        {
            try { reviewedNpcs = ReviewedNpcCatalogParser.Parse(sources["NpcData_C"], cancellationToken); }
            catch (CatalogDecodeException) { cancellationToken.ThrowIfCancellationRequested(); }
        }
        var candidate = new OfflineRuntimeCandidate(indexes, items, talks, texts, recipes, stages, doors,
            RuntimeCandidateBindings.SceneNames(stages, texts, cancellationToken),
            new(named, expedition.Levels, new OrderedCatalog<string, string>(expeditionHashes, expeditionHashes.Keys)),
            expeditionNpcs, new OrderedCatalog<string, string>(hashes, hashes.Keys), new(portals, coverage),
            reviewedNpcs: reviewedNpcs);
        cancellationToken.ThrowIfCancellationRequested();
        return candidate;
    }
}
