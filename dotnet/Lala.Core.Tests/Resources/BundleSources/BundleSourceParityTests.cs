using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class BundleSourceParityTests
{
    public static IEnumerable<object[]> Cases() => BundleSourceFixtures.Ids();
    [Theory, MemberData(nameof(Cases))]
    public void ActualPythonBinaryParserAndRequiredPlan(string id)
    {
        Assert.InRange(id.Length, 1, 64);
        var row = BundleSourceFixtures.Case(id); byte[] bytes = BundleSourceFixtures.Bytes(id);
        Assert.Equal(row.GetProperty("manifest_size").GetInt32(), bytes.Length);
        Assert.Equal(row.Text("manifest_sha256"), Convert.ToHexStringLower(SHA256.HashData(bytes)));
        Assert.Equal(row.Text("manifest_crc32_le"), ManifestIdentity.Crc32LittleEndian(bytes));
        if (!row.GetProperty("parse_ok").GetBoolean())
        { Assert.Throws<BundleSourceException>(() => YooAssetManifest.Parse(bytes)); return; }
        var parsed = YooAssetManifest.Parse(bytes);
        var actual = JsonSerializer.SerializeToNode(new
        {
            header = new { file_version = parsed.Header.FileVersion, enable_addressable = parsed.Header.EnableAddressable,
                location_to_lower = parsed.Header.LocationToLower, include_asset_guid = parsed.Header.IncludeAssetGuid,
                output_name_style = parsed.Header.OutputNameStyle, build_bundle_type = parsed.Header.BuildBundleType,
                build_pipeline = parsed.Header.BuildPipeline, package_name = parsed.Header.PackageName,
                package_version = parsed.Header.PackageVersion, package_note = parsed.Header.PackageNote },
            asset_count = parsed.Assets.Count, bundle_count = parsed.Bundles.Count,
            assets = parsed.Assets.Select(a => new { address = a.Address, path = a.Path, guid = a.Guid, tags = a.Tags,
                bundle_id = a.BundleId, bundle_name = parsed.Bundles[a.BundleId].Name }),
            bundles = parsed.Bundles.Select(b => new { name = b.Name, unity_crc = b.UnityCrc, file_hash = b.FileHash,
                file_crc = b.FileCrc, file_size = b.FileSize, encrypted = b.Encrypted, tags = b.Tags,
                dependency_ids = b.DependencyIds, dependencies = b.DependencyIds.Select(dep => parsed.Bundles[dep].Name) })
        });
        var expected = BundleSourceFixtures.Index(id);
        if (id == "note-utf8-max") expected["header"]!["package_note"] = new string('x', 65535);
        Assert.True(JsonNode.DeepEquals(expected, actual), id);
        Assert.Equal(row.Text("manifest_sha256"), parsed.Sha256);
        Assert.Equal(row.Text("manifest_crc32_le"), parsed.Crc32Le);
        if (parsed.Header.PackageName != "DataPackage")
        { Assert.Throws<BundleSourceException>(() => BundleSourcePlan.Create(parsed, row.Text("data_ver"))); return; }
        var expectedPlan = row.GetProperty("plan");
        if (!expectedPlan.GetProperty("success").GetBoolean())
        { Assert.Equal(BundleSourceFailure.MissingRequiredAsset, Assert.Throws<BundleSourceException>(() => BundleSourcePlan.Create(parsed, row.Text("data_ver"))).Failure); return; }
        var plan = BundleSourcePlan.Create(parsed, row.Text("data_ver"));
        Assert.Equal(expectedPlan.GetProperty("ordered_names").EnumerateArray().Select(x => x.GetString()), plan.Entries.Select(x => x.Spec.Name));
        Assert.Equal(expectedPlan.GetProperty("download_bytes").GetInt64(), plan.Entries.Sum(x => x.Spec.Size));
        Assert.Equal(0, plan.AddedCount); Assert.Equal(0, plan.ModifiedCount); Assert.Equal(0, plan.RemovedCount);
        foreach (var entry in plan.Entries)
        {
            var planned = expectedPlan.GetProperty("entries").EnumerateArray().Single(x => x.Text("name") == entry.Spec.Name);
            Assert.Equal(planned.GetProperty("dependencies").EnumerateArray().Select(x => x.GetString()), entry.Dependencies);
            Assert.Equal(BundleChange.FirstBaseline, entry.Change);
        }
        foreach (var payload in row.GetProperty("payloads").EnumerateArray())
        {
            var spec = new BundleSourceSpec(row.Text("data_ver"), parsed, parsed.Bundles.Single(x => x.Name == payload.Text("name")));
            byte[] body = Convert.FromBase64String(payload.Text("base64"));
            var handle = VerifiedBundleSource.Verify(spec, body, BundleAcquisition.UntrustedSourceDownload);
            Assert.Equal(payload.Text("sha256"), handle.Sha256); Assert.Equal(payload.Text("md5"), spec.Md5); Assert.Equal(payload.Text("crc32_le"), spec.Crc32Le);
            body[0] ^= 1;
            Assert.Equal(BundleSourceFailure.Checksum, Assert.Throws<BundleSourceException>(() => VerifiedBundleSource.Verify(spec, body, BundleAcquisition.UntrustedSourceDownload)).Failure);
        }
    }
}
