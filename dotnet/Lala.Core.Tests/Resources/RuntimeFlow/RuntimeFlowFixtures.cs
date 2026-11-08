using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;

namespace Lala.Core.Tests.Resources;

internal static class RuntimeFlowFixtures
{
    private static readonly Lazy<JsonElement> Evidence = new(() => JsonDocument.Parse(Read("evidence.json")).RootElement);
    internal const string Version = "1286_2026_10_29_13_42_37_94";
    internal const string AssetRoot = "Assets/ResourcesBuild/Data/";
    internal static byte[] Read(string name)
    {
        using var stream = typeof(RuntimeFlowFixtures).Assembly.GetManifestResourceStream(
            "Lala.Core.Tests.Resources.RuntimeFlow.Fixtures." + name) ?? throw new InvalidDataException("Missing owned fixture");
        using var output = new MemoryStream(); stream.CopyTo(output); byte[] bytes = output.ToArray();
        if (name != "evidence.json")
        {
            var evidence = Evidence.Value.GetProperty("files").GetProperty(name);
            if (bytes.Length != evidence.GetProperty("bytes").GetInt32() ||
                Convert.ToHexStringLower(SHA256.HashData(bytes)) != evidence.GetProperty("sha256").GetString())
                throw new InvalidDataException("Owned runtime fixture hash differs");
        }
        return bytes;
    }
    internal static byte[] Manifest(IReadOnlyDictionary<string, byte[]> bundles,
        IReadOnlyDictionary<string, string>? roots = null, IReadOnlyDictionary<string, string[]>? dependencies = null,
        string version = Version, bool includeSkill = false, bool includeDaily = false,
        IReadOnlySet<string>? omittedTables = null, bool includeInstances = false)
    {
        var index = BundleSourceFixtures.Index();
        index["header"]!["package_version"] = version;
        string[] names = bundles.Keys.ToArray();
        var ids = names.Select((name, id) => (name, id)).ToDictionary(pair => pair.name, pair => pair.id, StringComparer.Ordinal);
        var assets = new JsonArray(); var rows = new JsonArray();
        IEnumerable<string> tables = BundleSourcePlan.RequiredTables;
        if (includeSkill) tables = tables.Append("SkillData_C");
        if (includeDaily) tables = tables.Concat(new[] { "DailyTaskData_C", "DailyTaskRewardData_C" });
        if (includeInstances) tables = tables.Concat(new[] { "DungeonData_C", "CooperateEventData_C" });
        foreach (string name in tables)
        {
            if (omittedTables?.Contains(name) == true) continue;
            string path = AssetRoot + name + ".bytes";
            assets.Add(new JsonObject { ["address"] = "", ["path"] = path, ["guid"] = "", ["tags"] = new JsonArray(),
                ["bundle_id"] = ids[roots?.GetValueOrDefault(name) ?? names[0]] });
        }
        foreach (string name in names)
        {
            byte[] bytes = bundles[name];
            rows.Add(new JsonObject
            {
                ["name"] = name, ["unity_crc"] = 0u, ["file_hash"] = Convert.ToHexStringLower(MD5.HashData(bytes)),
                ["file_crc"] = ManifestIdentity.Crc32LittleEndian(bytes), ["file_size"] = (long)bytes.Length,
                ["encrypted"] = false, ["tags"] = new JsonArray(),
                ["dependency_ids"] = new JsonArray((dependencies?.GetValueOrDefault(name) ?? []).Select(dep => JsonValue.Create(ids[dep])).ToArray<JsonNode?>())
            });
        }
        index["assets"] = assets; index["bundles"] = rows;
        return BundleSourceFixtures.Encode(index);
    }
    internal static OfficialVersionSnapshot Snapshot(string dataVersion = "1.3.21", string packageVersion = Version) =>
        OfficialVersionSnapshot.Parse(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new
        {
            schema_version = 1, origin = "official_pc_version_endpoint", data_ver = dataVersion, exe_version = "1.3.0",
            packages = new { DataPackage = packageVersion, MainPackage = BundleSourceFixtures.Case("main-valid").Text("package_version") },
            checked_at_utc = "2026-01-02T03:04:05Z", assets_ready = false
        })));
}
