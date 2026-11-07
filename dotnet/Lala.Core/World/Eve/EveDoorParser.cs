using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Security.Cryptography;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.World.Eve;

public sealed class EveDoorSourceException : FormatException
{
    internal EveDoorSourceException(string message) : base(message) { }
}

/// <summary>Read-only port of doors_1275.py, with its own validation order rather than the
/// stricter all-section Eve parser. The only public entrypoint requires the reviewed source
/// pin. Internal composition may inspect a layout, but cannot assert official provenance.</summary>
public static class EveDoorParser
{
    public const string SourceSha256 = "f5fc56b1d6cf7c00dd20b2f35c04b4cbc60c92ccdb6085fbe465c7e6526745ad";
    public const int MaxSourceBytes = 32 * 1024 * 1024;
    // Source accepts overlapping scene windows. Bound repeated retained objects/references,
    // including duplicate door event references, rather than allowing input amplification.
    public const int MaxRetainedUnits = 1_000_000;
    private const string PinError = "1275 Eve.bytes SHA-256 與已確認來源不符";
    private static readonly ParserDiagnosticDefinition LayoutDiagnostic =
        new("wlre.services.world.doors_1275.parse_verified_doors", "eve-doors-v115");
    private static readonly ParserDiagnosticDefinition PinnedDiagnostic =
        new("wlre.services.world.doors_1275.parse_doors_1275", "eve-1275-pinned");

    public static EveDoorProjection ParsePinned1275(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = raw.Length is >= 12 and <= MaxSourceBytes ? raw.ToArray() : raw;
        return ParserDiagnostics.RunWithRaw(PinnedDiagnostic, snapshot, bytes =>
        {
            // Keep the pin check before every layout check, including size/header rejection.
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            for (int offset = 0; offset < bytes.Length; offset += Math.Min(65536, bytes.Length - offset))
            {
                cancellationToken.ThrowIfCancellationRequested();
                hash.AppendData(bytes.Slice(offset, Math.Min(65536, bytes.Length - offset)));
            }
            cancellationToken.ThrowIfCancellationRequested();
            if (Convert.ToHexStringLower(hash.GetHashAndReset()) != SourceSha256) throw new EveDoorSourceException(PinError);
            return ParseDiagnosedLayout(bytes, 1262, cancellationToken);
        }, result => new(result.Scenes.Length), null, cancellationToken);
    }

    internal static EveDoorProjection ParseLayout(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = raw.Length is >= 12 and <= MaxSourceBytes ? raw.ToArray() : raw;
        return ParseDiagnosedLayout(snapshot, null, cancellationToken);
    }

    private static EveDoorProjection ParseDiagnosedLayout(ReadOnlySpan<byte> raw, int? expectedScenes, CancellationToken token) =>
        ParserDiagnostics.RunWithRaw(LayoutDiagnostic, raw, bytes => ParseCore(bytes, expectedScenes, token),
            result => new(result.Scenes.Length), null, token);

    private static EveDoorProjection ParseCore(ReadOnlySpan<byte> raw, int? expectedScenes, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (raw.Length is < 12 or > MaxSourceBytes) throw new EveDoorSourceException("Eve 表頭或大小無效");
        uint count = BinaryPrimitives.ReadUInt32LittleEndian(raw[8..]);
        if (count is < 1 or > 4096 || (expectedScenes.HasValue && count != expectedScenes.Value) || 12 + count * 12 > raw.Length)
            throw new EveDoorSourceException("1275 Eve 場景數量或標頭不符");
        var scenes = ImmutableArray.CreateBuilder<EveDoorScene>((int)count);
        var ids = new HashSet<ushort>();
        var budget = new RetainedBudget();
        int doorCount = 0;
        // Do not sort or eagerly validate later headers: the source parses each scene in
        // directory order and permits overlap. Retain that error and output ordering.
        for (int i = 0; i < count; i++)
        {
            token.ThrowIfCancellationRequested();
            int at = 12 + i * 12;
            ParserDiagnostics.Checkpoint(offset: at, field: "scene", record: i + 1);
            var header = raw.Slice(at, 12);
            ushort id = BinaryPrimitives.ReadUInt16LittleEndian(header);
            ushort model = BinaryPrimitives.ReadUInt16LittleEndian(header[2..]);
            uint offset = BinaryPrimitives.ReadUInt32LittleEndian(header[4..]);
            uint size = BinaryPrimitives.ReadUInt32LittleEndian(header[8..]);
            if (ids.Contains(id) || offset < 12 + count * 12 || size < 6 || (ulong)offset + size > (ulong)raw.Length)
                throw new EveDoorSourceException("1275 場景長度或偏移無效");
            var reader = new Reader(raw, (int)offset, (int)(offset + size), token);
            // Short-circuiting is observable in the source's read checkpoints.
            if (reader.UInt16() != model || reader.UInt16() != 115)
                throw new EveDoorSourceException("1275 場景內模型 ID／版本不符");
            int npcs = reader.UInt16();
            if (npcs > 4096) throw new EveDoorSourceException("1275 場景 NPC 數量不合理");
            for (int j = 0; j < npcs; j++) SkipNpc(ref reader);
            int doors = reader.UInt16();
            if (doors > 4096) throw new EveDoorSourceException("1275 場景門數量不合理");
            var rows = ImmutableArray.CreateBuilder<EveDoorRow>(doors);
            var seenDoors = new HashSet<ushort>();
            var neededEvents = new HashSet<ushort>();
            for (int j = 0; j < doors; j++)
            {
                budget.Consume(1);
                ushort index = reader.UInt16();
                var common = ReadCommon(ref reader, retain: true, budget);
                uint right = reader.UInt32(), bottom = reader.UInt32();
                byte signType = reader.UInt8();
                uint signX = reader.UInt32(), signY = reader.UInt32();
                uint colX = reader.UInt32(), colY = reader.UInt32(), colZ = reader.UInt32();
                if (!seenDoors.Add(index)) throw new EveDoorSourceException("1275 場景內重複的門事件 index");
                foreach (byte eventId in common.Events) neededEvents.Add(eventId);
                rows.Add(new(index, common.Name, common.X, common.Y, common.Events, right, bottom, signType,
                    signX, signY, colX, colY, colZ, [], []));
            }
            var touch = ReadTouchEvents(ref reader, neededEvents, budget);
            var conveys = ReadConveys(ref reader, (int)offset, (int)size, budget);
            // Build each event once. Python mutates shared event dictionaries repeatedly;
            // immutable sharing preserves the exact values and duplicate reference order.
            var resolved = new Dictionary<ushort, EveDoorTouchEvent>();
            foreach (var (index, item) in touch)
            {
                var transfers = ImmutableArray.CreateBuilder<EveDoorTransfer>();
                var missing = ImmutableArray.CreateBuilder<ushort>();
                foreach (var condition in item.Conditions)
                    foreach (var effect in condition.Results)
                    {
                        token.ThrowIfCancellationRequested();
                        if (effect.ParaMain != 1 || effect.ParaKind != 3) continue;
                        budget.Consume(1);
                        if (conveys.TryGetValue(effect.ParaStyle, out var convey)) transfers.Add(new(convey, condition.Data));
                        else missing.Add(effect.ParaStyle);
                    }
                resolved.Add(index, item with { ConveyTransfers = transfers.ToImmutable(), MissingConveyIds = missing.ToImmutable(),
                    DestinationDecoded = transfers.Count > 0 && missing.Count == 0 });
            }
            for (int j = 0; j < rows.Count; j++)
            {
                token.ThrowIfCancellationRequested();
                var eventIds = ImmutableArray.CreateBuilder<byte>();
                var records = ImmutableArray.CreateBuilder<EveDoorTouchEvent>();
                foreach (byte eventId in rows[j].EventIds)
                    if (resolved.TryGetValue(eventId, out var item))
                    {
                        budget.Consume(2);
                        eventIds.Add(eventId);
                        records.Add(item);
                    }
                rows[j] = rows[j] with { TouchEventIds = eventIds.ToImmutable(), TouchEventRecords = records.ToImmutable() };
            }
            budget.Consume(1);
            scenes.Add(new(id, rows.MoveToImmutable()));
            ids.Add(id);
            doorCount += doors;
        }
        token.ThrowIfCancellationRequested();
        return new(scenes.MoveToImmutable(), doorCount);
    }

    private static EveDoorName ReadName(ref Reader reader)
    {
        var raw = reader.Take(20);
        int zero = raw.IndexOf((byte)0);
        if (zero >= 0) raw = raw[..zero];
        string original = Convert.ToHexStringLower(raw);
        if (!raw.IsEmpty && raw[0] == raw.Length - 1) raw = raw[1..];
        string? name = EveDoorCp950.Decode(raw);
        if (name is null) return new(null, original, false);
        int first = 0, last = name.Length;
        while (first < last && PythonWhitespace(name[first])) first++;
        while (last > first && PythonWhitespace(name[last - 1])) last--;
        name = name[first..last];
        bool valid = name.Length > 0 && !name.Any(ch => ch < 32);
        return new(valid ? name : null, original, valid);
    }
    private static bool PythonWhitespace(char value) => value is >= '\u0009' and <= '\u000D'
        or >= '\u001C' and <= '\u0020' or '\u0085' or '\u00A0' or '\u1680'
        or >= '\u2000' and <= '\u200A' or '\u2028' or '\u2029' or '\u202F' or '\u205F' or '\u3000';
    private readonly record struct Common(EveDoorName Name, uint X, uint Y, ImmutableArray<byte> Events);
    private static Common ReadCommon(ref Reader reader, bool retain, RetainedBudget? budget = null)
    {
        var name = ReadName(ref reader);
        reader.UInt8();
        uint x = reader.UInt32(), y = reader.UInt32();
        int count = reader.UInt8();
        var bytes = reader.Take(count);
        if (retain) budget!.Consume(count);
        var events = retain ? ImmutableArray.CreateRange(bytes.ToArray()) : ImmutableArray<byte>.Empty;
        reader.Skip(reader.UInt8());
        reader.UInt8();
        return new(name, x, y, events);
    }
    private static void SkipNpc(ref Reader reader)
    {
        reader.UInt16();
        ReadCommon(ref reader, false);
        reader.Skip(7);
        reader.Skip(reader.UInt8() * 12);
        reader.Skip(13);
        reader.Skip(reader.UInt8() * 103);
        reader.Skip(38);
    }
    private static EveDoorConditionData ReadCondition(ref Reader reader)
    {
        var bytes = reader.Take(22);
        return new(bytes[0], bytes[1], U16(bytes[2..]), U16(bytes[4..]), U16(bytes[6..]), bytes[8],
            U32(bytes[9..]), bytes[13], U32(bytes[14..]), U32(bytes[18..]));
    }
    private static EveDoorResultData ReadResult(ref Reader reader)
    {
        var bytes = reader.Take(22);
        return new(bytes[0], bytes[1], U16(bytes[2..]), U16(bytes[4..]), U16(bytes[6..]), bytes[8],
            BinaryPrimitives.ReadInt32LittleEndian(bytes[9..]), bytes[13], U32(bytes[14..]), U32(bytes[18..]));
    }
    private static ushort U16(ReadOnlySpan<byte> bytes) => BinaryPrimitives.ReadUInt16LittleEndian(bytes);
    private static uint U32(ReadOnlySpan<byte> bytes) => BinaryPrimitives.ReadUInt32LittleEndian(bytes);

    private static Dictionary<ushort, EveDoorTouchEvent> ReadTouchEvents(ref Reader reader, HashSet<ushort> needed, RetainedBudget budget)
    {
        for (int tail = 10; tail <= 11; tail++)
        {
            int objects = reader.UInt16();
            if (objects > 4096) throw new EveDoorSourceException("Eve 事件物件數量不合理");
            for (int j = 0; j < objects; j++)
            {
                reader.UInt16();
                ReadCommon(ref reader, false);
                reader.Skip(tail);
            }
        }
        int count = reader.UInt16();
        if (count > 4096) throw new EveDoorSourceException("Eve 事件數量不合理");
        var seen = new HashSet<ushort>();
        var touch = new Dictionary<ushort, EveDoorTouchEvent>();
        for (int i = 0; i < count; i++)
        {
            ushort index = reader.UInt16();
            byte occur = reader.UInt8();
            if (!seen.Add(index)) throw new EveDoorSourceException("Eve 場景內重複的事件 index");
            var name = ReadName(ref reader);
            bool keep = (occur & 2) != 0 && needed.Contains(index);
            var conditions = ImmutableArray.CreateBuilder<EveDoorCondition>();
            int conditionCount = reader.UInt8();
            for (int j = 0; j < conditionCount; j++)
            {
                if (keep)
                {
                    budget.Consume(1);
                    var data = ReadCondition(ref reader);
                    int resultCount = reader.UInt8();
                    budget.Consume(resultCount);
                    var results = ImmutableArray.CreateBuilder<EveDoorResultData>(resultCount);
                    for (int k = 0; k < resultCount; k++) results.Add(ReadResult(ref reader));
                    conditions.Add(new(data, results.MoveToImmutable()));
                }
                else
                {
                    reader.Skip(22);
                    reader.Skip(22 * reader.UInt8());
                }
            }
            if (keep)
            {
                budget.Consume(1);
                touch.Add(index, new(index, occur, name, conditions.ToImmutable(), [], [], false));
            }
        }
        return touch;
    }

    private static Dictionary<ushort, EveDoorConvey> ReadConveys(ref Reader reader, int start, int size, RetainedBudget budget)
    {
        if (size < 48) throw new EveDoorSourceException("Eve 場景缺少區段索引");
        // struct.unpack_from reads the directory without moving the Reader checkpoint.
        var offsets = reader.Raw.Slice(start + size - 44, 44);
        uint groups = U32(offsets[20..]), conveys = U32(offsets[24..]), next = U32(offsets[28..]);
        if (groups != reader.Position - start || groups < 4 || groups > conveys || conveys > next || next > size - 44)
            throw new EveDoorSourceException("Eve 群組／傳送區段偏移不符");
        int count = reader.UInt16();
        for (int i = 0; i < count; i++)
        {
            reader.Skip(27);
            reader.Skip(3 * reader.UInt16());
        }
        if (reader.Position != start + conveys) throw new EveDoorSourceException("Eve 群組區段長度不符");
        var rows = new Dictionary<ushort, EveDoorConvey>();
        count = reader.UInt16();
        for (int i = 0; i < count; i++)
        {
            ushort index = reader.UInt16();
            var name = ReadName(ref reader);
            ushort destination = reader.UInt16();
            uint x = reader.UInt32(), y = reader.UInt32();
            reader.UInt8(); // Direction and links are consumed, not guessed or retained.
            reader.UInt16();
            if (rows.ContainsKey(index)) throw new EveDoorSourceException("Eve 傳送編號重複或目的地無效");
            budget.Consume(1);
            rows.Add(index, new(index, destination, x, y, name));
        }
        if (reader.Position != start + next) throw new EveDoorSourceException("Eve 傳送區段長度不符");
        return rows;
    }

    private sealed class RetainedBudget
    {
        private int remaining = MaxRetainedUnits;
        internal void Consume(int units)
        {
            if (units > remaining) throw new EveDoorSourceException("Eve door projection exceeds retained data limit");
            remaining -= units;
        }
    }
    private ref struct Reader(ReadOnlySpan<byte> raw, int start, int end, CancellationToken token)
    {
        internal readonly ReadOnlySpan<byte> Raw = raw;
        internal int Position = start;
        internal ReadOnlySpan<byte> Take(int length)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.ReadCheckpoint(Position, length, end - Position);
            if (length < 0 || length > end - Position) throw new EveDoorSourceException("Eve Door 解析超出範圍");
            var result = Raw.Slice(Position, length);
            Position += length;
            return result;
        }
        internal void Skip(int length) => Take(length);
        internal byte UInt8() => Take(1)[0];
        internal ushort UInt16() => U16(Take(2));
        internal uint UInt32() => U32(Take(4));
    }
}
