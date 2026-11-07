using System.Collections;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class ResourceValidationTests
{
    private const string Data = "1275_2026_10_21_18_27_33_84";
    private const string Main = "1275_2026_10_21_18_29_38_49";
    private static readonly string[] Features = ["npc", "shops", "crafting", "scenes", "items"];
    private static byte[] Json(object? value) => JsonSerializer.SerializeToUtf8Bytes(value);
    private static string Text(JsonElement value, string name) => value.GetProperty(name).GetString()!;
    private static Dictionary<string, string> Versions(JsonElement value) => value.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!, StringComparer.Ordinal);
    private static OfficialVersionSnapshot Snapshot(string data = "1.3.21", string exe = "1.3.0", string main = Main, string checkedAt = "test") =>
        OfficialVersionSnapshot.Parse(Json(new { schema_version = 1, origin = "official_pc_version_endpoint", data_ver = data, exe_version = exe,
            packages = new { DataPackage = Data, MainPackage = main }, checked_at_utc = checkedAt, assets_ready = false }));
    private static byte[] ObservationBytes(string main = Main) => Json(new { resource_path = "1.3.21", official_exe_version = "1.3.0", newer_official_client = false,
        packages = new { DataPackage = new { remote = Data }, MainPackage = new { remote = main } } });
    private static JsonObject Metadata(string? key = null)
    {
        var sources = new JsonObject();
        foreach (string feature in Features)
            sources[feature] = new JsonObject { ["source_name"] = feature + "-source", ["schema_id"] = "display-only", ["sha256"] = new string('a', 64), ["record_count"] = 1 };
        return new JsonObject { ["catalog_key"] = key ?? OfficialCatalogObservation.Parse(ObservationBytes()).CatalogKey, ["sources"] = sources };
    }
    private static Dictionary<string, ManifestIdentityInput> ManifestInputs()
    {
        var result = new Dictionary<string, ManifestIdentityInput>();
        foreach ((string name, string version) in new[] { ("DataPackage", Data), ("MainPackage", Main) })
        {
            byte[] bytes = Encoding.ASCII.GetBytes("synthetic manifest " + name);
            result[name] = new("1.3.21", name, version, name, version, "2.2.5", ManifestIdentity.Crc32LittleEndian(bytes), bytes);
        }
        return result;
    }
    private static Dictionary<string, ManifestIdentityInput> ManifestInputs(JsonElement manifests)
    {
        var result = new Dictionary<string, ManifestIdentityInput>();
        foreach (var property in manifests.EnumerateObject())
        {
            var row = property.Value; var header = row.GetProperty("header");
            result[property.Name] = new(Text(row, "data_ver"), Text(row, "package"), Text(row, "package_version"),
                Text(header, "package_name"), Text(header, "package_version"), Text(header, "file_version"), Text(row, "crc"), Convert.FromBase64String(Text(row, "bytes")));
        }
        return result;
    }

    [Theory]
    [MemberData(nameof(PythonResourceVectors.Cases), MemberType = typeof(PythonResourceVectors))]
    public void RetainedPythonParity(string kind, string name, string bodyBase64, string? expectedJson)
    {
        Assert.NotEmpty(name);
        byte[] body = Convert.FromBase64String(bodyBase64);
        if (expectedJson is null)
        {
            Assert.Throws<ResourceValidationException>(() => Evaluate(kind, body));
            return;
        }
        object actual = Evaluate(kind, body);
        var expected = JsonNode.Parse(expectedJson)!;
        if (kind == "snapshot-compare") expected.AsObject().Remove("note"); // localized display text is not a policy field
        Assert.True(JsonNode.DeepEquals(expected, JsonNode.Parse(JsonSerializer.Serialize(actual))),
            $"Python parity mismatch: {kind}/{name}\nExpected {expected}\nActual {JsonSerializer.Serialize(actual)}");
    }

    private static object Evaluate(string kind, byte[] body)
    {
        if (kind == "baseline")
        {
            var result = ResourceCompatibility.ParseBaseline(body);
            return new { exe = result.OfficialGameExeVersion, label = result.Label,
                revisions = result.Packages.ToDictionary(p => p.Key, p => p.Value.Revision), manifests = result.Packages.ToDictionary(p => p.Key, p => p.Value.Manifest) };
        }
        if (kind == "snapshot")
        {
            var result = OfficialVersionSnapshot.Parse(body);
            return new { data = result.DataVersion, exe = result.ExeVersion, packages = result.Packages, @checked = result.CheckedAtUtc, assets_ready = result.AssetsReady };
        }
        if (kind == "observation")
        {
            var result = OfficialCatalogObservation.Parse(body);
            var decision = OfficialCatalogObservation.Select(body);
            return new { key = result.CatalogKey, packages = result.Packages, decision = new { catalog_key = decision.CatalogKey, status = decision.Status,
                reason = decision.Reason, verified_features = decision.VerifiedFeatures, assets_ready = decision.AssetsReady, can_send_packets = decision.CanSendPackets } };
        }
        using var doc = JsonDocument.Parse(body);
        JsonElement root = doc.RootElement;
        if (kind == "snapshot-compare")
        {
            var prior = root.GetProperty("previous");
            var result = OfficialVersionSnapshot.Parse(root.GetProperty("current")).Compare(prior.ValueKind == JsonValueKind.Null ? null : OfficialVersionSnapshot.Parse(prior));
            return new { data_ver_changed = result.DataVersionChanged, exe_version_changed = result.ExeVersionChanged, package_changes = result.PackageChanges,
                resource_installation = result.ResourceInstallation, can_start_asset_dependent_features = result.CanStartAssetDependentFeatures };
        }
        if (kind == "compatibility")
        {
            var result = ResourceCompatibility.Shipped.Compare(root.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()));
            return new { status = result.Status, comparisons = result.Packages.ToDictionary(p => p.Key, p => p.Value.Comparison) };
        }
        if (kind == "metadata")
        {
            var result = CatalogMetadataView.Inspect(OfficialCatalogObservation.Parse(ObservationBytes()), body);
            return new { key = result.CatalogKey, counts = result.Sources.ToDictionary(p => p.Key, p => p.Value.RecordCount),
                digests = result.Sources.ToDictionary(p => p.Key, p => p.Value.Sha256), assets_ready = result.AssetsReady, can_send_packets = result.CanSendPackets };
        }
        if (kind == "manifest")
        {
            var result = ManifestIdentity.Derive(OfficialVersionSnapshot.Parse(root.GetProperty("snapshot")), ManifestInputs(root.GetProperty("manifests")));
            return new { key = result.Key, identity = new { schema_version = 1, data_ver = result.DataVersion, exe_version = result.ExeVersion,
                packages = result.Packages.Select(p => new { name = p.Name, full_version = p.FullVersion, manifest_sha256 = p.ManifestSha256, manifest_crc32_le = p.ManifestCrc32Le }).ToArray() } };
        }
        if (kind == "origin") return new { host = root.TryGetProperty("WLRE_OFFICIAL_RESOURCE_HOST", out var host) ? OfficialResourceOrigin.SelectHost(host.GetString()!) : OfficialResourceOrigin.SelectHost() };
        throw new InvalidOperationException("Unknown parity case");
    }

    [Fact]
    public void ShippedBaselineCannotBeReplacedThroughPublicApi()
    {
        Assert.Empty(typeof(ResourceCompatibility).GetConstructors());
        Assert.Null(typeof(ResourceCompatibility).GetMethod("ParseBaseline"));
        Assert.Null(typeof(ResourceCompatibility).GetProperty("Shipped")!.SetMethod);
        Assert.Equal("1275", ResourceCompatibility.Shipped.Label);
        Assert.Equal("1.3.0", ResourceCompatibility.Shipped.OfficialGameExeVersion);
    }

    [Fact]
    public void ResultsOwnImmutableCollections()
    {
        var baseline = ResourceCompatibility.Shipped;
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, PackageBaseline>)baseline.Packages).Clear());
        var snapshot = Snapshot();
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, string>)snapshot.Packages).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, string>)snapshot.Compare().PackageChanges).Clear());
        var observation = OfficialCatalogObservation.Parse(ObservationBytes());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, string>)observation.Packages).Clear());
        var metadata = CatalogMetadataView.Inspect(observation, Json(Metadata()));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, CatalogSourceMetadata>)metadata.Sources).Clear());
        var inputs = ManifestInputs();
        var identity = ManifestIdentity.Derive(snapshot, inputs);
        string original = identity.Key;
        Assert.Throws<NotSupportedException>(() => ((IList<ManifestPackageIdentity>)identity.Packages).Clear());
        inputs["DataPackage"].Bytes[0] ^= 1;
        Assert.Equal(original, identity.Key);
        Assert.Throws<ResourceValidationException>(() => ManifestIdentity.Derive(snapshot, inputs));
    }

    [Fact]
    public void ParsingDoesNotRetainCallerBytesOrJsonDocument()
    {
        byte[] bytes = ObservationBytes();
        var result = OfficialCatalogObservation.Parse(bytes);
        string key = result.CatalogKey;
        Array.Fill(bytes, (byte)'!');
        Assert.Equal(key, result.CatalogKey);
        Assert.Equal(Main, result.Packages["MainPackage"]);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("null")]
    [InlineData("[]")]
    [InlineData("{")]
    public void MissingIdentityAlwaysSelectsBlocked(string raw)
    {
        var result = OfficialCatalogObservation.Select(Encoding.UTF8.GetBytes(raw));
        Assert.Equal("blocked", result.Status); Assert.Equal("invalid_official_identity", result.Reason);
        Assert.Null(result.CatalogKey); Assert.Empty(result.VerifiedFeatures);
        Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
    }

    [Fact]
    public void SelectionRequiresTheExactIndependentPairAndNeverAuthorizes()
    {
        var versions = new Dictionary<string, string> { ["DataPackage"] = Data, ["MainPackage"] = Main };
        Assert.Equal("verification_required", OfficialCatalogObservation.Select(ObservationBytes(), versions).Status);
        foreach (var wrong in new[] { new Dictionary<string, string>(), new Dictionary<string, string> { ["DataPackage"] = Data },
            new Dictionary<string, string> { ["DataPackage"] = Data, ["MainPackage"] = Data },
            new Dictionary<string, string> { ["DataPackage"] = Data, ["MainPackage"] = Main, ["extra"] = Main } })
        {
            var result = OfficialCatalogObservation.Select(ObservationBytes(), wrong);
            Assert.Equal("official_package_pair_mismatch", result.Reason); Assert.Null(result.CatalogKey);
            Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
        }
        var valid = OfficialCatalogObservation.Select(ObservationBytes(), versions);
        Assert.Empty(valid.VerifiedFeatures); Assert.False(valid.AssetsReady); Assert.False(valid.CanSendPackets);
    }

    [Theory]
    [InlineData("npc")]
    [InlineData("shops")]
    [InlineData("crafting")]
    [InlineData("scenes")]
    [InlineData("items")]
    public void EveryFeatureIsMandatoryAndFailureLeavesEarlierViewUnchanged(string feature)
    {
        var observation = OfficialCatalogObservation.Parse(ObservationBytes());
        var input = Metadata(); var previous = CatalogMetadataView.Inspect(observation, Json(input));
        input["sources"]!.AsObject().Remove(feature);
        Assert.Throws<ResourceValidationException>(() => CatalogMetadataView.Inspect(observation, Json(input)));
        Assert.Equal(5, previous.Sources.Count); Assert.Equal(1, previous.Sources[feature].RecordCount);
    }

    [Theory]
    [InlineData("true")]
    [InlineData("1.0")]
    [InlineData("1e0")]
    [InlineData("null")]
    [InlineData("\"1\"")]
    public void MetadataCountMustBeAnIntegerNotACoercibleJsonValue(string json)
    {
        var input = Metadata(); input["sources"]!["npc"]!["record_count"] = JsonNode.Parse(json);
        Assert.Throws<ResourceValidationException>(() => CatalogMetadataView.Inspect(OfficialCatalogObservation.Parse(ObservationBytes()), Json(input)));
    }

    [Fact]
    public void DisplayMetadataCannotElevateAuthorityEvenWithPlausibleDigestAndFlags()
    {
        var input = Metadata(); input["assets_ready"] = true; input["can_send_packets"] = true;
        var result = CatalogMetadataView.Inspect(OfficialCatalogObservation.Parse(ObservationBytes()), Json(input));
        Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
        Assert.Equal(new string('a', 64), result.Sources["npc"].Sha256); // shape validation only, never a payload proof
    }

    [Theory]
    [InlineData("null")]
    [InlineData("{}")]
    [InlineData("[]")]
    [InlineData("{")]
    public void MissingOrMalformedCatalogMetadataFailsClosed(string value) =>
        Assert.Throws<ResourceValidationException>(() => CatalogMetadataView.Inspect(OfficialCatalogObservation.Parse(ObservationBytes()), Encoding.UTF8.GetBytes(value)));

    [Fact]
    public void IdentityChangeIsStaleButTimestampAloneDoesNotInventFreshnessAuthority()
    {
        var before = Snapshot(); var inputs = ManifestInputs(); var identity = ManifestIdentity.Derive(before, inputs);
        var laterTime = Snapshot(checkedAt: "not-an-ISO-date");
        Assert.True(before.HasSameIdentity(laterTime));
        ManifestIdentity.ConfirmStable(before, laterTime, identity, inputs);
        foreach (var after in new[] { Snapshot(data: "1.3.21.1"), Snapshot(exe: "1.4.0"), Snapshot(main: "1275_2026_10_22_18_29_38_49") })
        {
            Assert.False(before.HasSameIdentity(after));
            Assert.Throws<ResourceValidationException>(() => ManifestIdentity.ConfirmStable(before, after, identity, inputs));
        }
    }

    [Fact]
    public void BytesReplacedWithNewMatchingCrcStillCannotReuseTheEarlierIdentity()
    {
        var before = Snapshot(); var inputs = ManifestInputs(); var initial = ManifestIdentity.Derive(before, inputs);
        byte[] replacement = Encoding.ASCII.GetBytes("different synthetic Manifest");
        inputs["MainPackage"] = inputs["MainPackage"] with { Bytes = replacement, OfficialCrc32Le = ManifestIdentity.Crc32LittleEndian(replacement) };
        Assert.NotEqual(initial.Key, ManifestIdentity.Derive(before, inputs).Key);
        Assert.Throws<ResourceValidationException>(() => ManifestIdentity.ConfirmStable(before, before, initial, inputs));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(8388609)]
    public void ManifestPayloadMustBePresentAndBounded(int length)
    {
        var inputs = ManifestInputs(); inputs["DataPackage"] = inputs["DataPackage"] with { Bytes = new byte[length] };
        Assert.Throws<ResourceValidationException>(() => ManifestIdentity.Derive(Snapshot(), inputs));
    }

    [Fact]
    public void UppercaseCrcOrExtraManifestIsNotSilentlyNormalized()
    {
        var inputs = ManifestInputs(); var input = inputs["DataPackage"];
        inputs["DataPackage"] = input with { OfficialCrc32Le = input.OfficialCrc32Le.ToUpperInvariant() };
        Assert.Throws<ResourceValidationException>(() => ManifestIdentity.Derive(Snapshot(), inputs));
        inputs["DataPackage"] = input; inputs["unexpected"] = input;
        Assert.Throws<ResourceValidationException>(() => ManifestIdentity.Derive(Snapshot(), inputs));
    }

    [Theory]
    [InlineData("", "00000000")]
    [InlineData("123456789", "2639f4cb")]
    public void CrcUsesYooAssetLittleEndian(string body, string expected) =>
        Assert.Equal(expected, ManifestIdentity.Crc32LittleEndian(Encoding.ASCII.GetBytes(body)));

    [Fact]
    public void PublicAssemblyExposesNoVerifiedManifestFactoryOrAuthorityBoolean()
    {
        Assert.False(typeof(ManifestIdentity).IsPublic); Assert.False(typeof(ManifestIdentityInput).IsPublic);
        var baseline = ResourceCompatibility.Shipped.Compare(new Dictionary<string, string?> { ["DataPackage"] = Data, ["MainPackage"] = Main });
        Assert.Equal("same_resources", baseline.Status); Assert.Equal("unverified", baseline.ProtocolCompatibility);
        Assert.True(baseline.ReadOnly); Assert.False(baseline.AssetsReady); Assert.False(baseline.CanSendPackets);
    }

    [Fact]
    public void DuplicateJsonPropertiesFollowPythonLastValueSemantics()
    {
        string json = Encoding.UTF8.GetString(ObservationBytes()).Replace("\"newer_official_client\":false", "\"newer_official_client\":1,\"newer_official_client\":false", StringComparison.Ordinal);
        Assert.Equal(OfficialCatalogObservation.Parse(ObservationBytes()).CatalogKey, OfficialCatalogObservation.Parse(Encoding.UTF8.GetBytes(json)).CatalogKey);
    }

    [Fact]
    public void OversizedSnapshotIsRejectedBeforeJsonParsing() =>
        Assert.Throws<ResourceValidationException>(() => OfficialVersionSnapshot.Parse(new byte[OfficialVersionSnapshot.MaximumBytes + 1]));
    [Fact]
    public void PublicMetadataBuffersAcceptTheLimitAndRejectOneMoreByte()
    {
        byte[] observed = ObservationBytes();
        byte[] atLimit = Enumerable.Repeat((byte)' ', OfficialCatalogObservation.MaximumBytes).ToArray();
        observed.CopyTo(atLimit, 0);
        var observation = OfficialCatalogObservation.Parse(atLimit);
        Assert.Equal(OfficialCatalogObservation.Parse(observed).CatalogKey, observation.CatalogKey);
        Assert.Throws<ResourceValidationException>(() => OfficialCatalogObservation.Parse(new byte[atLimit.Length + 1]));
        Assert.Equal("blocked", OfficialCatalogObservation.Select(new byte[atLimit.Length + 1]).Status);
        byte[] metadata = Json(Metadata());
        byte[] metadataLimit = Enumerable.Repeat((byte)' ', CatalogMetadataView.MaximumBytes).ToArray();
        metadata.CopyTo(metadataLimit, 0);
        Assert.Equal(5, CatalogMetadataView.Inspect(observation, metadataLimit).Sources.Count);
        Assert.Throws<ResourceValidationException>(() => CatalogMetadataView.Inspect(observation, new byte[metadataLimit.Length + 1]));
    }

    [Fact]
    public void PreCancelledOperationsProduceNoIdentityOrPartialMetadata()
    {
        using var source = new CancellationTokenSource(); source.Cancel(); var token = source.Token;
        var observation = OfficialCatalogObservation.Parse(ObservationBytes());
        var snapshot = Snapshot(); var inputs = ManifestInputs(); var identity = ManifestIdentity.Derive(snapshot, inputs);
        Assert.Throws<OperationCanceledException>(() => OfficialCatalogObservation.Parse(ObservationBytes(), token));
        Assert.Throws<OperationCanceledException>(() => OfficialCatalogObservation.Select(ObservationBytes(), cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => CatalogMetadataView.Inspect(observation, Json(Metadata()), token));
        Assert.Throws<OperationCanceledException>(() => OfficialVersionSnapshot.Parse(new byte[0], token));
        Assert.Throws<OperationCanceledException>(() => ManifestIdentity.Crc32LittleEndian(new byte[8192], token));
        Assert.Throws<OperationCanceledException>(() => ResourceValidation.Digest(new byte[8192], token));
        Assert.Throws<OperationCanceledException>(() => ManifestIdentity.Derive(snapshot, inputs, token));
        Assert.Throws<OperationCanceledException>(() => ManifestIdentity.ConfirmStable(snapshot, snapshot, identity, inputs, token));
        Assert.Equal(2, identity.Packages.Count);
    }

    [Fact]
    public void CancellationBetweenManifestInputsReturnsNoPartialIdentity()
    {
        using var source = new CancellationTokenSource();
        var inputs = ManifestInputs(); var prior = ManifestIdentity.Derive(Snapshot(), inputs);
        var cancelling = new CancelOnSecondManifest(inputs, source);
        Assert.Throws<OperationCanceledException>(() => ManifestIdentity.Derive(Snapshot(), cancelling, source.Token));
        Assert.Equal(2, prior.Packages.Count);
        Assert.Equal(prior.Key, ManifestIdentity.Derive(Snapshot(), inputs).Key);
    }

    private sealed class CancelOnSecondManifest(Dictionary<string, ManifestIdentityInput> inputs, CancellationTokenSource cancellation)
        : IReadOnlyDictionary<string, ManifestIdentityInput>
    {
        public ManifestIdentityInput this[string key]
        {
            get { if (key == "MainPackage") cancellation.Cancel(); return inputs[key]; }
        }
        public IEnumerable<string> Keys => inputs.Keys;
        public IEnumerable<ManifestIdentityInput> Values => inputs.Values;
        public int Count => inputs.Count;
        public bool ContainsKey(string key) => inputs.ContainsKey(key);
        public bool TryGetValue(string key, out ManifestIdentityInput value) => inputs.TryGetValue(key, out value!);
        public IEnumerator<KeyValuePair<string, ManifestIdentityInput>> GetEnumerator() => inputs.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    [Fact]
    public void InvalidUtf8InIgnoredFieldsCannotEvadeMetadataDecoding()
    {
        byte[] raw = ObservationBytes();
        byte[] invalid = raw[..^1].Concat(Encoding.ASCII.GetBytes(",\"ignored\":\""))
            .Concat(new byte[] { 0xff }).Concat(Encoding.ASCII.GetBytes("\"}")).ToArray();
        Assert.Throws<ResourceValidationException>(() => OfficialCatalogObservation.Parse(invalid));
        Assert.Equal("blocked", OfficialCatalogObservation.Select(invalid).Status);
    }

}
