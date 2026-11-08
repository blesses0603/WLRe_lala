using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record InstanceAward(byte Kind, uint Id, uint Value);
public sealed record DungeonDataRow(ushort Id, byte Kind, byte ParaKind, ushort MapId,
    uint DescriptionId, byte Picture, byte ScoreDisplay, byte AwardGroup, ushort NpcX,
    ushort NpcY, ushort NpcId, byte QuickId, ImmutableArray<InstanceAward> Awards,
    ImmutableArray<byte> DoubleAwardSlots, ImmutableArray<byte> SpecialAwardSlots);
public sealed record CooperativeEventDataRow(byte Id, uint TextId, ushort NpcX, ushort NpcY,
    byte FightCount, ushort StepMarkId, ushort FinishMarkId, ushort SellDataId,
    ImmutableArray<ushort> FollowerIds, InstanceAward FollowerReward);
public sealed record BoundInstanceAward(byte Slot, byte Kind, uint Id, uint Value);

/// <summary>
/// Immutable supplied-table projection. CreationSupported describes Python's structural schema
/// compatibility only, never current permission, server readiness, or a callable creation action.
/// Data retains all sixteen raw award slots, including empty slots and both flag lists.
/// </summary>
public sealed record BoundInstanceCatalogRow(DungeonDataRow Data, StageDataRow Stage,
    string Name, uint NameId, ImmutableArray<BoundInstanceAward> Awards,
    CooperativeEventDataRow? CooperativeEvent, bool CreationSupported)
{
    public byte Variant => Data.ParaKind;
    public ushort MinLevel => Stage.MinLevel;
    public byte MinMembers => Stage.MinMembers;
    public byte MaxMembers => Stage.MaxMembers;
    public ushort TimeMinutes => Stage.TimeMinutes;
    public byte RoomCount => Stage.RoomCapacity;
    public bool? IsOpen => null;
}

/// <summary>
/// Read-only preview, with no identity, source verification, activation, command, or packet APIs.
/// DeclaredMainMapIds is only the kind-1 map set declared by the supplied records, not map readiness.
/// </summary>
public sealed class InstanceCatalogPreview
{
    internal InstanceCatalogPreview(ImmutableArray<BoundInstanceCatalogRow> entries,
        ImmutableArray<CooperativeEventDataRow> cooperativeEvents, ImmutableHashSet<ushort> declaredMainMapIds)
        => (Entries, CooperativeEvents, DeclaredMainMapIds) = (entries, cooperativeEvents, declaredMainMapIds);
    public ImmutableArray<BoundInstanceCatalogRow> Entries { get; }
    public ImmutableArray<CooperativeEventDataRow> CooperativeEvents { get; }
    public ImmutableHashSet<ushort> DeclaredMainMapIds { get; }
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
}

/// <summary>
/// Exact instance_catalog.py table readers and instance_runtime.build_catalog binding invariants.
/// Caller-supplied stage, text and item metadata must come from one independently verified version;
/// successful parsing and binding do not establish provenance or authorize any runtime activity.
/// </summary>
public static class InstanceCatalogParser
{
    public const int MaxRecords = 20_000;
    public const int RewardSlots = 16;
    public const int DungeonRecordBytes = 168;
    public const int CooperativeEventRecordBytes = 33;
    public const int MaxDungeonBytes = 4 + MaxRecords * DungeonRecordBytes;
    public const int MaxCooperativeEventBytes = 4 + MaxRecords * CooperativeEventRecordBytes;
    private static readonly ParserDiagnosticDefinition DungeonDiagnostic =
        new("wlre.services.instance_catalog.parse_dungeons", "dungeon-v1");
    private static readonly ParserDiagnosticDefinition CooperativeDiagnostic =
        new("wlre.services.instance_catalog.parse_cooperative_events", "cooperate-v1");

    public static ImmutableArray<DungeonDataRow> ParseDungeons(ReadOnlySpan<byte> data,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // Preserve Python's read/validation/trailing-byte ordering without copying oversized input.
        ReadOnlySpan<byte> snapshot = data.Length <= MaxDungeonBytes ? data.ToArray() : data;
        return ParserDiagnostics.RunWithRaw(DungeonDiagnostic, snapshot,
            bytes => ReadDungeons(bytes, cancellationToken), rows => new(rows.Length), null,
            cancellationToken, inputName: "data");
    }

    public static ImmutableArray<CooperativeEventDataRow> ParseCooperativeEvents(ReadOnlySpan<byte> data,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = data.Length <= MaxCooperativeEventBytes ? data.ToArray() : data;
        return ParserDiagnostics.RunWithRaw(CooperativeDiagnostic, snapshot,
            bytes => ReadCooperativeEvents(bytes, cancellationToken), rows => new(rows.Length), null,
            cancellationToken, inputName: "data");
    }

    private static ImmutableArray<DungeonDataRow> ReadDungeons(ReadOnlySpan<byte> data, CancellationToken token)
    {
        var reader = new InstanceReader(data, token);
        int count = ReadCount(ref reader);
        var rows = ImmutableArray.CreateBuilder<DungeonDataRow>(count);
        for (int index = 0; index < count; index++)
        {
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            ushort id = reader.U16(); byte kind = reader.U8(), paraKind = reader.U8();
            ushort map = reader.U16(); uint description = reader.U32();
            byte picture = reader.U8(), score = reader.U8(), group = reader.U8();
            ushort x = reader.U16(), y = reader.U16(), npc = reader.U16(); byte quick = reader.U8();
            var awards = ImmutableArray.CreateBuilder<InstanceAward>(RewardSlots);
            for (int slot = 0; slot < RewardSlots; slot++) awards.Add(ReadAward(ref reader));
            var doubleSlots = ReadFlags(ref reader); var specialSlots = ReadFlags(ref reader);
            // Source checks kind only after all awards and flags, and accepts duplicate/zero IDs here.
            if (kind is not (1 or 2 or 3)) throw new CatalogDecodeException("未知副本種類；拒絕套用不相符資料");
            rows.Add(new(id, kind, paraKind, map, description, picture, score, group, x, y,
                npc, quick, awards.MoveToImmutable(), doubleSlots, specialSlots));
        }
        reader.End();
        token.ThrowIfCancellationRequested();
        return rows.MoveToImmutable();
    }

    private static ImmutableArray<CooperativeEventDataRow> ReadCooperativeEvents(ReadOnlySpan<byte> data,
        CancellationToken token)
    {
        var reader = new InstanceReader(data, token);
        int count = ReadCount(ref reader);
        var rows = ImmutableArray.CreateBuilder<CooperativeEventDataRow>(count);
        for (int index = 0; index < count; index++)
        {
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            byte id = reader.U8(); uint text = reader.U32(); ushort x = reader.U16(), y = reader.U16();
            byte fight = reader.U8(); ushort step = reader.U16(), finish = reader.U16(), sell = reader.U16();
            ImmutableArray<ushort> followers = [reader.U16(), reader.U16(), reader.U16(), reader.U16()];
            rows.Add(new(id, text, x, y, fight, step, finish, sell, followers, ReadAward(ref reader)));
        }
        reader.End();
        token.ThrowIfCancellationRequested();
        return rows.MoveToImmutable();
    }

    /// <summary>
    /// Uses stable caller-supplied metadata; does not look up files, invent names, or infer source identity.
    /// Raw cooperative parsing and event validation precede dungeon parsing, as in the Python builder.
    /// </summary>
    public static InstanceCatalogPreview Bind(ReadOnlySpan<byte> dungeonData, ReadOnlySpan<byte> cooperativeData,
        IReadOnlyDictionary<ushort, StageDataRow> stages, IReadOnlyDictionary<uint, string?> texts,
        IReadOnlySet<uint> itemIds, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(stages);
        ArgumentNullException.ThrowIfNull(texts);
        ArgumentNullException.ThrowIfNull(itemIds);
        var cooperativeEvents = ParseCooperativeEvents(cooperativeData, cancellationToken);
        var events = new Dictionary<ushort, CooperativeEventDataRow>();
        foreach (var row in cooperativeEvents)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (row.Id == 0 || !events.TryAdd(row.Id, row))
                throw new CatalogDecodeException("協力事件 ID 重複或為零");
        }
        var dungeons = ParseDungeons(dungeonData, cancellationToken);
        var entries = ImmutableArray.CreateBuilder<BoundInstanceCatalogRow>(dungeons.Length);
        var seen = new HashSet<(ushort Id, byte Variant)>();
        var maps = ImmutableHashSet.CreateBuilder<ushort>();
        foreach (var dungeon in dungeons)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (dungeon.Id == 0 || !seen.Add((dungeon.Id, dungeon.ParaKind)))
                throw new CatalogDecodeException("副本複合識別碼重複或無效");
            if (!stages.TryGetValue(dungeon.MapId, out var stage))
                throw new CatalogDecodeException("副本缺少同版場景");
            if (dungeon.Kind == 1 && !maps.Add(dungeon.MapId))
                throw new CatalogDecodeException("一般副本場景無法唯一識別");
            var cooperativeEvent = dungeon.Kind == 2 ? events.GetValueOrDefault(dungeon.NpcId) : null;
            if (dungeon.Kind == 2 && dungeon.ParaKind == 2 && cooperativeEvent is null)
                throw new CatalogDecodeException("具名協力副本缺少同版事件");
            uint nameId = cooperativeEvent?.TextId ?? stage.NameId;
            if (!texts.TryGetValue(nameId, out string? name) || name is null || PythonBlank(name))
                throw new CatalogDecodeException("副本缺少同版官方名稱");
            byte minimum = stage.MinMembers, maximum = stage.MaxMembers;
            if (minimum > maximum) throw new CatalogDecodeException("副本人數範圍無效");
            var awards = ImmutableArray.CreateBuilder<BoundInstanceAward>();
            for (int slot = 0; slot < dungeon.Awards.Length; slot++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var award = dungeon.Awards[slot];
                if (award.Kind == 0)
                {
                    if (award.Id != 0 || award.Value != 0)
                        throw new CatalogDecodeException("空獎勵槽位含有未知資料");
                    continue;
                }
                if (award.Kind is 10 or 11 && !itemIds.Contains(award.Id))
                    throw new CatalogDecodeException("副本獎勵缺少同版道具");
                awards.Add(new(checked((byte)(slot + 1)), award.Kind, award.Id, award.Value));
            }
            bool supported = dungeon.Kind == 1 && minimum > 0 ||
                dungeon.Kind == 2 && dungeon.ParaKind is 1 or 2 && minimum >= 1 && maximum <= 8 &&
                (dungeon.ParaKind != 1 || dungeon.NpcId == 0);
            entries.Add(new(dungeon, stage, name, nameId, awards.ToImmutable(), cooperativeEvent, supported));
        }
        if (entries.Count == 0) throw new CatalogDecodeException("官方副本資料為空");
        cancellationToken.ThrowIfCancellationRequested();
        return new(entries.MoveToImmutable(), cooperativeEvents, maps.ToImmutable());
    }

    private static bool PythonBlank(string text) => text.All(value => value is >= '\u0009' and <= '\u000d'
        or >= '\u001c' and <= '\u0020' or '\u0085' or '\u00a0' or '\u1680'
        or >= '\u2000' and <= '\u200a' or '\u2028' or '\u2029' or '\u202f' or '\u205f' or '\u3000');
    private static int ReadCount(ref InstanceReader reader)
    {
        int count = reader.I32();
        if (count is < 0 or > MaxRecords) throw new CatalogDecodeException("副本資料筆數超出安全範圍");
        return count;
    }
    private static InstanceAward ReadAward(ref InstanceReader reader) => new(reader.U8(), reader.U32(), reader.U32());
    private static ImmutableArray<byte> ReadFlags(ref InstanceReader reader)
    {
        var slots = ImmutableArray.CreateBuilder<byte>();
        for (int part = 0; part < 2; part++)
        {
            byte bits = reader.U8();
            for (int bit = 0; bit < 8; bit++)
                if ((bits & (1 << bit)) != 0) slots.Add((byte)(part * 8 + bit + 1));
        }
        return slots.ToImmutable();
    }

    // Match every wire.Reader read, including positions on semantic failures and EOF checks.
    private ref struct InstanceReader(ReadOnlySpan<byte> data, CancellationToken token)
    {
        private readonly ReadOnlySpan<byte> data = data;
        private readonly CancellationToken token = token;
        public int Position { get; private set; }
        private int Remaining => data.Length - Position;
        public ReadOnlySpan<byte> Take(int size)
        {
            ParserDiagnostics.ReadCheckpoint(Position, size, Remaining);
            token.ThrowIfCancellationRequested();
            if (size > Remaining) throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                $"offset {Position}: need {size}, have {Remaining}"));
            var result = data.Slice(Position, size); Position += size; return result;
        }
        public byte U8() => Take(1)[0];
        public ushort U16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
        public uint U32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
        public int I32() => BinaryPrimitives.ReadInt32LittleEndian(Take(4));
        public void End()
        {
            ParserDiagnostics.ReadCheckpoint(Position, 0, Remaining);
            if (Remaining != 0) throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                $"unexpected trailing bytes: {Remaining}"));
        }
    }
}
