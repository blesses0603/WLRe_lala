using System.Buffers.Binary;
using System.Globalization;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record StageDataRow(ushort Id, uint NameId, ushort ModelId, byte MaxMembers,
    byte MinMembers, ushort MinLevel, ushort TimeMinutes, byte Tag, byte RoomCapacity,
    byte Group, ushort Flag, byte PosXRatio, byte PosYRatio, ushort MapWidth,
    ushort MapHeight, ushort SmallOffsetX, ushort SmallOffsetY);

/// <summary>Offline ScenesData_C StageData:New fields only. No entry or transfer authority.</summary>
public static class StageDataParser
{
    public const int MaxRecords = 20_000;
    public const int RecordBytes = 76;
    public const int MaxBytes = 4 + MaxRecords * RecordBytes;
    private static readonly ParserDiagnosticDefinition Diagnostic =
        new("wlre.services.instance_catalog.parse_stages", "stage-76-v1");

    public static IReadOnlyDictionary<ushort, StageDataRow> Parse(ReadOnlySpan<byte> data,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // Oversized inputs still follow source read/duplicate/trailing failure ordering.
        ReadOnlySpan<byte> snapshot = data.Length <= MaxBytes ? data.ToArray() : data;
        return ParserDiagnostics.RunWithRaw(Diagnostic, snapshot,
            bytes => Read(bytes, cancellationToken), rows => new(rows.Count), null,
            cancellationToken, inputName: "data");
    }

    private static IReadOnlyDictionary<ushort, StageDataRow> Read(ReadOnlySpan<byte> data, CancellationToken token)
    {
        var reader = new StageReader(data, token);
        int count = BinaryPrimitives.ReadInt32LittleEndian(reader.Take(4));
        if (count is < 0 or > MaxRecords) throw new CatalogDecodeException("副本資料筆數超出安全範圍");
        var result = new Dictionary<ushort, StageDataRow>();
        var order = new List<ushort>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            ushort id = reader.U16();
            reader.Take(2);
            uint name = reader.U32();
            ushort model = reader.U16();
            reader.U16();
            reader.Take(3);
            reader.Take(2);
            reader.Take(4);
            byte max = reader.U8(), tag = reader.U8(), min = reader.U8(), capacity = reader.U8(), group = reader.U8();
            ushort flag = reader.U16(), level = reader.U16(), minutes = reader.U16();
            reader.Take(20);
            ushort width = reader.U16(), height = reader.U16();
            reader.U8();
            byte xRatio = reader.U8(), yRatio = reader.U8();
            ushort xOffset = reader.U16(), yOffset = reader.U16();
            reader.Take(8);
            reader.Take(5);
            // Source validates duplication only after reading the complete duplicate row.
            if (result.ContainsKey(id)) throw new CatalogDecodeException("重複 StageData ID");
            result.Add(id, new(id, name, model, max, min, level, minutes, tag, capacity, group,
                flag, xRatio, yRatio, width, height, xOffset, yOffset));
            order.Add(id);
        }
        reader.End();
        token.ThrowIfCancellationRequested();
        return new OrderedCatalog<ushort, StageDataRow>(result, order);
    }

    // Match each wire.Reader take exactly, including discarded source fields and cursor state.
    private ref struct StageReader(ReadOnlySpan<byte> data, CancellationToken token)
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
            var result = data.Slice(Position, size);
            Position += size;
            return result;
        }
        public byte U8() => Take(1)[0];
        public ushort U16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
        public uint U32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
        public void End()
        {
            ParserDiagnostics.ReadCheckpoint(Position, 0, Remaining);
            if (Remaining != 0) throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                $"unexpected trailing bytes: {Remaining}"));
        }
    }
}
