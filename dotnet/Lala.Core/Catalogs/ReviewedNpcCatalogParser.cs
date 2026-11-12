using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Text;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Inventory;

namespace Lala.Core.Catalogs;

/// <summary>
/// Reviewed NPC names and five source skill slots from the already-required NpcData table.
/// The normal-attack parser's fixed SHA-256 and full layout validation remain mandatory.
/// These immutable observations grant neither source provenance nor command authority.
/// </summary>
public static class ReviewedNpcCatalogParser
{
    public static ImmutableDictionary<uint, CombatResourceNpc> Parse(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default) => ParseCore(raw, true, cancellationToken);

    // Synthetic tests only. No public layout switch or caller-supplied digest can bypass review.
    internal static ImmutableDictionary<uint, CombatResourceNpc> ParseLayout(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default) => ParseCore(raw, false, cancellationToken);

    private static ImmutableDictionary<uint, CombatResourceNpc> ParseCore(ReadOnlySpan<byte> raw,
        bool verifySource, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (raw.Length > NormalAttackCatalogParser.MaxNpcBytes)
        {
            // Reject without allocating a second oversized payload, retaining source diagnostics.
            NormalAttackCatalogParser.ParseNpcs(raw, token);
            throw new InvalidOperationException("Unreachable NPC size acceptance");
        }
        // The validator and name/skill reread must observe the same owned bytes.
        byte[] snapshot = raw.ToArray();
        if (verifySource) NormalAttackCatalogParser.ParseNpcs(snapshot, token);
        else NormalAttackCatalogParser.ParseNpcsLayout(snapshot, token);
        return ReadCombatNpcs(snapshot, token);
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
        var result = rows.ToImmutable();
        token.ThrowIfCancellationRequested();
        return result;
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
