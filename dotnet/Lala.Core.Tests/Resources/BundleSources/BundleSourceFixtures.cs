using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;

namespace Lala.Core.Tests.Resources;

internal static class BundleSourceFixtures
{
    private static readonly Lazy<JsonDocument> Document = new(() => JsonDocument.Parse(typeof(BundleSourceFixtures).Assembly.GetManifestResourceStream(
        "Lala.Core.Tests.Resources.BundleSources.bundle_sources.json")!));
    internal static JsonElement Case(string id) => Document.Value.RootElement.GetProperty("cases").EnumerateArray().Single(x => x.GetProperty("id").GetString() == id);
    internal static IEnumerable<object[]> Ids() => Document.Value.RootElement.GetProperty("cases").EnumerateArray().Select(x => new object[] { x.GetProperty("id").GetString()! });
    internal static string Text(this JsonElement element, string key) => element.GetProperty(key).GetString()!;
    internal static byte[] Bytes(string id)
    {
        var row = Case(id);
        if (row.TryGetProperty("manifest_base64", out var encoded)) return Convert.FromBase64String(encoded.GetString()!);
        var recipe = row.GetProperty("recipe");
        var index = Index(recipe.Text("base_case"));
        index["header"]!["package_note"] = new string(recipe.Text("value")[0], recipe.GetProperty("repeat").GetInt32());
        return Encode(index);
    }
    internal static JsonObject Index(string id = "data-valid") => JsonNode.Parse(Case(id).GetProperty("expected_index").GetRawText())!.AsObject();
    internal static byte[] Payload(string name) => Convert.FromBase64String(Case("data-valid").GetProperty("payloads").EnumerateArray().Single(x => x.Text("name") == name).Text("base64"));
    internal static OfficialVersionSnapshot Snapshot(string dataVersion = "1.3.21") => OfficialVersionSnapshot.Parse(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new
    {
        schema_version = 1, origin = "official_pc_version_endpoint", data_ver = dataVersion, exe_version = "1.3.0",
        packages = new { DataPackage = Case("data-valid").Text("package_version"), MainPackage = Case("main-valid").Text("package_version") },
        checked_at_utc = "2026-01-02T03:04:05Z", assets_ready = false
    })));
    internal static byte[] Encode(JsonObject index)
    {
        using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true);
        void Text(JsonNode? node) { byte[] bytes = Encoding.UTF8.GetBytes(node!.GetValue<string>()); writer.Write(checked((ushort)bytes.Length)); writer.Write(bytes); }
        void Strings(JsonNode? node) { var list = node!.AsArray(); writer.Write(checked((ushort)list.Count)); foreach (var text in list) Text(text); }
        var header = index["header"]!;
        writer.Write(0x00594f4fU); Text(header["file_version"]);
        foreach (string key in new[] { "enable_addressable", "location_to_lower", "include_asset_guid" }) writer.Write(header[key]!.GetValue<bool>());
        writer.Write(header["output_name_style"]!.GetValue<int>()); writer.Write(header["build_bundle_type"]!.GetValue<int>());
        foreach (string key in new[] { "build_pipeline", "package_name", "package_version", "package_note" }) Text(header[key]);
        writer.Write(index["assets"]!.AsArray().Count);
        foreach (var row in index["assets"]!.AsArray())
        { Text(row!["address"]); Text(row["path"]); Text(row["guid"]); Strings(row["tags"]); writer.Write(row["bundle_id"]!.GetValue<int>()); }
        writer.Write(index["bundles"]!.AsArray().Count);
        foreach (var row in index["bundles"]!.AsArray())
        {
            Text(row!["name"]); writer.Write(row["unity_crc"]!.GetValue<uint>()); Text(row["file_hash"]); Text(row["file_crc"]);
            writer.Write(row["file_size"]!.GetValue<long>()); writer.Write(row["encrypted"]!.GetValue<bool>()); Strings(row["tags"]);
            var ids = row["dependency_ids"]!.AsArray(); writer.Write(checked((ushort)ids.Count)); foreach (var id in ids) writer.Write(id!.GetValue<int>());
        }
        writer.Flush(); return stream.ToArray();
    }
}
