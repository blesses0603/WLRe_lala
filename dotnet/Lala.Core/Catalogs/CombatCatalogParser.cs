using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Inventory;

namespace Lala.Core.Catalogs;

public sealed record CombatCatalogItem(string Name, byte Kind, ImmutableArray<ItemAttribute> Attributes,
    byte Special, ushort Restrict, ushort SkillLink, byte FitType);

/// <summary>
/// Immutable parsed values, not a runtime identity or permission token. Construction of a public
/// knowledge DTO never proves provenance. Official package activation remains outside this port.
/// </summary>
public sealed class CombatCatalogData
{
    public ImmutableDictionary<uint, CombatResourceSkill> Skills { get; }
    public ImmutableDictionary<ushort, uint> SkillKeys { get; }
    public ImmutableDictionary<ushort, CombatCatalogItem> Items { get; }
    public ImmutableDictionary<uint, CombatResourceNpc> Npcs { get; }
    public CombatCatalogConstants Constants { get; }

    internal CombatCatalogData(ImmutableDictionary<uint, CombatResourceSkill> skills,
        ImmutableDictionary<ushort, uint> keys, ImmutableDictionary<ushort, CombatCatalogItem> items,
        ImmutableDictionary<uint, CombatResourceNpc> npcs, CombatCatalogConstants constants)
        => (Skills, SkillKeys, Items, Npcs, Constants) = (skills, keys, items, npcs, constants);

    /// <summary>
    /// Explicit lossy projection to existing offline knowledge inputs. Item names, special values
    /// and attribute effect bytes stay in Items above. Unrepresentable characters or nonfinite
    /// weights reject here, never clamp or silently become a different action candidate.
    /// </summary>
    public CombatResourceCatalog ToKnowledgeSnapshot(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var characters = ImmutableArray.CreateBuilder<CombatResourceCharacter>();
        foreach (var row in Constants.Characters)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (row.Sex > int.MaxValue || row.Head > int.MaxValue || row.Skill > uint.MaxValue || row.Body > ushort.MaxValue)
                throw new CatalogDecodeException("Character value exceeds knowledge snapshot range");
            characters.Add(new((int)row.Sex, (int)row.Head, (uint)row.Skill, (ushort)row.Body));
        }
        if (Constants.ElementWeights.Values.SelectMany(row => row.Values).Any(value => !double.IsFinite(value)))
            throw new CatalogDecodeException("Nonfinite element weight cannot enter knowledge snapshot");
        var items = ImmutableDictionary.CreateBuilder<ushort, CombatResourceItem>();
        foreach (var (id, row) in Items)
        {
            cancellationToken.ThrowIfCancellationRequested();
            items.Add(id, new(row.Kind, row.FitType, row.SkillLink)
            {
                Attributes = [.. row.Attributes.Select(value => new CombatResourceAttribute(value.Kind, value.Value))],
                Restrict = row.Restrict
            });
        }
        var result = new CombatResourceCatalog
        {
            Skills = Skills, SkillKeys = SkillKeys, Npcs = Npcs, Items = items.ToImmutable(), Characters = characters.ToImmutable(),
            ElementWeights = Constants.ElementWeights.ToImmutableDictionary(pair => (long)pair.Key,
                pair => pair.Value.ToImmutableDictionary(cell => (long)cell.Key, cell => cell.Value))
        };
        cancellationToken.ThrowIfCancellationRequested();
        return result;
    }
}

public static partial class CombatCatalogParser
{
    public static CombatCatalogData BuildCatalog(ReadOnlySpan<byte> skillRaw, ReadOnlySpan<byte> npcRaw,
        ReadOnlySpan<byte> itemRaw, IReadOnlyDictionary<uint, string?> texts, string define, string fight,
        CancellationToken cancellationToken = default) =>
        Build(skillRaw, npcRaw, itemRaw, texts, define, fight, verifySource: true, cancellationToken);

    // Synthetic test-only path. It cannot accept custom hashes or promote a DTO into official data.
    internal static CombatCatalogData BuildCatalogLayout(ReadOnlySpan<byte> skillRaw, ReadOnlySpan<byte> npcRaw,
        ReadOnlySpan<byte> itemRaw, IReadOnlyDictionary<uint, string?> texts, string define, string fight,
        CancellationToken cancellationToken = default) =>
        Build(skillRaw, npcRaw, itemRaw, texts, define, fight, verifySource: false, cancellationToken);

    private static CombatCatalogData Build(ReadOnlySpan<byte> skillRaw, ReadOnlySpan<byte> npcRaw,
        ReadOnlySpan<byte> itemRaw, IReadOnlyDictionary<uint, string?> texts, string define, string fight,
        bool verifySource, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        // Source order: item digest, NPC validation/reread, item parse, skill parse, names, keys, Lua.
        if (itemRaw.Length > ItemDataParser.MaxBytes) throw new CatalogDecodeException("Unreviewed combat ItemData");
        byte[] itemSnapshot = itemRaw.ToArray();
        if (verifySource && Convert.ToHexStringLower(SHA256.HashData(itemSnapshot)) != ItemDataParser.Reviewed1296Sha256)
            throw new CatalogDecodeException("Unreviewed combat ItemData");
        token.ThrowIfCancellationRequested();
        if (npcRaw.Length > NormalAttackCatalogParser.MaxNpcBytes)
        {
            // Reuse the source-decorated validator even on an oversized failure.
            NormalAttackCatalogParser.ParseNpcs(npcRaw, token);
            throw new InvalidOperationException("Unreachable NPC size acceptance");
        }
        byte[] npcSnapshot = npcRaw.ToArray();
        if (verifySource) NormalAttackCatalogParser.ParseNpcs(npcSnapshot, token);
        else NormalAttackCatalogParser.ParseNpcsLayout(npcSnapshot, token);
        var npcs = ReadCombatNpcs(npcSnapshot, token);
        var itemRows = verifySource ? ItemDataParser.Parse(itemSnapshot, includeSkillLink: true, cancellationToken: token)
            : ItemDataParser.ParseLayout(itemSnapshot, reviewed1296: true, includeSkillLink: true, cancellationToken: token);
        var items = ImmutableDictionary.CreateBuilder<ushort, CombatCatalogItem>();
        foreach (var (id, item) in itemRows)
        {
            token.ThrowIfCancellationRequested();
            var details = item.ReviewedDetails ?? throw new CatalogDecodeException("Unreviewed combat ItemData");
            items.Add(id, new(item.Name, details.Kind, [.. details.Attributes], details.Special,
                item.Restrict, details.SkillLink!.Value, details.FitType));
        }
        var skillRows = verifySource ? SkillDataParser.Parse(skillRaw, token) : SkillDataParser.ParseLayout(skillRaw, token);
        ArgumentNullException.ThrowIfNull(texts);
        var skills = ImmutableDictionary.CreateBuilder<uint, CombatResourceSkill>();
        // Parser dictionaries do not promise source order. The source validates all names before
        // keys, and every failure in each phase has the same value-free error, so no order is guessed.
        foreach (var (id, skill) in skillRows)
        {
            token.ThrowIfCancellationRequested();
            if (!texts.TryGetValue(skill.NameTextId, out string? name) || string.IsNullOrEmpty(name))
                throw new CatalogDecodeException("Missing official skill name");
            skills.Add(id, new() { Name = name, Fields = skill.Fields.ToImmutableDictionary(pair => pair.Key,
                pair => (long)pair.Value, StringComparer.Ordinal) });
        }
        var keys = ImmutableDictionary.CreateBuilder<ushort, uint>();
        foreach (var (id, skill) in skillRows)
        {
            token.ThrowIfCancellationRequested();
            if (skill.Key != 0 && !keys.TryAdd(skill.Key, id)) throw new CatalogDecodeException("Ambiguous skill key");
        }
        var constants = verifySource ? ParseConstants(define, fight, token) : ParseConstantsLayout(define, fight, token);
        var result = new CombatCatalogData(skills.ToImmutable(), keys.ToImmutable(), items.ToImmutable(), npcs, constants);
        token.ThrowIfCancellationRequested();
        return result;
    }

    private static ImmutableDictionary<uint, CombatResourceNpc> ReadCombatNpcs(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        var reader = new CatalogReader(raw, token);
        ParserDiagnostics.ReadCheckpoint(reader.Position, 4, reader.Remaining);
        uint count = reader.UInt32();
        var rows = ImmutableDictionary.CreateBuilder<uint, CombatResourceNpc>();
        for (int index = 0; index < count; index++)
        {
            string name = ReadValidatedNpcText(ref reader);
            ReadValidatedNpcText(ref reader);
            ParserDiagnostics.ReadCheckpoint(reader.Position, NormalAttackCatalogParser.NpcFieldBytes, reader.Remaining);
            var fields = reader.Take(NormalAttackCatalogParser.NpcFieldBytes);
            ushort id = BinaryPrimitives.ReadUInt16LittleEndian(fields[1..]);
            var skills = ImmutableArray.CreateBuilder<uint>(5);
            for (int offset = 75; offset < 85; offset += 2) skills.Add(BinaryPrimitives.ReadUInt16LittleEndian(fields[offset..]));
            rows.Add(id, new() { Name = name, Skills = skills.ToImmutable() });
        }
        return rows.ToImmutable();
    }

    private static readonly UnicodeEncoding StrictNpcUnicode = new(false, false, true);
    private static string ReadValidatedNpcText(ref CatalogReader reader)
    {
        // The owned snapshot already passed the source-decorated NPC validator. These source
        // Reader.take checkpoints still matter when the undecorated builder has a diagnosed parent.
        ParserDiagnostics.ReadCheckpoint(reader.Position, 2, reader.Remaining);
        ushort length = reader.UInt16();
        ParserDiagnostics.ReadCheckpoint(reader.Position, length, reader.Remaining);
        return StrictNpcUnicode.GetString(reader.Take(length)).TrimEnd('\0');
    }
}
