using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;

namespace Lala.Core.World.Eve;

public enum EveSection { Npc, Door, Mine, Goods, Event, Group, Convey, Interact, Battle, LeadEvent, LeadGroup }

/// <summary>Only bounded numeric locations and a code-owned section; no names, input bytes or paths.</summary>
public sealed record EveParseLocation(int Offset, ushort? SceneId = null, EveSection? Section = null,
    int? Record = null, int? RequestedBytes = null, int? AvailableBytes = null);
public sealed class EveDecodeException : FormatException
{
    public const string Schema = "eve-v115";
    public EveParseLocation? Location { get; }
    internal EveDecodeException(string message, EveParseLocation? location = null) : base(message) => Location = location;
}

/// <summary>Strict read-only port of world/eve_v115.py. Every scene and all eleven sections are
/// validated even when only one index is selected. No file/network access or runtime authority.</summary>
public static class EveV115Parser
{
    public const string NpcSource = "EventData.NewNpc";
    public const string InteractionSource = "EventData.NewInteract";
    public const int MaxSourceBytes = 16 * 1024 * 1024;
    public const int MaxScenes = 4096;
    public const int MaxRecords = 20_000;
    public const int MaxRowsPerType = 4096;
    public const int SectionOffsetBytes = 44;
    private static readonly string[] SectionNames =
        ["npc", "door", "mine", "goods", "event", "group", "convey", "interact", "battle", "lead_event", "lead_group"];

    public static EveV115Indexes Parse(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default) =>
        ParseCore(raw, null, cancellationToken);
    public static EveV115Indexes Parse(ReadOnlySpan<byte> raw, string source, CancellationToken cancellationToken = default) =>
        ParseCore(raw, source ?? "", cancellationToken);
    public static ImmutableArray<byte> DeriveIndex(ReadOnlySpan<byte> raw, string source, CancellationToken cancellationToken = default) =>
        Parse(raw, source, cancellationToken).ToJsonUtf8(source, cancellationToken);
    public static ImmutableDictionary<string, ImmutableArray<byte>> DeriveIndexes(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default)
    {
        var indexes = Parse(raw, cancellationToken);
        return ImmutableDictionary<string, ImmutableArray<byte>>.Empty
            .Add(NpcSource, indexes.ToJsonUtf8(NpcSource, cancellationToken))
            .Add(InteractionSource, indexes.ToJsonUtf8(InteractionSource, cancellationToken));
    }

    private static EveV115Indexes ParseCore(ReadOnlySpan<byte> raw, string? source, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (raw.Length is < 12 or > MaxSourceBytes) throw new EveDecodeException("Missing or oversized Eve source");
        if (source is not (null or NpcSource or InteractionSource)) throw new EveDecodeException("Unknown requested Eve index");
        // Snapshot caller-owned input before validating headers or offsets. Bound before allocating.
        byte[] bytes = raw.ToArray();
        token.ThrowIfCancellationRequested();
        uint count = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(8));
        if (count is 0 or > MaxScenes || 12 + 12 * count > bytes.Length)
            throw new EveDecodeException("Eve header/scene count invalid");
        var segments = new Segment[count];
        var ids = new HashSet<ushort>();
        for (int index = 0; index < segments.Length; index++)
        {
            token.ThrowIfCancellationRequested();
            int position = 12 + 12 * index;
            var header = bytes.AsSpan(position, 12);
            ushort id = BinaryPrimitives.ReadUInt16LittleEndian(header);
            uint offset = BinaryPrimitives.ReadUInt32LittleEndian(header[4..]);
            uint size = BinaryPrimitives.ReadUInt32LittleEndian(header[8..]);
            // Deliberate fail-closed correction: Python checks an int against string scene keys.
            // Do not reproduce its duplicate-ID overwrite and inconsistent total record count.
            if (!ids.Add(id) || offset < 12 + 12 * count || size < 6 || (ulong)offset + size > (ulong)bytes.Length)
                throw new EveDecodeException("Duplicate scene ID or out-of-bounds offset", new(position));
            segments[index] = new(id, (int)offset, (int)size);
        }
        Array.Sort(segments, (a, b) => a.Offset.CompareTo(b.Offset));
        bool npcs = source is null or NpcSource, interactions = source is null or InteractionSource;
        var scenes = ImmutableArray.CreateBuilder<EveSceneIndexes>(segments.Length);
        int npcCount = 0, interactionCount = 0;
        for (int index = 0; index < segments.Length; index++)
        {
            token.ThrowIfCancellationRequested();
            var segment = segments[index];
            if (index > 0 && segments[index - 1].Offset + segments[index - 1].Size > segment.Offset)
                throw new EveDecodeException("Eve scene segments overlap", new(segment.Offset));
            var reader = new Reader(bytes, segment, token);
            EveSceneIndexes scene;
            try { scene = ReadScene(ref reader, npcs, interactions); }
            catch (EveDecodeException error)
            {
                throw new EveDecodeException(F($"場景 {segment.Id}（偏移 {segment.Offset}，長度 {segment.Size}）：{error.Message}"), error.Location);
            }
            npcCount += scene.Npcs.Length;
            interactionCount += scene.Interactions.Length;
            if (npcCount > MaxRecords || interactionCount > MaxRecords)
                throw new EveDecodeException("Eve selected index exceeds record limit", reader.Location());
            scenes.Add(scene);
        }
        token.ThrowIfCancellationRequested();
        return new(scenes.OrderBy(s => s.SceneId).ToImmutableArray(), npcs, interactions, npcCount, interactionCount);
    }

    private static EveSceneIndexes ReadScene(ref Reader reader, bool npcs, bool interactions)
    {
        reader.Skip(2); // Model IDs are ignored by the source, including header/body disagreement.
        if (reader.UInt16() != 115) throw reader.Error("Unsupported Eve scene format, expected 115");
        var npcRows = ImmutableArray.CreateBuilder<EveNpcRow>();
        var interactionRows = ImmutableArray.CreateBuilder<EveInteractionRow>();
        Span<int> offsets = stackalloc int[11];
        Span<int> counts = stackalloc int[11];
        for (int section = 0; section < 11; section++)
        {
            reader.Section = (EveSection)section;
            reader.Record = null;
            offsets[section] = reader.RelativePosition;
            try
            {
                int count = reader.UInt16();
                if (count > MaxRowsPerType) throw reader.Error("Eve per-scene event count exceeds limit");
                counts[section] = count;
                var seen = section is 0 or 7 ? new HashSet<ushort>() : null;
                for (int record = 0; record < count; record++)
                {
                    reader.Record = record + 1;
                    try
                    {
                        switch (section)
                        {
                            case 0:
                                var npc = ReadNpc(ref reader, npcs);
                                if (!seen!.Add(npc.Index)) throw reader.Error("Duplicate event index in scene");
                                if (npcs) npcRows.Add(npc);
                                break;
                            case 7:
                                var interaction = ReadInteraction(ref reader, interactions);
                                if (!seen!.Add(interaction.Index)) throw reader.Error("Duplicate event index in scene");
                                if (interactions) interactionRows.Add(interaction);
                                break;
                            case 4 or 9: SkipEvent(ref reader); break;
                            case 5 or 10:
                                reader.Skip(27);
                                reader.Skip(3 * reader.UInt16());
                                break;
                            case 8:
                                reader.Skip(2);
                                ReadCommon(ref reader, false);
                                reader.Skip(4);
                                reader.Skip(3 * reader.UInt8());
                                reader.Skip(3 * reader.UInt8());
                                reader.Skip(1);
                                break;
                            case 1 or 2 or 3:
                                reader.Skip(2);
                                ReadCommon(ref reader, false);
                                reader.Skip(section == 1 ? 29 : section == 2 ? 10 : 11);
                                break;
                            default: reader.Skip(35); break; // convey
                        }
                    }
                    catch (EveDecodeException error)
                    {
                        throw new EveDecodeException(F($"{SectionNames[section]} 第 {record + 1}/{count} 筆（場景內偏移 {reader.RelativePosition}）：{error.Message}"), error.Location);
                    }
                }
            }
            catch (EveDecodeException error) when (reader.Record is null)
            {
                throw new EveDecodeException(F($"{SectionNames[section]} 區段（場景內偏移 {reader.RelativePosition}）：{error.Message}"), error.Location);
            }
        }
        reader.Section = null;
        reader.Record = null;
        if (reader.Remaining != SectionOffsetBytes)
        {
            bool zero = reader.Remaining > 0 && reader.RemainingIsZero();
            var sizes = new string[11];
            for (int index = 0; index < sizes.Length; index++) sizes[index] = F($"{SectionNames[index]}:{counts[index]}");
            throw reader.Error(F($"Eve v115 section offset table length mismatch（已讀 {reader.RelativePosition}，剩餘 {reader.Remaining} bytes，預期 {SectionOffsetBytes} bytes，尾段全零={(zero ? "True" : "False")}，事件數={string.Join(',', sizes)}）"));
        }
        for (int section = 0; section < 11; section++)
        {
            reader.Section = (EveSection)section;
            uint recorded = reader.UInt32();
            if (recorded != offsets[section])
                throw reader.Error(F($"Eve v115 offset table differs at {SectionNames[section]}: expected {offsets[section]}, got {recorded}"));
        }
        return new(reader.SceneId, npcRows.ToImmutable(), interactionRows.ToImmutable());
    }

    private static EveNpcRow ReadNpc(ref Reader reader, bool retain)
    {
        ushort index = reader.UInt16();
        var (x, y, events) = ReadCommon(ref reader, retain);
        uint id = reader.UInt32();
        reader.Skip(3);
        reader.Skip(reader.UInt8() * 12);
        reader.Skip(13);
        reader.Skip(reader.UInt8() * 103);
        reader.Skip(38);
        if (id == 0) throw reader.Error("NPC source ID is invalid");
        return new(index, id, x, y, events);
    }
    private static (uint X, uint Y, ImmutableArray<byte> Events) ReadCommon(ref Reader reader, bool retain)
    {
        reader.Skip(21);
        uint x = reader.UInt32(), y = reader.UInt32();
        var events = reader.Take(reader.UInt8());
        var retained = retain ? ImmutableArray.CreateRange(events.ToArray()) : ImmutableArray<byte>.Empty;
        reader.Skip(reader.UInt8());
        reader.Skip(1);
        return (x, y, retained);
    }
    private static EveInteractionRow ReadInteraction(ref Reader reader, bool retain)
    {
        ushort index = reader.UInt16();
        reader.Skip(20);
        byte form = reader.UInt8();
        ushort link = reader.UInt16();
        byte count = reader.UInt8();
        if (form is not (1 or 2 or 3)) throw reader.Error("Unknown interaction form kind");
        var items = retain ? ImmutableArray.CreateBuilder<EveInteractionItem>(count) : null;
        for (int item = 0; item < count; item++)
        {
            byte id = reader.UInt8();
            ushort text = reader.UInt16();
            byte database = reader.UInt8(), kind = reader.UInt8();
            items?.Add(new(id, text, database, kind));
        }
        return new(index, form, link, items?.MoveToImmutable() ?? ImmutableArray<EveInteractionItem>.Empty);
    }
    private static void SkipEvent(ref Reader reader)
    {
        reader.Skip(23);
        int count = reader.UInt8();
        for (int index = 0; index < count; index++)
        {
            reader.Skip(22);
            reader.Skip(22 * reader.UInt8());
        }
    }
    private static string F(FormattableString value) => value.ToString(CultureInfo.InvariantCulture);
    private readonly record struct Segment(ushort Id, int Offset, int Size);

    private ref struct Reader(byte[] data, Segment segment, CancellationToken token)
    {
        private readonly byte[] data = data;
        private readonly Segment segment = segment;
        private readonly CancellationToken token = token;
        private int position = segment.Offset;
        public ushort SceneId => segment.Id;
        public int RelativePosition => position - segment.Offset;
        public int Remaining => segment.Offset + segment.Size - position;
        public EveSection? Section { get; set; }
        public int? Record { get; set; }
        public EveParseLocation Location() => new(position, SceneId, Section, Record);
        public EveDecodeException Error(string message) => new(message, Location());
        public ReadOnlySpan<byte> Take(int length)
        {
            token.ThrowIfCancellationRequested();
            if (length < 0 || length > Remaining)
                throw new EveDecodeException("Eve record exceeds verified scene limits", new(position, SceneId, Section, Record, length, Remaining));
            var value = data.AsSpan(position, length);
            position += length;
            return value;
        }
        public void Skip(int length) => Take(length);
        public byte UInt8() => Take(1)[0];
        public ushort UInt16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
        public uint UInt32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
        public bool RemainingIsZero()
        {
            // Check in bounded chunks without moving the diagnostic cursor.
            for (int offset = position; offset < segment.Offset + segment.Size; offset += 4096)
            {
                token.ThrowIfCancellationRequested();
                if (data.AsSpan(offset, Math.Min(4096, segment.Offset + segment.Size - offset)).ContainsAnyExcept((byte)0)) return false;
            }
            return true;
        }
    }
}
