using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class BattleDisplayParityTests
{
    [Theory]
    [MemberData(nameof(BattleDisplayPythonVectors.Cases), MemberType = typeof(BattleDisplayPythonVectors))]
    public void LabelsAndOrderedAttackLinesMatchRetainedPythonInEveryCulture(string name, string json)
    {
        _ = name;
        using var document = JsonDocument.Parse(json);
        var row = document.RootElement;
        var state = ReadState(row.GetProperty("state"));
        var report = ReadReport(row.GetProperty("event"));
        var expected = row.GetProperty("expected_lines").EnumerateArray().Select(value => value.GetString()!).ToArray();
        var beforeState = JsonSerializer.Serialize(state);
        var beforeReport = JsonSerializer.Serialize(report);
        var previous = CultureInfo.CurrentCulture;
        var previousUi = CultureInfo.CurrentUICulture;
        try
        {
            foreach (var culture in new[] { "", "ar-SA", "tr-TR", "fr-FR" })
            {
                CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo(culture);
                CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo(culture);
                foreach (var label in row.GetProperty("labels").EnumerateArray())
                    Assert.Equal(label.GetProperty("expected").GetString(), BattleDisplayRules.UnitLabel(state,
                        new(label.GetProperty("col").GetByte(), label.GetProperty("row").GetByte())));
                Assert.Equal(expected, BattleDisplayRules.AttackLines(report, state));
            }
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
            CultureInfo.CurrentUICulture = previousUi;
        }
        Assert.Equal(beforeState, JsonSerializer.Serialize(state));
        Assert.Equal(beforeReport, JsonSerializer.Serialize(report));
    }

    [Fact]
    public void OracleCountsAndSourceHashArePinnedAndNewlinePortable()
    {
        var rows = BattleDisplayPythonVectors.Cases().Select(row => (string)row[1]).ToArray();
        Assert.Equal(116, rows.Length);
        Assert.Equal(BattleDisplayPythonVectors.CaseCount, rows.Length);
        var labels = 0;
        var lines = 0;
        foreach (var json in rows)
        {
            using var row = JsonDocument.Parse(json);
            labels += row.RootElement.GetProperty("labels").GetArrayLength();
            lines += row.RootElement.GetProperty("expected_lines").GetArrayLength();
        }
        Assert.Equal(12, labels);
        Assert.Equal(155, lines);
        Assert.Equal(BattleDisplayPythonVectors.LabelCount, labels);
        Assert.Equal(BattleDisplayPythonVectors.LineCount, lines);

        var lf = Normalize(File.ReadAllBytes(FindFile(BattleDisplayPythonVectors.SourcePath)));
        var crlf = lf.SelectMany(value => value == 10 ? new byte[] { 13, 10 } : [value]).ToArray();
        Assert.Equal(BattleDisplayPythonVectors.SourceSha256, Hash(lf));
        Assert.Equal(BattleDisplayPythonVectors.SourceSha256, Hash(crlf));
        Assert.NotEqual(BattleDisplayPythonVectors.SourceSha256, Hash([.. lf, 32]));
    }

    [Fact]
    public void HumanReadableFixtureFitsPhysicalByteLimitWithBothCheckoutNewlines()
    {
        var current = File.ReadAllBytes(FindFile("dotnet/Lala.Core.Tests/Battle/BattleDisplayPythonVectors.cs"));
        var lf = Normalize(current);
        Assert.InRange(current.Length, 1, 500000);
        Assert.InRange(lf.Length, 1, 500000);
        Assert.InRange(lf.Length + lf.Count(value => value == 10), 1, 500000);
    }

    private static BattleEventSnapshot ReadState(JsonElement state)
    {
        if (!state.TryGetProperty("battle_units", out var units)) return BattleEventSnapshot.Empty;
        var layouts = units.EnumerateObject().Select(entry =>
        {
            var slot = entry.Name.Split(':');
            return new BattleUnit(16, 0, 71, 0, 0,
                byte.Parse(slot[0], CultureInfo.InvariantCulture), byte.Parse(slot[1], CultureInfo.InvariantCulture),
                100, 40, 90, 20, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, Text(entry.Value, "name"), []);
        }).ToImmutableArray();
        return BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleUnitsEvent(layouts));
    }

    private static AttackResultEvent ReadReport(JsonElement report) => new(report.GetProperty("actions").EnumerateArray()
        .Select(action => new AttackAction(action.GetProperty("col").GetByte(), action.GetProperty("row").GetByte(),
            action.GetProperty("skill_id").GetUInt16(), action.GetProperty("skill_level").GetByte(),
            action.GetProperty("fight_area").GetByte(), Text(action, "skill_name"),
            action.GetProperty("targets").EnumerateArray().Select(target => new AttackTarget(
                target.GetProperty("col").GetByte(), target.GetProperty("row").GetByte(),
                target.GetProperty("attack_result").GetByte(), target.GetProperty("hit_action").GetByte(),
                target.GetProperty("attributes").EnumerateArray().Select(value => new AttackAttribute(
                    value.GetProperty("kind").GetByte(), Text(value, "attribute"),
                    value.GetProperty("value").GetUInt32(), value.GetProperty("sign").GetByte()))
                    .ToImmutableArray())).ToImmutableArray())).ToImmutableArray());

    private static string Text(JsonElement value, string property) =>
        value.TryGetProperty(property, out var text) ? text.GetString() ?? "" : "";

    private static string FindFile(string path)
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, path))) directory = directory.Parent;
        Assert.NotNull(directory);
        return Path.Combine(directory.FullName, path);
    }

    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(Normalize(bytes))).ToLowerInvariant();

    private static byte[] Normalize(byte[] bytes)
    {
        var result = new List<byte>(bytes.Length);
        for (var index = 0; index < bytes.Length; index++)
        {
            if (bytes[index] == 13 && index + 1 < bytes.Length && bytes[index + 1] == 10) continue;
            result.Add(bytes[index]);
        }
        return result.ToArray();
    }
}
