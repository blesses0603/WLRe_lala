using System.Collections;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeDatabaseStructuralMatcherTests
{
    [Theory]
    [MemberData(nameof(DatabaseMatchPythonVectors.Cases), MemberType = typeof(DatabaseMatchPythonVectors))]
    public void Retained_actual_python_outcome_and_resource_check_order_match(string id)
    {
        var fixture = DatabaseMatchPythonVectors.Case(id);
        var active = Active(fixture);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, Rows(fixture, active?.VersionId));
        var result = RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), Digests(fixture));
        var expected = fixture.GetProperty("expected");
        Assert.Equal(expected.GetProperty("matches").GetBoolean(), result.MatchesSuppliedRuntime);
        string[] examined = expected.GetProperty("queries").EnumerateArray()
            .Where(query => query.GetProperty("sql").GetString()!.StartsWith("SELECT sha256,data", StringComparison.Ordinal))
            .Select(query => query.GetProperty("parameters")[1].GetString()![..^6]).ToArray();
        Assert.Equal(examined, result.ExaminedSources);
        AssertNonAuthorizing(result);
    }

    [Fact]
    public void Existing_manifest_key_and_exact_ascii_json_remain_source_derived()
    {
        var identity = Identity();
        var inputs = DatabaseMatchPythonVectors.Root.GetProperty("identity_inputs");
        Assert.Equal(inputs.GetProperty("key").GetString(), identity.Key);
        Assert.Equal(inputs.GetProperty("canonical_json").GetString(), identity.CanonicalJson);
        Assert.Equal(identity.Key, Sha(Encoding.ASCII.GetBytes(identity.CanonicalJson)));
        Assert.All(identity.CanonicalJson, c => Assert.InRange((int)c, 0, 127));
        Assert.Equal(BundleSourcePlan.RequiredTables,
            DatabaseMatchPythonVectors.Root.GetProperty("required_tables").EnumerateArray().Select(x => x.GetString()));
    }

    [Fact]
    public void Metadata_catalog_key_is_not_manifest_content_identity()
    {
        var identity = Identity();
        var input = DatabaseMatchPythonVectors.Root.GetProperty("identity_inputs").GetProperty("snapshot");
        var observation = OfficialCatalogObservation.Parse(JsonSerializer.SerializeToUtf8Bytes(new
        {
            resource_path = input.GetProperty("data_ver").GetString(),
            official_exe_version = input.GetProperty("exe_version").GetString(), newer_official_client = false,
            packages = input.GetProperty("packages").EnumerateObject().ToDictionary(p => p.Name, p => new { remote = p.Value.GetString() })
        }));
        Assert.NotEqual(identity.Key, observation.CatalogKey);
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match");
        var active = Active(fixture)! with { CatalogKey = observation.CatalogKey };
        var result = RuntimeDatabaseStructuralMatcher.Match(OwnedRuntimeDatabaseSnapshot.Capture(active, Rows(fixture, active.VersionId)), identity, Digests(fixture));
        Assert.False(result.MatchesSuppliedRuntime); Assert.Empty(result.ExaminedSources);
    }

    [Fact]
    public void Snapshot_owns_exact_slices_and_detaches_rows_map_active_record_and_expected_results()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match");
        var active = Active(fixture)!;
        var rows = Rows(fixture, active.VersionId);
        var digests = Digests(fixture)!;
        var backing = new List<byte[]>();
        foreach (string name in rows.Keys.ToArray())
        {
            var row = rows[name]!; byte[] original = row.Data!.Value.ToArray();
            byte[] envelope = new byte[original.Length + 11]; Array.Fill(envelope, (byte)0xff);
            original.CopyTo(envelope, 7); backing.Add(envelope);
            rows[name] = row with { Data = envelope.AsMemory(7, original.Length) };
        }
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, rows);
        var identity = Identity();
        var first = RuntimeDatabaseStructuralMatcher.Match(snapshot, identity, digests);
        Assert.True(first.MatchesSuppliedRuntime);
        foreach (byte[] bytes in backing) Array.Fill(bytes, (byte)0);
        rows.Clear(); active = active with { VersionId = 900, CatalogKey = "stale", IdentityJson = "[]" };
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(snapshot, identity, digests).MatchesSuppliedRuntime);
        Assert.NotEqual(active.VersionId, snapshot.Active!.VersionId);
        digests["NpcCareerData_C"] = new string('0', 64);
        var changed = RuntimeDatabaseStructuralMatcher.Match(snapshot, identity, digests);
        Assert.False(changed.MatchesSuppliedRuntime); Assert.Equal(10, changed.ExaminedSources.Length);
        Assert.True(first.MatchesSuppliedRuntime); Assert.Equal(10, first.ExaminedSources.Length);
        Assert.Throws<NotSupportedException>(() => ((IList<string>)first.ExaminedSources)[0] = "mutated");
        AssertNonAuthorizing(first);
    }

    [Fact]
    public void Matching_recorded_hashes_do_not_hide_tampered_owned_bytes()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match");
        var active = Active(fixture)!; var rows = Rows(fixture, active.VersionId);
        var row = rows["NpcCareerData_C.bytes"]!;
        byte[] corrupted = row.Data!.Value.ToArray(); corrupted[^1] ^= 0xff;
        rows["NpcCareerData_C.bytes"] = row with { Data = corrupted };
        var result = RuntimeDatabaseStructuralMatcher.Match(OwnedRuntimeDatabaseSnapshot.Capture(active, rows), Identity(), Digests(fixture));
        Assert.False(result.MatchesSuppliedRuntime); Assert.Equal(BundleSourcePlan.RequiredTables, result.ExaminedSources);
        AssertNonAuthorizing(result);
    }

    [Fact]
    public void Case_insensitive_lookup_cannot_promote_an_inexact_resource_name()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var rows = new Dictionary<string, RuntimeDatabaseTableInput?>(Rows(fixture, active.VersionId), StringComparer.OrdinalIgnoreCase);
        var row = rows["Eve.bytes"]!; rows.Remove("Eve.bytes");
        rows.Add("eve.bytes", row with { Name = "eve.bytes" });
        var result = RuntimeDatabaseStructuralMatcher.Match(OwnedRuntimeDatabaseSnapshot.Capture(active, rows), Identity(), Digests(fixture));
        Assert.False(result.MatchesSuppliedRuntime); Assert.Equal(new[] { "Eve" }, result.ExaminedSources);
    }

    [Fact]
    public void Optional_rows_are_not_enumerated_or_retained_and_stale_versions_are_not_copied()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var rows = Rows(fixture, active.VersionId);
        rows.Add("SkillData_C.bytes", new(active.VersionId, "SkillData_C.bytes", "unused", new byte[1024]));
        var lookup = new LookupOnlyRows(rows);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, lookup);
        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes"), lookup.Lookups);
        Assert.Null(snapshot.Table(active.VersionId, "SkillData_C.bytes"));
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), Digests(fixture)).MatchesSuppliedRuntime);
        rows["Eve.bytes"] = rows["Eve.bytes"]! with { VersionId = active.VersionId - 1 };
        snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, rows);
        Assert.Null(snapshot.Table(active.VersionId - 1, "Eve.bytes"));
    }

    [Fact]
    public void Oversized_values_are_rejected_without_retaining_or_copying_their_backing_data()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var rows = Rows(fixture, active.VersionId);
        rows["Eve.bytes"] = rows["Eve.bytes"]! with { Data = new byte[OwnedRuntimeDatabaseSnapshot.MaximumTableBytes + 1], RecordedSha256 = new string('x', 100000) };
        long before = GC.GetAllocatedBytesForCurrentThread();
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, rows);
        long allocated = GC.GetAllocatedBytesForCurrentThread() - before;
        Assert.InRange(allocated, 0, 1024 * 1024);
        var table = snapshot.Table(active.VersionId, "Eve.bytes")!;
        Assert.True(table.HasBlob); Assert.Equal(OwnedRuntimeDatabaseSnapshot.MaximumTableBytes + 1, table.ByteLength);
        Assert.True(table.Bytes.IsEmpty); Assert.Null(table.RecordedSha256);
        Assert.False(RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), Digests(fixture)).MatchesSuppliedRuntime);
        snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active with { IdentityJson = new string(' ', 100000), CatalogKey = new string('a', 100000) }, null);
        Assert.Null(snapshot.Active!.IdentityJson); Assert.Null(snapshot.Active.CatalogKey);
        Assert.Equal(10L * 16 * 1024 * 1024, OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes);
    }

    [Fact]
    public void Cancelled_capture_or_match_cannot_return_a_partial_result()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var rows = Rows(fixture, active.VersionId); using var cts = new CancellationTokenSource(); cts.Cancel();
        Assert.Throws<OperationCanceledException>(() => OwnedRuntimeDatabaseSnapshot.Capture(active, rows, cts.Token));
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, rows);
        Assert.Throws<OperationCanceledException>(() => RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), Digests(fixture), cts.Token));
        using var duringCapture = new CancellationTokenSource();
        var lookup = new LookupOnlyRows(rows, name => { if (name == "NpcCareerData_C.bytes") duringCapture.Cancel(); });
        OwnedRuntimeDatabaseSnapshot? captured = null;
        Assert.Throws<OperationCanceledException>(() => captured = OwnedRuntimeDatabaseSnapshot.Capture(active, lookup, duringCapture.Token));
        Assert.Null(captured); Assert.Equal(10, lookup.Lookups.Count);
        using var duringExpectedCopy = new CancellationTokenSource();
        var digests = new CountingDigests(Digests(fixture)!.ToArray(), () => duringExpectedCopy.Cancel());
        RuntimeDatabaseStructuralMatch? matched = null;
        Assert.Throws<OperationCanceledException>(() => matched = RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), digests, duringExpectedCopy.Token));
        Assert.Null(matched);
    }

    [Fact]
    public void A_hostile_expected_map_cannot_exceed_the_ten_entry_copy_budget()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, Rows(fixture, active.VersionId));
        var entries = Digests(fixture)!.ToArray().Concat(Enumerable.Range(0, 1000).Select(i => new KeyValuePair<string, string?>("extra" + i, "bogus")));
        var map = new CountingDigests(entries);
        var result = RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), map);
        Assert.False(result.MatchesSuppliedRuntime); Assert.Empty(result.ExaminedSources); Assert.Equal(11, map.Enumerated);
    }

    [Fact]
    public void Oversized_or_null_expected_names_are_rejected_before_table_matching()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, Rows(fixture, active.VersionId));
        foreach (string? invalid in new[] { new string('x', 1000000), null })
        {
            var entries = Digests(fixture)!.ToArray(); entries[0] = new(invalid!, entries[0].Value);
            var result = RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), new CountingDigests(entries));
            Assert.False(result.MatchesSuppliedRuntime); Assert.Empty(result.ExaminedSources);
        }
    }

    [Fact]
    public void Missing_typed_inputs_remain_non_authorizing_and_do_not_examine_tables()
    {
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = Active(fixture)!;
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, Rows(fixture, active.VersionId));
        foreach (var result in new[] {
            RuntimeDatabaseStructuralMatcher.Match(null, Identity(), Digests(fixture)),
            RuntimeDatabaseStructuralMatcher.Match(snapshot, null, Digests(fixture)),
            RuntimeDatabaseStructuralMatcher.Match(snapshot, Identity(), null) })
        { Assert.False(result.MatchesSuppliedRuntime); Assert.Empty(result.ExaminedSources); AssertNonAuthorizing(result); }
        Assert.False(typeof(RuntimeDatabaseStructuralMatcher).IsPublic);
        Assert.False(typeof(OwnedRuntimeDatabaseSnapshot).IsPublic);
        Assert.False(typeof(RuntimeDatabaseStructuralMatch).IsPublic);
    }

    [Fact]
    public void Retained_python_sources_use_crlf_only_hash_normalization()
    {
        string root = RepositoryRoot();
        foreach (var source in DatabaseMatchPythonVectors.Root.GetProperty("source_sha256").EnumerateObject())
        {
            byte[] raw = File.ReadAllBytes(Path.Combine(root, source.Name));
            using var normalized = new MemoryStream(raw.Length);
            for (int i = 0; i < raw.Length; i++)
            { if (raw[i] == 13 && i + 1 < raw.Length && raw[i + 1] == 10) continue; normalized.WriteByte(raw[i]); }
            Assert.Equal(source.Value.GetString(), Sha(normalized.ToArray()));
        }
    }

    private static void AssertNonAuthorizing(RuntimeDatabaseStructuralMatch result)
    {
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.ProvesDatabaseTransaction);
        Assert.False(result.RuntimeAdmitted); Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
    }
    private static string Sha(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    private static string? Text(JsonElement element) => element.ValueKind == JsonValueKind.Null ? null : element.GetString();
    private static RuntimeDatabaseActiveInput? Active(JsonElement fixture)
    {
        var active = fixture.GetProperty("active");
        return active.ValueKind == JsonValueKind.Null ? null : new(active[0].GetInt64(), Text(active[1]), Text(active[2]));
    }
    private static Dictionary<string, string?>? Digests(JsonElement fixture)
    {
        var value = fixture.GetProperty("expected_digests");
        return value.ValueKind == JsonValueKind.Null ? null : value.EnumerateArray().ToDictionary(row => row.GetProperty("name").GetString()!, row => Text(row.GetProperty("sha256")), StringComparer.Ordinal);
    }
    private static Dictionary<string, RuntimeDatabaseTableInput?> Rows(JsonElement fixture, long? active)
    {
        var result = new Dictionary<string, RuntimeDatabaseTableInput?>(StringComparer.Ordinal);
        foreach (var row in fixture.GetProperty("rows").EnumerateArray())
        {
            string name = row.GetProperty("name").GetString()!;
            long version = row.GetProperty("active_id").GetInt64();
            // The source SELECT has a (version_id, name) key. An extra stale-version row must
            // never overwrite an active row when adapting fixtures to the supplied projection.
            if (result.TryGetValue(name, out var prior) && prior?.VersionId == active) continue;
            result[name] = new(version, name, Text(row.GetProperty("sha256")), Payload(row.GetProperty("data")));
        }
        return result;
    }
    private static ReadOnlyMemory<byte>? Payload(JsonElement payload)
    {
        if (payload.ValueKind == JsonValueKind.Null) return null;
        byte[] bytes;
        if (payload.GetProperty("kind").GetString() == "base64") bytes = Convert.FromBase64String(payload.GetProperty("value").GetString()!);
        else { bytes = new byte[payload.GetProperty("length").GetInt32()]; Array.Fill(bytes, payload.GetProperty("byte").GetByte()); }
        Assert.Equal(payload.GetProperty("size").GetInt32(), bytes.Length);
        Assert.Equal(payload.GetProperty("sha256").GetString(), Sha(bytes));
        return bytes;
    }
    private static ManifestIdentity Identity()
    {
        var input = DatabaseMatchPythonVectors.Root.GetProperty("identity_inputs");
        var snapshot = OfficialVersionSnapshot.Parse(input.GetProperty("snapshot"));
        var manifests = new Dictionary<string, ManifestIdentityInput>(StringComparer.Ordinal);
        foreach (var row in input.GetProperty("manifests").EnumerateArray())
        {
            string name = row.GetProperty("package").GetString()!, version = row.GetProperty("package_version").GetString()!;
            byte[] bytes = Convert.FromBase64String(row.GetProperty("bytes_base64").GetString()!);
            Assert.Equal(row.GetProperty("sha256").GetString(), Sha(bytes));
            manifests.Add(name, new(snapshot.DataVersion, name, version, name, version, "2.2.5", row.GetProperty("crc32_le").GetString()!, bytes));
        }
        return ManifestIdentity.Derive(snapshot, manifests);
    }
    private static string RepositoryRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "wlre/services/world/resource_database.py"))) return directory.FullName;
        throw new InvalidOperationException("Retained source checkout unavailable.");
    }
    private sealed class LookupOnlyRows(Dictionary<string, RuntimeDatabaseTableInput?> rows, Action<string>? lookup = null)
        : IReadOnlyDictionary<string, RuntimeDatabaseTableInput?>
    {
        internal readonly List<string> Lookups = [];
        public bool TryGetValue(string key, out RuntimeDatabaseTableInput? value) { Lookups.Add(key); lookup?.Invoke(key); return rows.TryGetValue(key, out value); }
        public int Count => throw new InvalidOperationException("Unneeded row count.");
        public IEnumerable<string> Keys => throw new InvalidOperationException("Unbounded row enumeration.");
        public IEnumerable<RuntimeDatabaseTableInput?> Values => throw new InvalidOperationException("Unbounded row enumeration.");
        public RuntimeDatabaseTableInput? this[string key] => throw new InvalidOperationException("Unneeded lookup.");
        public bool ContainsKey(string key) => throw new InvalidOperationException("Unneeded lookup.");
        public IEnumerator<KeyValuePair<string, RuntimeDatabaseTableInput?>> GetEnumerator() => throw new InvalidOperationException("Unbounded row enumeration.");
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
    private sealed class CountingDigests(IEnumerable<KeyValuePair<string, string?>> entries, Action? enumerate = null) : IReadOnlyDictionary<string, string?>
    {
        internal int Enumerated;
        public int Count => 10;
        public IEnumerator<KeyValuePair<string, string?>> GetEnumerator()
        { foreach (var pair in entries) { Enumerated++; enumerate?.Invoke(); yield return pair; } }
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
        public IEnumerable<string> Keys => throw new InvalidOperationException();
        public IEnumerable<string?> Values => throw new InvalidOperationException();
        public string? this[string key] => throw new InvalidOperationException();
        public bool ContainsKey(string key) => throw new InvalidOperationException();
        public bool TryGetValue(string key, out string? value) => throw new InvalidOperationException();
    }
}
