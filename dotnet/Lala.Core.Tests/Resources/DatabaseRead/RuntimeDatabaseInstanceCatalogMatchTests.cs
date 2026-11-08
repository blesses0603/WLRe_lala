using System.Collections;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeDatabaseInstanceCatalogMatchTests
{
    private const string DungeonTable = "DungeonData_C.bytes";
    private const string CooperativeTable = "CooperateEventData_C.bytes";
    private const string SkillTable = "SkillData_C.bytes";
    private const string DailyTaskTable = "DailyTaskData_C.bytes";
    private const string DailyRewardTable = "DailyTaskRewardData_C.bytes";
    private static readonly byte[] DungeonBytes = [1, 0, 0, 0, 7, 9];
    private static readonly byte[] CooperativeBytes = [1, 0, 0, 0, 8, 10, 11];
    private static readonly byte[] DailyTaskBytes = [1, 2, 3];
    private static readonly byte[] DailyRewardBytes = [4, 5, 6, 7];
    private static string DungeonSha => DatabaseReadTestDatabase.Sha(DungeonBytes);
    private static string CooperativeSha => DatabaseReadTestDatabase.Sha(CooperativeBytes);

    [Theory]
    [InlineData(false, false)]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public void Explicit_capture_only_looks_up_exact_slots_and_detaches_instance_slices(bool includeSkill, bool includeDaily)
    {
        var rows = RequiredRows(); byte[] dungeons = [255, .. DungeonBytes, 255], cooperatives = [255, .. CooperativeBytes, 255];
        rows.Add(DungeonTable, new(41, DungeonTable, DungeonSha, dungeons.AsMemory(1, DungeonBytes.Length)));
        rows.Add(CooperativeTable, new(41, CooperativeTable, CooperativeSha, cooperatives.AsMemory(1, CooperativeBytes.Length)));
        rows.Add(SkillTable, new(41, SkillTable, SkillDataParser.ReviewedSha256, new byte[] { 1, 0, 0, 0, 1 }));
        AddDaily(rows);
        rows.Add("Other.bytes", new(41, "Other.bytes", "unused", new byte[100]));
        var lookup = new LookupOnlyRows(rows);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup, includeSkillData: includeSkill,
            includeDailyCatalog: includeDaily, includeInstanceCatalog: true);

        var expected = BundleSourcePlan.RequiredTables.Select(name => name + ".bytes");
        if (includeSkill) expected = expected.Append(SkillTable);
        if (includeDaily) expected = expected.Append(DailyTaskTable).Append(DailyRewardTable);
        Assert.Equal(expected.Append(DungeonTable).Append(CooperativeTable), lookup.Lookups);
        Array.Fill(dungeons, (byte)0); Array.Fill(cooperatives, (byte)0); rows.Clear();
        Assert.Equal(DungeonBytes, snapshot.Table(41, DungeonTable)!.Bytes.ToArray());
        Assert.Equal(CooperativeBytes, snapshot.Table(41, CooperativeTable)!.Bytes.ToArray());
        Assert.True(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, DungeonSha, CooperativeSha));
        AssertRequiredMatch(snapshot);
        Assert.Equal(includeSkill, snapshot.Table(41, SkillTable) is not null);
        Assert.Equal(includeDaily, MatchesDaily(snapshot));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(snapshot));
        Assert.Null(snapshot.Table(41, "Other.bytes"));
    }

    [Fact]
    public void Default_capture_does_not_enumerate_or_retain_instance_slots()
    {
        var rows = InstanceRows(); var lookup = new LookupOnlyRows(rows);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup);
        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes"), lookup.Lookups);
        Assert.Null(snapshot.Table(41, DungeonTable)); Assert.Null(snapshot.Table(41, CooperativeTable));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, DungeonSha, CooperativeSha));
        AssertRequiredMatch(snapshot);
    }

    public static IEnumerable<object[]> InvalidRows() =>
        from name in new[] { DungeonTable, CooperativeTable }
        from anomaly in new[] { "missing", "wrong-version", "wrong-case", "null", "empty", "oversized" }
        select new object[] { name, anomaly };

    [Theory]
    [MemberData(nameof(InvalidRows))]
    public void Invalid_optional_inputs_are_not_copied_and_cannot_match(string name, string anomaly)
    {
        var rows = new Dictionary<string, RuntimeDatabaseTableInput?>(InstanceRows(), StringComparer.OrdinalIgnoreCase);
        var row = rows[name]!;
        rows[name] = anomaly switch
        {
            "missing" => null, "wrong-version" => row with { VersionId = 42 },
            "wrong-case" => row with { Name = name.ToLowerInvariant() }, "null" => row with { Data = null },
            "empty" => row with { Data = ReadOnlyMemory<byte>.Empty },
            "oversized" => row with { Data = new byte[OwnedRuntimeDatabaseSnapshot.MaximumTableBytes + 1] },
            _ => throw new InvalidOperationException()
        };
        long before = GC.GetAllocatedBytesForCurrentThread();
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeInstanceCatalog: true);
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 1024 * 1024);
        Assert.Null(snapshot.Table(41, name));
        Assert.NotNull(snapshot.Table(41, name == DungeonTable ? CooperativeTable : DungeonTable));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, DungeonSha, CooperativeSha));
        AssertRequiredMatch(snapshot);
    }

    public static IEnumerable<object[]> TamperedRows() =>
        from name in new[] { DungeonTable, CooperativeTable }
        from anomaly in new[] { "stored-hash", "payload", "self-consistent-replacement" }
        select new object[] { name, anomaly };

    [Theory]
    [MemberData(nameof(TamperedRows))]
    public void Instance_matching_requires_both_stored_and_actual_hashes_to_equal_each_expected_hash(string name, string anomaly)
    {
        var rows = InstanceRows(); var row = rows[name]!; byte[] changed = row.Data!.Value.ToArray(); changed[^1] ^= 255;
        rows[name] = anomaly switch
        {
            "stored-hash" => row with { RecordedSha256 = DatabaseReadTestDatabase.Sha(changed) },
            "payload" => row with { Data = changed },
            "self-consistent-replacement" => row with { Data = changed, RecordedSha256 = DatabaseReadTestDatabase.Sha(changed) },
            _ => throw new InvalidOperationException()
        };
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeInstanceCatalog: true);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, DungeonSha, CooperativeSha));
        AssertRequiredMatch(snapshot);
    }

    public static IEnumerable<object?[]> InvalidClaims() =>
        from dungeon in new[] { false, true }
        from claim in new string?[] { null, "", new string('0', 63), new string('0', 65), new string('g', 64), new string('A', 64), new string('0', 63) + "\n", new string('f', 100000) }
        select new object?[] { dungeon, claim };

    [Theory]
    [MemberData(nameof(InvalidClaims))]
    public void Null_malformed_or_noncanonical_expected_hashes_never_match(bool dungeon, string? invalid)
    {
        var rows = InstanceRows(); string name = dungeon ? DungeonTable : CooperativeTable;
        // Even a recorded value that agrees with the invalid claim cannot authorize matching.
        rows[name] = rows[name]! with { RecordedSha256 = invalid };
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeInstanceCatalog: true);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, dungeon ? invalid : DungeonSha, dungeon ? CooperativeSha : invalid));
        AssertRequiredMatch(snapshot);
    }

    [Fact]
    public void Instance_match_is_a_supplied_equality_claim_not_identity_or_required_resource_admission()
    {
        var rows = InstanceRows();
        foreach (string source in BundleSourcePlan.RequiredTables) rows.Remove(source + ".bytes");
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(new(41, "untrusted-key", "not-json"), rows, includeInstanceCatalog: true);
        Assert.True(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, DungeonSha, CooperativeSha));
        var required = RuntimeDatabaseStructuralMatcher.Match(snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests());
        Assert.False(required.MatchesSuppliedRuntime); Assert.False(required.HasVerifiedProvenance); Assert.False(required.RuntimeAdmitted);
        Assert.False(required.AssetsReady); Assert.False(required.CanSendPackets); Assert.False(required.ProvesDatabaseTransaction);
        Assert.False(typeof(RuntimeDatabaseStructuralMatcher).IsPublic);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(null, DungeonSha, CooperativeSha));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(OwnedRuntimeDatabaseSnapshot.Capture(null, rows, includeInstanceCatalog: true), DungeonSha, CooperativeSha));
    }

    [Theory]
    [InlineData(DungeonTable)]
    [InlineData(CooperativeTable)]
    public void Cancellation_during_capture_or_before_match_never_returns_a_partial_result(string name)
    {
        using var cts = new CancellationTokenSource();
        var rows = InstanceRows(); rows.Remove(name);
        var lookup = new LookupOnlyRows(rows, value => { if (value == name) cts.Cancel(); });
        OwnedRuntimeDatabaseSnapshot? snapshot = null;
        Assert.Throws<OperationCanceledException>(() => snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup, cts.Token, includeInstanceCatalog: true));
        Assert.Null(snapshot); Assert.Equal(name == DungeonTable ? 11 : 12, lookup.Lookups.Count);
        Assert.Throws<OperationCanceledException>(() => RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(null, null, null, cts.Token));
        var valid = OwnedRuntimeDatabaseSnapshot.Capture(Active(), InstanceRows(), includeInstanceCatalog: true);
        Assert.Throws<OperationCanceledException>(() => RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(valid, DungeonSha, CooperativeSha, cts.Token));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Detached_capture_uses_the_existing_160_mib_budget_across_all_five_optional_slots(bool cooperativeFits)
    {
        Assert.Equal(160L * 1024 * 1024, OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes);
        byte[] full = new byte[OwnedRuntimeDatabaseSnapshot.MaximumTableBytes];
        byte[] skill = [1, 0, 0, 0, 1];
        var rows = InstanceRows();
        AddDaily(rows);
        foreach (string source in BundleSourcePlan.RequiredTables)
            rows[source + ".bytes"] = new(41, source + ".bytes", "unused", full);
        string last = BundleSourcePlan.RequiredTables.Last() + ".bytes";
        int optionalBytes = skill.Length + DailyTaskBytes.Length + DailyRewardBytes.Length + DungeonBytes.Length +
            (cooperativeFits ? CooperativeBytes.Length : 0);
        rows[last] = rows[last]! with { Data = full.AsMemory(0, full.Length - optionalBytes) };
        rows.Add(SkillTable, new(41, SkillTable, SkillDataParser.ReviewedSha256, skill));
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeSkillData: true, includeDailyCatalog: true, includeInstanceCatalog: true);

        Assert.Equal(skill, snapshot.Table(41, SkillTable)!.Bytes.ToArray());
        Assert.Equal(DungeonBytes, snapshot.Table(41, DungeonTable)!.Bytes.ToArray());
        Assert.True(MatchesDaily(snapshot));
        Assert.Equal(cooperativeFits, snapshot.Table(41, CooperativeTable) is not null);
        long retained = BundleSourcePlan.RequiredTables.Sum(source => (long)snapshot.Table(41, source + ".bytes")!.Bytes.Length)
            + snapshot.Table(41, SkillTable)!.Bytes.Length + snapshot.Table(41, DailyTaskTable)!.Bytes.Length
            + snapshot.Table(41, DailyRewardTable)!.Bytes.Length + snapshot.Table(41, DungeonTable)!.Bytes.Length
            + (snapshot.Table(41, CooperativeTable)?.ByteLength ?? 0);
        Assert.Equal(OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes, retained);
        Assert.Equal(cooperativeFits, RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(snapshot, DungeonSha, CooperativeSha));
    }

    private static RuntimeDatabaseActiveInput Active() => new(41, DatabaseReadTestDatabase.Identity().Key, DatabaseReadTestDatabase.Identity().CanonicalJson);
    private static void AddDaily(Dictionary<string, RuntimeDatabaseTableInput?> rows)
    {
        rows.Add(DailyTaskTable, new(41, DailyTaskTable, DatabaseReadTestDatabase.Sha(DailyTaskBytes), DailyTaskBytes));
        rows.Add(DailyRewardTable, new(41, DailyRewardTable, DatabaseReadTestDatabase.Sha(DailyRewardBytes), DailyRewardBytes));
    }
    private static bool MatchesDaily(OwnedRuntimeDatabaseSnapshot snapshot) =>
        RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, DatabaseReadTestDatabase.Sha(DailyTaskBytes), DatabaseReadTestDatabase.Sha(DailyRewardBytes));
    private static Dictionary<string, RuntimeDatabaseTableInput?> InstanceRows()
    {
        var rows = RequiredRows();
        rows.Add(DungeonTable, new(41, DungeonTable, DungeonSha, DungeonBytes)); rows.Add(CooperativeTable, new(41, CooperativeTable, CooperativeSha, CooperativeBytes));
        return rows;
    }
    private static Dictionary<string, RuntimeDatabaseTableInput?> RequiredRows() => DatabaseMatchPythonVectors.Case("all-ten-match").GetProperty("rows").EnumerateArray()
        .ToDictionary(row => row.GetProperty("name").GetString()!, row => (RuntimeDatabaseTableInput?)new RuntimeDatabaseTableInput(
            row.GetProperty("active_id").GetInt64(), row.GetProperty("name").GetString(), row.GetProperty("sha256").GetString(),
            Convert.FromBase64String(row.GetProperty("data").GetProperty("value").GetString()!)), StringComparer.Ordinal);
    private static void AssertRequiredMatch(OwnedRuntimeDatabaseSnapshot snapshot)
    {
        var result = RuntimeDatabaseStructuralMatcher.Match(snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests());
        Assert.True(result.MatchesSuppliedRuntime); Assert.Equal(BundleSourcePlan.RequiredTables, result.ExaminedSources);
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted); Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
    }
    private sealed class LookupOnlyRows(Dictionary<string, RuntimeDatabaseTableInput?> rows, Action<string>? lookup = null)
        : IReadOnlyDictionary<string, RuntimeDatabaseTableInput?>
    {
        internal List<string> Lookups { get; } = [];
        public bool TryGetValue(string key, out RuntimeDatabaseTableInput? value) { Lookups.Add(key); lookup?.Invoke(key); return rows.TryGetValue(key, out value); }
        public int Count => throw new InvalidOperationException("Unneeded row count");
        public IEnumerable<string> Keys => throw new InvalidOperationException("Unbounded row enumeration");
        public IEnumerable<RuntimeDatabaseTableInput?> Values => throw new InvalidOperationException("Unbounded row enumeration");
        public RuntimeDatabaseTableInput? this[string key] => throw new InvalidOperationException("Unneeded lookup");
        public bool ContainsKey(string key) => throw new InvalidOperationException("Unneeded lookup");
        public IEnumerator<KeyValuePair<string, RuntimeDatabaseTableInput?>> GetEnumerator() => throw new InvalidOperationException("Unbounded row enumeration");
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
