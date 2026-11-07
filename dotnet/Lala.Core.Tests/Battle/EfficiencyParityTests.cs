using System.Globalization;
using System.Numerics;
using System.Text.Json;
using Lala.Core.Battle;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class EfficiencyParityTests
{
    [Theory]
    [MemberData(nameof(EfficiencyPythonVectors.Curves), MemberType = typeof(EfficiencyPythonVectors))]
    public void CurvesMatchPython(int level, int degree, long need, long cumulative)
    {
        Assert.Equal(need, EfficiencyRules.Need(level, degree));
        Assert.Equal(cumulative, EfficiencyRules.Cumulative(level, degree));
    }

    [Theory]
    [MemberData(nameof(EfficiencyPythonVectors.Progress), MemberType = typeof(EfficiencyPythonVectors))]
    public void ProgressMatchesPython(long total, int level, int degree, long? remaining, double? percent, long? target)
    {
        var result = EfficiencyRules.Progress(total, level, degree);
        Assert.Equal(remaining, result.Remaining);
        Number(percent, result.Percent);
        Assert.Equal(target, result.FirstRebirth190Remaining);
    }

    [Theory]
    [MemberData(nameof(EfficiencyPythonVectors.Durations), MemberType = typeof(EfficiencyPythonVectors))]
    public void DurationMatchesPython(double? seconds, string expected) => Assert.Equal(expected, EfficiencyRules.Duration(seconds));

    [Theory]
    [MemberData(nameof(EfficiencyPythonVectors.Forecasts), MemberType = typeof(EfficiencyPythonVectors))]
    public void ForecastMatchesPython(double? remaining, double? rate, double elapsed, string expected) =>
        Assert.Equal(expected, EfficiencyRules.Forecast(remaining, rate, elapsed));

    [Theory]
    [MemberData(nameof(EfficiencyPythonVectors.Sequences), MemberType = typeof(EfficiencyPythonVectors))]
    public void EveryStateTransitionMatchesPython(string name, string json)
    {
        Assert.NotEmpty(name);
        using var document = JsonDocument.Parse(json);
        var tracker = new EfficiencyTracker(() => 1234.5);
        var reduced = EfficiencySnapshot.Empty;
        var snapshots = new List<(EfficiencySnapshot Snapshot, JsonElement Expected)>();
        foreach (var step in document.RootElement.EnumerateArray())
        {
            if (step.GetProperty("reset").GetBoolean()) { tracker.Reset(); reduced = EfficiencySnapshot.Empty; }
            var state = tracker.Observe(Knowledge(step.GetProperty("knowledge")), Event(step.GetProperty("event")));
            reduced = EfficiencyReducer.Apply(reduced, Knowledge(step.GetProperty("knowledge")),
                Event(step.GetProperty("event")), () => 1234.5);
            AssertSnapshot(step.GetProperty("expected"), state);
            AssertSnapshot(step.GetProperty("expected"), reduced);
            snapshots.Add((state, step.GetProperty("expected")));
            snapshots.Add((reduced, step.GetProperty("expected")));
        }
        // Later observations must not mutate a published snapshot or nested history.
        tracker.Reset();
        foreach (var (snapshot, expected) in snapshots) AssertSnapshot(expected, snapshot);
    }

    internal static EfficiencyKnowledgeSnapshot Knowledge(JsonElement value) => new(
        U32(value, "role_id"), Stats(value.GetProperty("stats")),
        value.GetProperty("companions").EnumerateObject().Select(entry => new KeyValuePair<int, EfficiencyCompanion>(
            int.Parse(entry.Name, CultureInfo.InvariantCulture), new(U32(entry.Value, "npc_id"), Stats(entry.Value.GetProperty("stats"))))),
        value.GetProperty("name").GetString()!);

    private static EfficiencyStats Stats(JsonElement value) => new(I64(value, "exp"), I32(value, "level"), I32(value, "degree"),
        value.TryGetProperty("name", out var name) ? name.GetString() : null);

    private static EfficiencySubject Subject(string value) => value == "self" ? EfficiencySubject.Player
        : EfficiencySubject.Companion(int.Parse(value.Split(':')[1], CultureInfo.InvariantCulture));

    private static EfficiencyEvent Event(JsonElement value)
    {
        EfficiencyEvent result = value.GetProperty("type").GetString() switch
        {
            "battle_start" => new EfficiencyBattleStart(value.GetProperty("units").EnumerateArray().Select(unit => new EfficiencyBattleUnit(
                U32(unit, "pid"), U32(unit, "master_id"), I32(unit, "npc_index")))),
            "event_end" => new EfficiencyEventEnd(),
            "star_info" => new EfficiencyStarInfo(value.GetProperty("exp").GetInt64()),
            "attribute_set" => new EfficiencyAttributeSet(Subject(value.GetProperty("entity").GetString()!),
                value.GetProperty("kind").GetInt32(), value.GetProperty("value").GetInt64(), I32(value, "parameter") ?? 0, I32(value, "human_kind")),
            _ => new EfficiencyRefresh()
        };
        return result with
        {
            ObservedAt = value.TryGetProperty("_observed_at", out var time) ? Floating(time) : null,
            Offline = value.TryGetProperty("_offline", out var offline) ? offline.GetBoolean() : null
        };
    }

    internal static void AssertSnapshot(JsonElement expected, EfficiencySnapshot actual)
    {
        Assert.Equal(U32(expected, "role_id"), actual.RoleId);
        Assert.Equal(expected.GetProperty("pending").GetBoolean(), actual.Pending);
        Assert.Equal(expected.GetProperty("offline").GetBoolean(), actual.Offline);
        Assert.Equal(expected.GetProperty("battles").GetInt64(), actual.Battles);
        Assert.Equal(expected.GetProperty("dirty").EnumerateArray().Select(x => x.GetString()), actual.Dirty.Select(x => x.ToString()));
        Assert.Equal(expected.GetProperty("participants").EnumerateArray().Select(x => x.GetString()), actual.Participants.Select(x => x.ToString()));
        var rows = expected.GetProperty("rows");
        Assert.Equal(rows.EnumerateObject().Count(), actual.Rows.Count);
        foreach (var entry in rows.EnumerateObject())
        {
            var row = actual.Rows[Subject(entry.Name)];
            var wanted = entry.Value;
            Assert.Equal(U32(wanted, "identity"), row.Identity);
            Assert.Equal(wanted.GetProperty("name").GetString(), row.Name);
            Assert.Equal(I64(wanted, "exp"), row.Experience);
            Assert.Equal(I32(wanted, "level"), row.Level);
            Assert.Equal(I32(wanted, "degree"), row.Degree);
            Assert.Equal(wanted.GetProperty("level_inferred").GetBoolean(), row.LevelInferred);
            Assert.Equal(wanted.GetProperty("degree_inferred").GetBoolean(), row.DegreeInferred);
            Assert.Equal(I64(wanted, "last_total"), row.LastTotal);
            Assert.Equal(Integer(wanted.GetProperty("last_gain")), row.LastGain);
            Assert.Equal(Integer(wanted.GetProperty("earned")), row.Earned);
            Assert.Equal(wanted.GetProperty("count").GetInt64(), row.Count);
            Number(Floating(wanted.GetProperty("first_time")), row.FirstTime);
            Number(Floating(wanted.GetProperty("last_time")), row.LastTime);
            Assert.Equal(I32(wanted, "sample_degree"), row.SampleDegree);
            var history = wanted.GetProperty("history").EnumerateArray().ToArray();
            Assert.Equal(history.Length, row.History.Length);
            for (int i = 0; i < history.Length; i++)
            {
                Assert.Equal(Integer(history[i][0]), row.History[i].Earned);
                Number(Floating(history[i][1]), row.History[i].ObservedAt);
            }
            var rates = EfficiencyRules.Rates(row);
            var actualRates = new[] { rates.All, rates.Last10, rates.Last30 };
            var expectedRates = wanted.GetProperty("rates").EnumerateArray().ToArray();
            for (int i = 0; i < actualRates.Length; i++)
            {
                Number(Floating(expectedRates[i][0]), actualRates[i].ExperiencePerMinute);
                Assert.Equal(expectedRates[i][1].GetInt64(), actualRates[i].Count);
            }
        }
    }

    private static uint? U32(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetUInt32() : null;
    private static int? I32(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetInt32() : null;
    private static long? I64(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetInt64() : null;
    private static BigInteger? Integer(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null : BigInteger.Parse(value.GetRawText(), CultureInfo.InvariantCulture);
    private static double? Floating(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null => null,
        JsonValueKind.String => value.GetString() switch { "nan" => double.NaN, "inf" => double.PositiveInfinity, "-inf" => double.NegativeInfinity, _ => throw new InvalidOperationException() },
        _ => value.GetDouble()
    };
    private static void Number(double? expected, double? actual)
    {
        if (expected is null) Assert.Null(actual);
        else
        {
            Assert.NotNull(actual);
            if (double.IsFinite(expected.Value)) Assert.InRange(Math.Abs(expected.Value - actual.Value), 0, Math.Max(1e-9, Math.Abs(expected.Value) * 1e-12));
            else Assert.Equal(expected, actual);
        }
    }
}
