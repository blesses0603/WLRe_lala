using System.Collections;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeDatabaseDailyCatalogMatchTests
{
    private const string TaskTable = "DailyTaskData_C.bytes";
    private const string RewardTable = "DailyTaskRewardData_C.bytes";
    private const string SkillTable = "SkillData_C.bytes";
    private static readonly byte[] TaskBytes = [1, 0, 0, 0, 7, 9];
    private static readonly byte[] RewardBytes = [1, 0, 0, 0, 8, 10, 11];
    private static string TaskSha => DatabaseReadTestDatabase.Sha(TaskBytes);
    private static string RewardSha => DatabaseReadTestDatabase.Sha(RewardBytes);

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void Explicit_capture_only_looks_up_exact_slots_and_detaches_daily_slices(bool includeSkill)
    {
        var rows = RequiredRows(); byte[] tasks = [255, .. TaskBytes, 255], rewards = [255, .. RewardBytes, 255];
        rows.Add(TaskTable, new(41, TaskTable, TaskSha, tasks.AsMemory(1, TaskBytes.Length)));
        rows.Add(RewardTable, new(41, RewardTable, RewardSha, rewards.AsMemory(1, RewardBytes.Length)));
        rows.Add(SkillTable, new(41, SkillTable, SkillDataParser.ReviewedSha256, new byte[] { 1, 0, 0, 0, 1 }));
        rows.Add("Other.bytes", new(41, "Other.bytes", "unused", new byte[100]));
        var lookup = new LookupOnlyRows(rows);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup, includeSkillData: includeSkill, includeDailyCatalog: true);

        var expected = BundleSourcePlan.RequiredTables.Select(name => name + ".bytes");
        if (includeSkill) expected = expected.Append(SkillTable);
        Assert.Equal(expected.Append(TaskTable).Append(RewardTable), lookup.Lookups);
        Array.Fill(tasks, (byte)0); Array.Fill(rewards, (byte)0); rows.Clear();
        Assert.Equal(TaskBytes, snapshot.Table(41, TaskTable)!.Bytes.ToArray());
        Assert.Equal(RewardBytes, snapshot.Table(41, RewardTable)!.Bytes.ToArray());
        Assert.True(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, TaskSha, RewardSha));
        AssertRequiredMatch(snapshot);
        Assert.Equal(includeSkill, snapshot.Table(41, SkillTable) is not null);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(snapshot));
        Assert.Null(snapshot.Table(41, "Other.bytes"));
    }

    [Fact]
    public void Default_capture_does_not_enumerate_or_retain_daily_slots()
    {
        var rows = DailyRows(); var lookup = new LookupOnlyRows(rows);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup);
        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes"), lookup.Lookups);
        Assert.Null(snapshot.Table(41, TaskTable)); Assert.Null(snapshot.Table(41, RewardTable));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, TaskSha, RewardSha));
        AssertRequiredMatch(snapshot);
    }

    public static IEnumerable<object[]> InvalidRows() =>
        from name in new[] { TaskTable, RewardTable }
        from anomaly in new[] { "missing", "wrong-version", "wrong-case", "null", "empty", "oversized" }
        select new object[] { name, anomaly };

    [Theory]
    [MemberData(nameof(InvalidRows))]
    public void Invalid_optional_inputs_are_not_copied_and_cannot_match(string name, string anomaly)
    {
        var rows = new Dictionary<string, RuntimeDatabaseTableInput?>(DailyRows(), StringComparer.OrdinalIgnoreCase);
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
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeDailyCatalog: true);
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 1024 * 1024);
        Assert.Null(snapshot.Table(41, name));
        Assert.NotNull(snapshot.Table(41, name == TaskTable ? RewardTable : TaskTable));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, TaskSha, RewardSha));
        AssertRequiredMatch(snapshot);
    }

    public static IEnumerable<object[]> TamperedRows() =>
        from name in new[] { TaskTable, RewardTable }
        from anomaly in new[] { "stored-hash", "payload", "self-consistent-replacement" }
        select new object[] { name, anomaly };

    [Theory]
    [MemberData(nameof(TamperedRows))]
    public void Daily_matching_requires_both_stored_and_actual_hashes_to_equal_each_expected_hash(string name, string anomaly)
    {
        var rows = DailyRows(); var row = rows[name]!; byte[] changed = row.Data!.Value.ToArray(); changed[^1] ^= 255;
        rows[name] = anomaly switch
        {
            "stored-hash" => row with { RecordedSha256 = DatabaseReadTestDatabase.Sha(changed) },
            "payload" => row with { Data = changed },
            "self-consistent-replacement" => row with { Data = changed, RecordedSha256 = DatabaseReadTestDatabase.Sha(changed) },
            _ => throw new InvalidOperationException()
        };
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeDailyCatalog: true);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, TaskSha, RewardSha));
        AssertRequiredMatch(snapshot);
    }

    public static IEnumerable<object?[]> InvalidClaims() =>
        from task in new[] { false, true }
        from claim in new string?[] { null, "", new string('0', 63), new string('0', 65), new string('g', 64), new string('A', 64), new string('0', 63) + "\n", new string('f', 100000) }
        select new object?[] { task, claim };

    [Theory]
    [MemberData(nameof(InvalidClaims))]
    public void Null_malformed_or_noncanonical_expected_hashes_never_match(bool task, string? invalid)
    {
        var rows = DailyRows(); string name = task ? TaskTable : RewardTable;
        // Even a recorded value that agrees with the invalid claim cannot authorize matching.
        rows[name] = rows[name]! with { RecordedSha256 = invalid };
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeDailyCatalog: true);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, task ? invalid : TaskSha, task ? RewardSha : invalid));
        AssertRequiredMatch(snapshot);
    }

    [Fact]
    public void Daily_match_is_a_supplied_equality_claim_not_identity_or_required_resource_admission()
    {
        var rows = DailyRows();
        foreach (string source in BundleSourcePlan.RequiredTables) rows.Remove(source + ".bytes");
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(new(41, "untrusted-key", "not-json"), rows, includeDailyCatalog: true);
        Assert.True(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, TaskSha, RewardSha));
        var required = RuntimeDatabaseStructuralMatcher.Match(snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests());
        Assert.False(required.MatchesSuppliedRuntime); Assert.False(required.HasVerifiedProvenance); Assert.False(required.RuntimeAdmitted);
        Assert.False(required.AssetsReady); Assert.False(required.CanSendPackets); Assert.False(required.ProvesDatabaseTransaction);
        Assert.False(typeof(RuntimeDatabaseStructuralMatcher).IsPublic);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(null, TaskSha, RewardSha));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(OwnedRuntimeDatabaseSnapshot.Capture(null, rows, includeDailyCatalog: true), TaskSha, RewardSha));
    }

    [Theory]
    [InlineData(TaskTable)]
    [InlineData(RewardTable)]
    public void Cancellation_during_capture_or_before_match_never_returns_a_partial_result(string name)
    {
        using var cts = new CancellationTokenSource();
        var rows = DailyRows(); rows.Remove(name);
        var lookup = new LookupOnlyRows(rows, value => { if (value == name) cts.Cancel(); });
        OwnedRuntimeDatabaseSnapshot? snapshot = null;
        Assert.Throws<OperationCanceledException>(() => snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup, cts.Token, includeDailyCatalog: true));
        Assert.Null(snapshot); Assert.Equal(name == TaskTable ? 11 : 12, lookup.Lookups.Count);
        Assert.Throws<OperationCanceledException>(() => RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(null, null, null, cts.Token));
        var valid = OwnedRuntimeDatabaseSnapshot.Capture(Active(), DailyRows(), includeDailyCatalog: true);
        Assert.Throws<OperationCanceledException>(() => RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(valid, TaskSha, RewardSha, cts.Token));
    }

    [Fact]
    public void Detached_capture_uses_the_existing_160_mib_budget_across_required_skill_task_and_reward()
    {
        Assert.Equal(160L * 1024 * 1024, OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes);
        byte[] full = new byte[OwnedRuntimeDatabaseSnapshot.MaximumTableBytes];
        byte[] skill = [1, 0, 0, 0, 1];
        var rows = DailyRows();
        foreach (string source in BundleSourcePlan.RequiredTables)
            rows[source + ".bytes"] = new(41, source + ".bytes", "unused", full);
        string last = BundleSourcePlan.RequiredTables.Last() + ".bytes";
        rows[last] = rows[last]! with { Data = full.AsMemory(0, full.Length - skill.Length - TaskBytes.Length) };
        rows.Add(SkillTable, new(41, SkillTable, SkillDataParser.ReviewedSha256, skill));
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeSkillData: true, includeDailyCatalog: true);

        Assert.Equal(skill, snapshot.Table(41, SkillTable)!.Bytes.ToArray());
        Assert.Equal(TaskBytes, snapshot.Table(41, TaskTable)!.Bytes.ToArray());
        Assert.Null(snapshot.Table(41, RewardTable));
        long retained = BundleSourcePlan.RequiredTables.Sum(source => (long)snapshot.Table(41, source + ".bytes")!.Bytes.Length)
            + snapshot.Table(41, SkillTable)!.Bytes.Length + snapshot.Table(41, TaskTable)!.Bytes.Length;
        Assert.Equal(OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes, retained);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(snapshot, TaskSha, RewardSha));
    }

    private static RuntimeDatabaseActiveInput Active() => new(41, DatabaseReadTestDatabase.Identity().Key, DatabaseReadTestDatabase.Identity().CanonicalJson);
    private static Dictionary<string, RuntimeDatabaseTableInput?> DailyRows()
    {
        var rows = RequiredRows();
        rows.Add(TaskTable, new(41, TaskTable, TaskSha, TaskBytes)); rows.Add(RewardTable, new(41, RewardTable, RewardSha, RewardBytes));
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
