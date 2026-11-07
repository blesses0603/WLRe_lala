using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Lala.Core.World.Portals;

public sealed class PortalProjectionException(string message) : FormatException(message);
public readonly record struct PortalReferenceKey(ushort Scene, uint Index);
public sealed record StagePortalRow(ushort Scene, byte Kind, ushort CrossScene, uint EventId,
    ushort X, ushort Y, uint NameId, byte Sorting);
public sealed record EvePortalLink(ushort Scene, int Index, ushort X, ushort Y, ushort Destination, ushort ArrivalX, ushort ArrivalY);
public sealed record PortalRouteRow(ushort Scene, ushort X, ushort Y, ushort Destination, ushort ArrivalX, ushort ArrivalY);
public sealed record ParsedStagePortals(ImmutableArray<StagePortalRow> Rows,
    ImmutableDictionary<PortalReferenceKey, StagePortalRow> UniqueMarkers);

/// <summary>Read-only reviewed layouts, not source authentication. All payloads and retained
/// rows are bounded; no path, source provider, activation or transport is involved.</summary>
public static class OfflinePortalSources
{
    public const int MaximumRows = 100_000;
    public const int MaximumLinkBytes = 4 * 1024 * 1024;
    public static ParsedStagePortals ParseStageMap(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        int count = Count(raw, 18);
        var rows = ImmutableArray.CreateBuilder<StagePortalRow>(count);
        var unique = new Dictionary<PortalReferenceKey, StagePortalRow?>();
        for (int i = 0; i < count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var r = raw.Slice(4 + i * 18, 18);
            var row = new StagePortalRow(U16(r), r[2], U16(r[3..]), U32(r[5..]), U16(r[9..]), U16(r[11..]), U32(r[13..]), r[17]);
            if (row.Kind > 5) throw new PortalProjectionException("Unknown StageMap marker kind");
            rows.Add(row);
            if (row.Kind is not (2 or 3) || row.Scene == 0 || row.EventId == 0) continue;
            var key = new PortalReferenceKey(row.Scene, row.EventId);
            if (!unique.TryAdd(key, row)) unique[key] = null;
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(rows.MoveToImmutable(), unique.Where(p => p.Value is not null).ToImmutableDictionary(p => p.Key, p => p.Value!));
    }

    public static ImmutableDictionary<ushort, ImmutableArray<EvePortalLink>> ParseEveLinks(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (raw.Length == 0 || raw.Length % 2 != 0 || raw.Length > MaximumLinkBytes)
            throw new PortalProjectionException("Invalid EveDoorLinks byte length");
        string text;
        try { text = new UnicodeEncoding(false, false, true).GetString(raw).TrimStart('\ufeff'); }
        catch (DecoderFallbackException) { throw new PortalProjectionException("Invalid EveDoorLinks UTF-16LE"); }
        // Python decimal fields accept all Unicode Nd digits, including supplementary ones.
        var normalized = new StringBuilder(text.Length);
        foreach (var rune in text.EnumerateRunes())
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (Rune.GetUnicodeCategory(rune) == UnicodeCategory.DecimalDigitNumber)
                normalized.Append((char)('0' + (int)Rune.GetNumericValue(rune)));
            else normalized.Append(rune.ToString());
        }
        var result = new Dictionary<ushort, ImmutableArray<EvePortalLink>.Builder>();
        ushort? scene = null;
        foreach (string part in Lines.Split(normalized.ToString()))
        {
            cancellationToken.ThrowIfCancellationRequested();
            string line = PythonStrip(part);
            if (line.Length == 0) continue;
            var header = Header.Match(line);
            if (header.Success)
            {
                int id = Decimal(header.Groups[1].Value, ushort.MaxValue);
                if (id == 0 || !result.TryAdd((ushort)id, ImmutableArray.CreateBuilder<EvePortalLink>()))
                    throw new PortalProjectionException("Duplicate or invalid EveDoorLinks scene");
                scene = (ushort)id; continue;
            }
            if (scene is null) throw new PortalProjectionException("Missing EveDoorLinks scene header");
            var fields = Brackets.Matches(line);
            if (fields.Count != 3 || !line.StartsWith("原場景位置", StringComparison.Ordinal))
                throw new PortalProjectionException("Invalid EveDoorLinks fields");
            var source = Point.Match(fields[0].Groups[1].Value); var arrival = Point.Match(fields[2].Groups[1].Value);
            string target = fields[1].Groups[1].Value;
            if (!source.Success || !arrival.Success || target.Length == 0 || target.Any(c => c is < '0' or > '9'))
                throw new PortalProjectionException("Invalid EveDoorLinks numeric field");
            int destination = Decimal(target, ushort.MaxValue);
            if (destination == 0) throw new PortalProjectionException("Invalid EveDoorLinks destination");
            var rows = result[scene.Value];
            rows.Add(new(scene.Value, rows.Count + 1, (ushort)Decimal(source.Groups[1].Value, ushort.MaxValue),
                (ushort)Decimal(source.Groups[2].Value, ushort.MaxValue), (ushort)destination,
                (ushort)Decimal(arrival.Groups[1].Value, ushort.MaxValue), (ushort)Decimal(arrival.Groups[2].Value, ushort.MaxValue)));
        }
        cancellationToken.ThrowIfCancellationRequested();
        return result.ToImmutableDictionary(p => p.Key, p => p.Value.ToImmutable());
    }
    public static ImmutableArray<PortalRouteRow> ParseDoorRoutes(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        int count = Count(raw, 12); var rows = ImmutableArray.CreateBuilder<PortalRouteRow>(count);
        for (int i = 0; i < count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested(); var r = raw.Slice(4 + i * 12, 12);
            var row = new PortalRouteRow(U16(r), U16(r[2..]), U16(r[4..]), U16(r[6..]), U16(r[8..]), U16(r[10..]));
            if (row.Scene == 0 || row.Destination == 0) throw new PortalProjectionException("Zero DoorLinkData scene");
            rows.Add(row);
        }
        cancellationToken.ThrowIfCancellationRequested(); return rows.MoveToImmutable();
    }
    private static int Count(ReadOnlySpan<byte> raw, int width)
    {
        if (raw.Length < 4) throw new PortalProjectionException("Missing portal table header");
        int count = BinaryPrimitives.ReadInt32LittleEndian(raw);
        if (count is < 0 or > MaximumRows || raw.Length != 4 + count * width) throw new PortalProjectionException("Portal table count or length mismatch");
        return count;
    }
    private static string PythonStrip(string value)
    {
        static bool White(char c) => char.IsWhiteSpace(c) || c is >= '\x1c' and <= '\x1f';
        int start = 0, end = value.Length;
        while (start < end && White(value[start])) start++;
        while (end > start && White(value[end - 1])) end--;
        return value[start..end];
    }
    private static int Decimal(string value, int maximum)
    {
        // Match the retained CPython oracle's default decimal conversion limit, including zeros.
        if (value.Length > 4300) throw new PortalProjectionException("Portal decimal digit limit exceeded");
        // Bounded accumulation avoids BigInteger allocation.
        int result = 0;
        foreach (char c in value)
        {
            if (c is < '0' or > '9' || result > (maximum - (c - '0')) / 10)
                throw new PortalProjectionException("Portal numeric field exceeds range");
            result = result * 10 + c - '0';
        }
        return result;
    }
    private static ushort U16(ReadOnlySpan<byte> r) => BinaryPrimitives.ReadUInt16LittleEndian(r);
    private static uint U32(ReadOnlySpan<byte> r) => BinaryPrimitives.ReadUInt32LittleEndian(r);
    private const string Ws = @"[\s\x1c-\x1f]";
    private static readonly Regex Lines = new(@"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex Header = new("^" + Ws + @"*(?:事件ID|\[事件ID\])" + Ws + "*=" + Ws + @"*([0-9]+)" + Ws + "*$", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex Brackets = new(@"\[([^\[\]]*)\]", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex Point = new("^" + Ws + @"*[^:：\[\],]+[:：]" + Ws + @"*([0-9]+)" + Ws + "*," + Ws + @"*[^:：\[\],]+[:：]" + Ws + @"*([0-9]+)" + Ws + "*$", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
}

/// <summary>A defensive comparison/retention budget for supplied offline projections. This cap
/// intentionally rejects excessive synthetic combinations that Python may process without a cap.</summary>
public sealed record PortalProjectionBudget(int MaximumOperations = 2_000_000)
{
    internal PortalWork Start(CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (MaximumOperations is < 1 or > 10_000_000) throw new ArgumentOutOfRangeException(nameof(MaximumOperations));
        return new(MaximumOperations, token);
    }
}
internal sealed class PortalWork(int maximum, CancellationToken token)
{
    private int _remaining = maximum;
    internal void Step() { token.ThrowIfCancellationRequested(); if (--_remaining < 0) throw new PortalProjectionException("Offline portal projection budget exceeded"); }
    internal void Check() => token.ThrowIfCancellationRequested();
}
