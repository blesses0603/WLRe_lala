using System.Collections.Frozen;
using System.Globalization;
using System.Numerics;

namespace Lala.Core.Battle;

/// <summary>Offline port of core/efficiency.py. Curves are EXP_Monitor reference formulas, not new protocol evidence.</summary>
public static class EfficiencyRules
{
    public static IReadOnlyDictionary<int, string> Stages { get; } = new Dictionary<int, string>
        { [0] = "未轉生", [1] = "一轉", [2] = "二轉星脈" }.ToFrozenDictionary();
    private static readonly long[,] Totals = BuildTotals();

    public static int? MaximumLevel(int? degree) => MaximumLevel((long?)degree);
    public static int? MaximumLevel(long? degree) => degree switch { 0 => 199, 1 => 190, 2 => 100, _ => null };

    /// <summary>Keep full received evidence; narrow only after validating the supported curve domain.</summary>
    public static long? Need(long level, long degree) => level is >= 1 and <= 400 && degree is >= 0 and <= 2
        ? Need((int)level, (int)degree) : null;

    /// <summary>Returns null outside the supported integer level/degree domain.</summary>
    public static long? Need(int level, int degree)
    {
        if (level is < 1 or > 400) return null;
        double value = degree switch
        {
            0 => Math.Pow(level, 3.1) + 5,
            1 => Math.Pow(level, 3.3) + (level <= 150 ? 50 : Math.Pow(level - 150, 4.9)),
            2 => level <= 1 ? 0 : Math.Pow(300 + level, 2.6) + Math.Pow(Math.Max(0, level - 49), 5.6),
            _ => double.NaN
        };
        return double.IsNaN(value) ? null : checked((long)Math.Floor(value + .5));
    }

    /// <summary>Level-one origin, matching EXP_Monitor. Cache is fixed-size and private.</summary>
    public static long? Cumulative(int level, int degree) => Cumulative((long)level, degree);
    public static long? Cumulative(long level, long degree) => level is >= 1 and <= 400 && degree is >= 0 and <= 2
        ? Totals[(int)degree, (int)level] : null;

    public static EfficiencyProgress Progress(long? total, int? level, int? degree) => Progress(total, (long?)level, degree);
    public static EfficiencyProgress Progress(long? total, long? level, long? degree)
    {
        int? maximum = MaximumLevel(degree);
        if (total is null || maximum is null || level is null || level < 1 || level > maximum)
            return EfficiencyProgress.Unknown;
        long baseline = Totals[(int)degree!.Value, (int)level.Value];
        if (level == maximum)
            return total >= baseline ? new(0, 100, degree == 1 ? 0 : null) : EfficiencyProgress.Unknown;
        long required = Need(level.Value + 1, degree.Value)!.Value;
        if (total < baseline || total > baseline + required) return EfficiencyProgress.Unknown;
        return new(baseline + required - total, (double)(total.Value - baseline) / required * 100,
            degree == 1 ? Math.Max(0, Totals[1, 190] - total.Value) : null);
    }

    public static EfficiencyRates Rates(EfficiencyRowSnapshot row)
    {
        ArgumentNullException.ThrowIfNull(row);
        double seconds = row.LastTime is { } last && row.FirstTime is { } first ? last - first : 0;
        var all = new EfficiencyRate(seconds > 0 && row.Count != 0 ? (double)(row.Earned * 60) / seconds : null, row.Count);
        return new(all, Window(10), Window(30));

        EfficiencyRate Window(int size)
        {
            if (row.History.IsDefaultOrEmpty) return new(null, 0);
            int firstIndex = Math.Max(0, row.History.Length - size - 1);
            int count = row.History.Length - firstIndex - 1;
            double elapsed = count > 0 ? row.History[^1].ObservedAt - row.History[firstIndex].ObservedAt : 0;
            return new(elapsed > 0 ? (double)((row.History[^1].Earned - row.History[firstIndex].Earned) * 60) / elapsed : null, count);
        }
    }

    public static string Duration(double? seconds)
    {
        if (seconds is null || !double.IsFinite(seconds.Value)) return "等待統計";
        BigInteger rounded = new(Math.Ceiling(Math.Max(0, seconds.Value)));
        BigInteger days = BigInteger.DivRem(rounded, 86400, out var remainder);
        BigInteger hours = BigInteger.DivRem(remainder, 3600, out remainder);
        BigInteger minutes = BigInteger.DivRem(remainder, 60, out remainder);
        static string Part(BigInteger value, string unit) => value.IsZero ? "" : value.ToString(CultureInfo.InvariantCulture) + unit;
        return Part(days, "天") + Part(hours, "時") + Part(minutes, "分") + remainder.ToString(CultureInfo.InvariantCulture) + "秒";
    }

    public static string Forecast(double? remaining, double? rate, double elapsed = 0)
    {
        if (remaining is null) return "資料待同步";
        if (remaining == 0) return "已達標";
        if (rate is null || rate <= 0) return "等待效率樣本";
        double seconds = remaining.Value / rate.Value * 60 - elapsed;
        return seconds > 0 ? Duration(seconds) : "等待下場確認";
    }

    private static long[,] BuildTotals()
    {
        var result = new long[3, 401];
        for (int degree = 0; degree <= 2; degree++)
            for (int level = 2; level <= 400; level++)
                result[degree, level] = checked(result[degree, level - 1] + Need(level, degree)!.Value);
        return result;
    }
}
