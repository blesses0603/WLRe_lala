using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

/// <summary>
/// The expedition data.py raw decoders, not normal_attack_catalog's different NPC projection.
/// No cache, filesystem, source classification, fixed-pin override or runtime installation.
/// </summary>
public static class ExpeditionCatalogParser
{
    public const int MaxTasks = 65_535;
    public const int TaskRecordBytes = 105;
    public const int MaxLevels = 255;
    public const int LevelRecordBytes = 15;
    public const int MaxNpcs = 65_535;
    public const int MaxCareers = 65_535;
    private static readonly UnicodeEncoding StrictUnicode = new(false, false, true);
    private static readonly ParserDiagnosticDefinition CatalogDiagnostic =
        new("wlre.services.expedition.data.parse_catalog", "adventure-v1");
    private static readonly ParserDiagnosticDefinition NpcDiagnostic =
        new("wlre.services.expedition.data.parse_npcs", "npc-career-v1");

    public static ExpeditionCatalogData ParseCatalog(ReadOnlySpan<byte> tasksData, ReadOnlySpan<byte> levelsData,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        byte[] tasks = tasksData.ToArray(), levels = levelsData.ToArray();
        return ParserDiagnostics.Run(CatalogDiagnostic,
            [new("tasks_data", tasks), new("levels_data", levels)],
            () => ReadCatalog(tasks, levels, cancellationToken), rows => new(rows.Tasks.Count),
            cancellationToken: cancellationToken);
    }

    private static ExpeditionCatalogData ReadCatalog(byte[] tasksData, byte[] levelsData, CancellationToken token)
    {
        var reader = new ExpeditionWireReader(tasksData, token);
        int count = reader.I32();
        if (count is < 1 or > MaxTasks) throw new CatalogDecodeException("遠征任務資料筆數錯誤");
        var tasks = new Dictionary<ushort, ExpeditionTaskData>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            ushort id = reader.U16(); byte area = reader.U8(); uint areaName = reader.U32();
            byte difficulty = reader.U8(); uint name = reader.U32(), description = reader.U32();
            ushort minutes = reader.U16(); byte faith = reader.U8(); ushort success = reader.U16();
            var condition = ReadCondition(ref reader);
            var recommendations = ImmutableArray.CreateBuilder<ExpeditionRecommendation>(4);
            for (int slot = 0; slot < 4; slot++)
                recommendations.Add(new(ReadCondition(ref reader), reader.U16()));
            uint expeditionExp = reader.U32();
            var rewards = ImmutableArray.CreateBuilder<ExpeditionReward>(3);
            for (int slot = 0; slot < 3; slot++) rewards.Add(ReadReward(ref reader));
            ushort specialRate = reader.U16();
            var specialReward = ReadReward(ref reader);
            int exp = reader.I32();
            // Validation is after the entire record, not immediately after its ID/minutes fields.
            if (id == 0 || tasks.ContainsKey(id) || minutes == 0 || faith > 100)
                throw new CatalogDecodeException("遠征任務資料內容錯誤");
            tasks.Add(id, new(id, area, areaName, difficulty, name, description, minutes, faith, success,
                condition, recommendations.MoveToImmutable(), expeditionExp, rewards.MoveToImmutable(),
                specialRate, specialReward, exp));
        }
        reader.End();
        reader = new ExpeditionWireReader(levelsData, token);
        count = reader.I32();
        if (count is < 1 or > MaxLevels) throw new CatalogDecodeException("遠征等級資料筆數錯誤");
        var levels = new Dictionary<byte, ExpeditionLevelData>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            byte level = reader.U8(); reader.U32(); reader.U32();
            byte teams = reader.U8(), difficulty = reader.U8(); ushort reduction = reader.U16();
            reader.U8(); reader.U8();
            if (levels.ContainsKey(level) || teams > 7 || reduction > 1000)
                throw new CatalogDecodeException("遠征等級資料內容錯誤");
            levels.Add(level, new(teams, difficulty, reduction));
        }
        reader.End();
        var hashes = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["AdventureData_C"] = Hash(tasksData, token),
            ["AdventureLvData_C"] = Hash(levelsData, token)
        };
        token.ThrowIfCancellationRequested();
        return new(new OrderedCatalog<ushort, ExpeditionTaskData>(tasks, tasks.Keys),
            new OrderedCatalog<byte, ExpeditionLevelData>(levels, levels.Keys),
            new OrderedCatalog<string, string>(hashes, hashes.Keys));
    }

    public static IReadOnlyDictionary<ushort, ExpeditionNpcData> ParseNpcs(ReadOnlySpan<byte> npcData,
        ReadOnlySpan<byte> careerData, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        byte[] npcs = npcData.ToArray(), careers = careerData.ToArray();
        return ParserDiagnostics.Run(NpcDiagnostic, [new("npc_data", npcs), new("career_data", careers)],
            () => ReadNpcs(npcs, careers, cancellationToken), rows => new(rows.Count),
            cancellationToken: cancellationToken);
    }

    private static IReadOnlyDictionary<ushort, ExpeditionNpcData> ReadNpcs(byte[] npcData, byte[] careerData,
        CancellationToken token)
    {
        // Career parsing including EOF precedes the NPC header, even for invalid NPC bytes.
        var reader = new ExpeditionWireReader(careerData, token);
        int count = reader.I32();
        if (count is < 0 or > MaxCareers) throw new CatalogDecodeException("轉職夥伴資料筆數錯誤");
        var careers = new Dictionary<ushort, ushort>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "career", record: index + 1);
            var fields = reader.Take(17);
            ushort original = BinaryPrimitives.ReadUInt16LittleEndian(fields[2..]);
            ushort career = BinaryPrimitives.ReadUInt16LittleEndian(fields[4..]);
            if (!careers.TryAdd(career, original)) throw new CatalogDecodeException("轉職夥伴對照重複");
        }
        reader.End();
        reader = new ExpeditionWireReader(npcData, token);
        count = reader.I32();
        if (count is < 1 or > MaxNpcs) throw new CatalogDecodeException("夥伴資料筆數錯誤");
        var npcs = new Dictionary<ushort, ExpeditionNpcData>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            for (int field = 0; field < 2; field++)
            {
                ushort size = reader.U16();
                if ((size & 1) != 0) throw new CatalogDecodeException("夥伴名稱長度錯誤");
                // Python lets UnicodeDecodeError escape here; preserve .NET's strict codec exception.
                StrictUnicode.GetString(reader.Take(size));
            }
            var fields = reader.Take(203);
            ushort id = BinaryPrimitives.ReadUInt16LittleEndian(fields[1..]);
            if (id == 0 || npcs.ContainsKey(id)) throw new CatalogDecodeException("夥伴 ID 無效或重複");
            npcs.Add(id, new(fields[74], fields[106], careers.GetValueOrDefault(id, id)));
        }
        reader.End();
        token.ThrowIfCancellationRequested();
        return new OrderedCatalog<ushort, ExpeditionNpcData>(npcs, npcs.Keys);
    }

    /// <summary>Original attach_names truthiness: whitespace and NUL names are allowed, empty/missing are not.</summary>
    public static ExpeditionCatalogData AttachNames(ExpeditionCatalogData catalog, ReadOnlySpan<byte> textData,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(catalog);
        // The existing parser owns strict TextData semantics and the sole text-v1 observation.
        // Keep TextData's oversize rejection and named diagnostic without copying a doomed input.
        if (textData.Length > TextDataParser.MaxBytes)
            TextDataParser.Parse(textData, cancellationToken);
        byte[] text = textData.ToArray();
        var texts = TextDataParser.Parse(text, cancellationToken);
        var named = BindNames(catalog, texts, strictRuntimeNames: false, cancellationToken);
        var hashes = CopyHashes(catalog.SourceSha256);
        hashes["TextData_C"] = Hash(text, cancellationToken);
        return new(named, catalog.Levels, new OrderedCatalog<string, string>(hashes, hashes.Keys));
    }

    internal static IReadOnlyDictionary<ushort, ExpeditionTaskData> BindNames(ExpeditionCatalogData catalog,
        IReadOnlyDictionary<uint, string> texts, bool strictRuntimeNames, CancellationToken token)
    {
        var named = new Dictionary<ushort, ExpeditionTaskData>();
        foreach (var (id, quest) in catalog.Tasks)
        {
            token.ThrowIfCancellationRequested();
            texts.TryGetValue(quest.NameId, out var name);
            string area = texts.GetValueOrDefault(quest.AreaName, "");
            if (strictRuntimeNames)
            {
                if (name is null || PythonBlank(name) || CodepointLength(name) > 8192 || CodepointLength(area) > 8192)
                    throw new CatalogDecodeException("1275 遠征任務缺少已驗證文字");
            }
            else if (string.IsNullOrEmpty(name))
                throw new CatalogDecodeException("官方文字資料缺少任務名稱：" + id.ToString(CultureInfo.InvariantCulture));
            named.Add(id, quest with { Name = name, AreaLabel = area });
        }
        token.ThrowIfCancellationRequested();
        return new OrderedCatalog<ushort, ExpeditionTaskData>(named, named.Keys);
    }

    private static bool PythonBlank(string text) => text.All(value => value is >= '\u0009' and <= '\u000d'
        or >= '\u001c' and <= '\u0020' or '\u0085' or '\u00a0' or '\u1680'
        or >= '\u2000' and <= '\u200a' or '\u2028' or '\u2029' or '\u202f' or '\u205f' or '\u3000');
    private static int CodepointLength(string text)
    {
        int count = 0;
        foreach (var unused in text.EnumerateRunes()) count++;
        return count;
    }
    private static ImmutableArray<ushort> ReadCondition(ref ExpeditionWireReader reader) =>
        [reader.U16(), reader.U16(), reader.U16()];
    private static ExpeditionReward ReadReward(ref ExpeditionWireReader reader) => new(reader.U8(), reader.U32(), reader.U32());
    internal static Dictionary<string, string> CopyHashes(IReadOnlyDictionary<string, string> hashes) =>
        hashes.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
    internal static string Hash(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        while (!raw.IsEmpty)
        {
            token.ThrowIfCancellationRequested();
            int size = Math.Min(raw.Length, 64 * 1024);
            hash.AppendData(raw[..size]); raw = raw[size..];
        }
        token.ThrowIfCancellationRequested();
        return Convert.ToHexStringLower(hash.GetHashAndReset());
    }
}
