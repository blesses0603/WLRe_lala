using System.Collections.Immutable;

namespace Lala.Core.Catalogs;

/// <summary>
/// Bounded offline composition of six required raw-table decoders only. Caller maps are not trusted
/// provenance. No revision/pin policy, Eve projection, bundle extraction, admission or installation.
/// </summary>
public static class OfflineRuntimeTableDecoder
{
    public const int MaxSourceBytes = 16 * 1024 * 1024;
    public static ImmutableArray<string> Sources { get; } =
        ["TalkData_C", "TextData_C", "AdventureData_C", "AdventureLvData_C", "NpcData_C", "NpcCareerData_C"];

    public static OfflineRuntimeTableData Decode(IReadOnlyDictionary<string, ReadOnlyMemory<byte>> sources,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(sources);
        // Access only each required source when its source stage is reached. Extra tables are ignored.
        // Order matches the runtime's relative order for these six tables, with other stages excluded.
        var talks = TalkDataParser.Parse(Source("TalkData_C"), cancellationToken);
        var texts = TextDataParser.Parse(Source("TextData_C"), cancellationToken);
        byte[] taskRaw = Source("AdventureData_C"), levelRaw = Source("AdventureLvData_C");
        var expedition = ExpeditionCatalogParser.ParseCatalog(taskRaw, levelRaw, cancellationToken);
        byte[] npcRaw = Source("NpcData_C"), careerRaw = Source("NpcCareerData_C");
        var npcs = ExpeditionCatalogParser.ParseNpcs(npcRaw, careerRaw, cancellationToken);
        var named = ExpeditionCatalogParser.BindNames(expedition, texts, strictRuntimeNames: true, cancellationToken);
        var hashes = ExpeditionCatalogParser.CopyHashes(expedition.SourceSha256);
        hashes["NpcData_C"] = ExpeditionCatalogParser.Hash(npcRaw, cancellationToken);
        hashes["NpcCareerData_C"] = ExpeditionCatalogParser.Hash(careerRaw, cancellationToken);
        // Source runtime includes these four hashes, not TextData_C. Do not fabricate its provenance label.
        var result = new OfflineRuntimeTableData(talks, texts,
            new(named, expedition.Levels, new OrderedCatalog<string, string>(hashes, hashes.Keys)), npcs);
        cancellationToken.ThrowIfCancellationRequested();
        return result;

        byte[] Source(string name)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!sources.TryGetValue(name, out var raw))
                throw new CatalogDecodeException("Missing offline raw table: " + name);
            if (raw.Length > MaxSourceBytes)
                throw new CatalogDecodeException("Oversized offline raw table: " + name);
            return raw.ToArray();
        }
    }
}
