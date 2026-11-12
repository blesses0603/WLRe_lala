using System.Buffers.Binary;
using System.Collections.Immutable;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Lala.Core.World;

namespace Lala.Core.Resources;

internal sealed record ReviewedNavigationModel(ushort Model, string Sha256, int Length, ImmutableArray<string> Bundles);
internal sealed record ReviewedNavigationGeometry(NavigationPoint Origin, PreviewNavigationMesh Mesh);

internal static class ReviewedNavigationCache
{
    internal const int MaxBytes = 8 * 1024 * 1024;
    internal const string MainSha256 = "faaab749110cf9e68be784e613e94579d51e92015ad8ef21e68de4aebbb5ba98";
    internal static readonly IReadOnlyDictionary<ushort, ReviewedNavigationModel> Models = ReadRegistry();
    private static IReadOnlyDictionary<ushort, ReviewedNavigationModel> ReadRegistry()
    {
        using var pinsStream = typeof(ReviewedNavigationCache).Assembly.GetManifestResourceStream("Lala.Core.NavigationPins.json")!;
        using var auditStream = typeof(ReviewedNavigationCache).Assembly.GetManifestResourceStream("Lala.Core.NavigationAudit.json")!;
        using var pins = JsonDocument.Parse(pinsStream); using var audit = JsonDocument.Parse(auditStream);
        if (audit.RootElement.GetProperty("manifest_sha256").GetString() != MainSha256) throw new InvalidDataException("Navigation review identity mismatch.");
        var rows = new Dictionary<ushort, ReviewedNavigationModel>();
        foreach (var row in audit.RootElement.GetProperty("models").EnumerateArray())
        {
            if (row.GetProperty("status").GetString() != "preview_supported") continue;
            ushort model = row.GetProperty("model").GetUInt16(); string sha = row.GetProperty("sha256").GetString()!;
            if (!pins.RootElement.TryGetProperty(model.ToString(), out var pin) || pin.GetString() != sha) throw new InvalidDataException("Navigation model review mismatch.");
            rows.Add(model, new(model, sha, row.GetProperty("cache_bytes").GetInt32(), [..row.GetProperty("bundles").EnumerateArray().Select(b => b.GetProperty("name").GetString()!)]));
        }
        return rows.ToImmutableDictionary();
    }
    internal static ReviewedNavigationGeometry Decode(ReadOnlyMemory<byte> raw, ReviewedNavigationModel model, string mode, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (raw.Length != model.Length || raw.Length > MaxBytes || Convert.ToHexStringLower(SHA256.HashData(raw.Span)) != model.Sha256)
            throw new NavigationException("導航快取與已核對的官方指紋不符。");
        return DecodeFormat(raw, model.Model, mode, token);
    }
    internal static ReviewedNavigationGeometry DecodeFormat(ReadOnlyMemory<byte> raw, ushort model, string mode, CancellationToken token)
    {
        using var zip = new ZipArchive(new MemoryStream(raw.ToArray(), false), ZipArchiveMode.Read);
        string[] names = ["graph0.json", "graph_references.binary", "graph0_extra.binary", "graph0_references.binary", "node_link2.binary", "meta.json"];
        if (zip.Entries.Count != 6 || !zip.Entries.Select(e => e.FullName).Order().SequenceEqual(names.Order()) || zip.Entries.Sum(e => e.Length) > MaxBytes)
            throw new NavigationException("導航封存成員或大小不符。");
        var parts = new Dictionary<string, byte[]>();
        foreach (var entry in zip.Entries)
        {
            token.ThrowIfCancellationRequested(); using var input = entry.Open();
            var bytes = new byte[checked((int)entry.Length)]; input.ReadExactly(bytes);
            if (input.ReadByte() != -1) throw new NavigationException("導航成員長度不符。");
            parts.Add(entry.FullName, bytes);
        }
        var text = Encoding.UTF8.GetString(parts["meta.json"]);
        var version = Regex.Matches(text, "\"version\"\\s*:\\s*4\\.3\\.60(?=\\s*,)", RegexOptions.CultureInvariant);
        if (version.Count != 1) throw new NavigationException("未支援的導航序列化版本。");
        using var meta = JsonDocument.Parse(text[..version[0].Index] + "\"version\":\"4.3.60\"" + text[(version[0].Index + version[0].Length)..]);
        using var settings = JsonDocument.Parse(parts["graph0.json"]);
        var root = settings.RootElement;
        if (meta.RootElement.GetProperty("graphs").GetInt32() != 1 || meta.RootElement.GetProperty("typeNames").GetArrayLength() != 1 ||
            meta.RootElement.GetProperty("typeNames")[0].GetString() != "Pathfinding.RecastGraph" ||
            meta.RootElement.GetProperty("guids")[0].GetString() != root.GetProperty("guid").GetProperty("value").GetString() ||
            new[] { "x", "y", "z" }.Any(axis => root.GetProperty("rotation").GetProperty(axis).GetDouble() != 0) ||
            !parts["node_link2.binary"].AsSpan().SequenceEqual(new byte[4])) throw new NavigationException("未核對的導航圖類型或連結。");
        double Axis(string name) => (root.GetProperty("forcedBoundsCenter").GetProperty(name).GetDouble() - root.GetProperty("forcedBoundsSize").GetProperty(name).GetDouble() / 2) * 1000;
        var origin = new NavigationPoint(Axis("x"), Axis("y"), Axis("z"));
        if (!origin.IsInInt3Range) throw new NavigationException("導航原點超出範圍。");
        var r = new Reader(parts["graph0_extra.binary"]);
        if (r.I32() != 1 || r.I32() != 1 || r.I32() != 0 || r.I32() != 0 || r.I32() != 1 || r.I32() != 1) throw new NavigationException("未支援的導航分塊。");
        int indices = r.Count(); if (indices % 3 != 0 || indices / 3 > 10000) throw new NavigationException("導航三角形配額或索引無效。");
        var triangles = Enumerable.Range(0, indices / 3).Select(_ => new[] { r.I32(), r.I32(), r.I32() }).ToArray();
        var verticesA = r.Vertices(); var verticesB = r.Vertices();
        if (verticesA.Length == 0 || verticesA.Length != verticesB.Length || r.Count() != triangles.Length) throw new NavigationException("導航頂點或節點數量不符。");
        for (int i = 0; i < verticesA.Length; i++)
            if (Math.Abs(verticesA[i].X - verticesB[i].X - origin.X) > .501 || Math.Abs(verticesA[i].Y - verticesB[i].Y - origin.Y) > .501 || Math.Abs(verticesA[i].Z - verticesB[i].Z - origin.Z) > .501)
                throw new NavigationException("導航座標轉換不符。");
        var metadata = new NavigationNodeMetadata?[triangles.Length]; var faces = new NavigationTriangle[triangles.Length];
        for (int i = 0; i < triangles.Length; i++)
        {
            token.ThrowIfCancellationRequested(); metadata[i] = new(r.U32(), r.U32());
            if (triangles[i].Any(index => index < 0 || index >= verticesB.Length) || Enumerable.Range(0, 3).Any(j => r.I32() != triangles[i][j])) throw new NavigationException("導航節點索引不符。");
            faces[i] = new(verticesB[triangles[i][0]], verticesB[triangles[i][1]], verticesB[triangles[i][2]]);
        }
        r.End(); r = new(parts["graph_references.binary"]); int maximum = r.Count();
        var refs = new Dictionary<int, int>();
        for (int i = 0; i < triangles.Length; i++) { int id = r.I32(); if (id < 0 || id > maximum || !refs.TryAdd(id, i)) throw new NavigationException("導航參照表無效。"); }
        r.End(); r = new(parts["graph0_references.binary"]);
        var connections = new NavigationConnection[triangles.Length][];
        for (int i = 0; i < triangles.Length; i++)
        {
            int count = r.Count(); if (count > 3) throw new NavigationException("導航節點連結過多。");
            connections[i] = new NavigationConnection[count]; var used = new HashSet<int>();
            for (int j = 0; j < count; j++)
            {
                int id = r.I32(); uint cost = r.U32(); int edge = r.U8();
                if (!refs.TryGetValue(id, out int target) || target == i || !used.Add(target) || edge > 2 ||
                    !triangles[i].Intersect(triangles[target]).Order().SequenceEqual(new[] { triangles[i][edge], triangles[i][(edge + 1) % 3] }.Order())) throw new NavigationException("導航連結不跨越已宣告的共享邊。");
                connections[i][j] = new(target, cost, edge);
            }
        }
        r.End();
        return new(origin, new([new NavigationTile(faces, metadata, token)], connections, mode, "M" + model.ToString("D5"), token));
    }
    private sealed class Reader(byte[] data)
    {
        private int offset;
        internal int I32() { Check(4); int n = BinaryPrimitives.ReadInt32LittleEndian(data.AsSpan(offset, 4)); offset += 4; return n; }
        internal uint U32() => unchecked((uint)I32());
        internal byte U8() { Check(1); return data[offset++]; }
        internal int Count() { int n = I32(); if (n is < 0 or > 100000) throw new NavigationException("導航陣列超出配額。"); return n; }
        internal NavigationPoint[] Vertices() => Enumerable.Range(0, Count()).Select(_ => new NavigationPoint(I32(), I32(), I32())).ToArray();
        internal void End() { if (offset != data.Length) throw new NavigationException("導航資料含未解碼位元組。"); }
        private void Check(int n) { if (offset > data.Length - n) throw new NavigationException("導航資料截斷。"); }
    }
}
