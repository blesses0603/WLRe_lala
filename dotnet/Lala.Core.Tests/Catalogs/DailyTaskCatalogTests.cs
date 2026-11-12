using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs;

public sealed class DailyTaskCatalogTests
{
    [Theory]
    [MemberData(nameof(PythonDailyCatalogVectors.Tasks), MemberType = typeof(PythonDailyCatalogVectors))]
    public void TaskLayoutMatchesEveryPythonField(string name, string encoded, string? expected)
    {
        Assert.NotEmpty(name);
        byte[] raw = Convert.FromBase64String(encoded);
        if (expected is null)
        {
            Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseTasks(raw));
            return;
        }
        var table = DailyTaskDataParser.ParseTasks(raw);
        AssertJson(expected, new
        {
            group_count = table.Groups.Length, task_count = table.Tasks.Length,
            groups = table.Groups.Select(g => new { mission_kind = g.MissionKind, refresh_kind = g.RefreshKind, group = g.Group }),
            tasks = table.Tasks.Select(Project), missing_group_ids = table.MissingGroupIds.Select(id => (int)id)
        });
    }

    [Theory]
    [MemberData(nameof(PythonDailyCatalogVectors.Rewards), MemberType = typeof(PythonDailyCatalogVectors))]
    public void RewardLayoutMatchesEveryPythonField(string name, string encoded, string? expected)
    {
        Assert.NotEmpty(name);
        byte[] raw = Convert.FromBase64String(encoded);
        if (expected is null)
        {
            Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseRewards(raw));
            return;
        }
        AssertJson(expected, DailyTaskDataParser.ParseRewards(raw).Rewards.Select(Project));
    }

    [Theory]
    [MemberData(nameof(PythonDailyCatalogVectors.Bind), MemberType = typeof(PythonDailyCatalogVectors))]
    public void BindingMatchesPythonMetadataAndRules(string name, string encodedTasks, string encodedRewards,
        string textJson, string itemJson, string? expected)
    {
        Assert.NotEmpty(name);
        var tasks = DailyTaskDataParser.ParseTasks(Convert.FromBase64String(encodedTasks));
        var rewards = DailyTaskDataParser.ParseRewards(Convert.FromBase64String(encodedRewards));
        var texts = JsonSerializer.Deserialize<Dictionary<uint, string?>>(textJson)!;
        var items = JsonSerializer.Deserialize<HashSet<uint>>(itemJson)!;
        if (expected is null)
        {
            Assert.Throws<CatalogDecodeException>(() => DailyTaskCatalogBinder.Bind(tasks, rewards, texts, items));
            return;
        }
        var preview = DailyTaskCatalogBinder.Bind(tasks, rewards, texts, items);
        AssertJson(expected, new
        {
            tasks = preview.Tasks.Select(t =>
            {
                var row = Project(t.Data);
                row["name"] = t.Name; row["cycle"] = t.Cycle; row["goal"] = t.Goal;
                return row;
            }),
            rewards = preview.Rewards.Select(Project)
        });
        Assert.False(preview.AssetsReady);
        Assert.False(preview.CanSendPackets);
        var definitions = preview.ToPlanningDefinitions();
        Assert.Equal(preview.Tasks.Length, definitions.Tasks.Length);
        Assert.Equal(preview.Rewards.Length, definitions.Rewards.Length);
        foreach (var (bound, definition) in preview.Tasks.Zip(definitions.Tasks))
        {
            Assert.Equal(bound.Cycle, definition.Cycle);
            Assert.Equal(bound.Data.Group, definition.Group);
            Assert.Equal(bound.Data.Index, definition.Index);
            Assert.Equal(bound.Data.Id, definition.Id);
            Assert.Equal(bound.Goal, definition.Goal);
            Assert.Equal(bound.Data.Awards, definition.Awards);
        }
        foreach (var (bound, definition) in preview.Rewards.Zip(definitions.Rewards))
        {
            Assert.Equal(bound.Kind, definition.Kind);
            Assert.Equal(bound.Mark, (uint)definition.Mark);
            Assert.Equal(bound.Value, definition.Value);
            Assert.Equal(bound.Awards, definition.Awards);
        }
    }

    [Theory]
    [MemberData(nameof(PythonDailyCatalogVectors.Goals), MemberType = typeof(PythonDailyCatalogVectors))]
    public void AllConditionBytesMatchPython(int kind, int first, int second, int third, int? expected) =>
        Assert.Equal(expected, DailyTaskCatalogBinder.Goal((byte)kind, (ushort)first, (ushort)second, (ushort)third));

    [Fact]
    public void MaximumTaskCountIsAcceptedAndNextCountFailsBeforeAllocation()
    {
        byte[] raw = new byte[8 + DailyTaskDataParser.MaxTasks * DailyTaskDataParser.TaskRecordBytes];
        BinaryPrimitives.WriteInt32LittleEndian(raw.AsSpan(4), DailyTaskDataParser.MaxTasks);
        for (int index = 0; index < DailyTaskDataParser.MaxTasks; index++)
            BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(8 + index * DailyTaskDataParser.TaskRecordBytes), (ushort)index);
        var table = DailyTaskDataParser.ParseTasks(raw);
        Assert.Equal(DailyTaskDataParser.MaxTasks, table.Tasks.Length);
        Assert.Equal(new byte[] { 0 }, table.MissingGroupIds);
        BinaryPrimitives.WriteInt32LittleEndian(raw.AsSpan(4), DailyTaskDataParser.MaxTasks + 1);
        Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseTasks(raw));
    }

    [Fact]
    public void AllGroupBytesAreAcceptedButMoreUniqueGroupsCannotExist()
    {
        byte[] raw = new byte[8 + 256 * 3];
        BinaryPrimitives.WriteInt32LittleEndian(raw, 256);
        for (int index = 0; index < 256; index++)
        { raw[4 + index * 3] = 1; raw[5 + index * 3] = 2; raw[6 + index * 3] = (byte)index; }
        Assert.Equal(256, DailyTaskDataParser.ParseTasks(raw).Groups.Length);
        foreach (int count in new[] { 257, 1000 })
        {
            byte[] duplicate = new byte[8 + count * 3];
            BinaryPrimitives.WriteInt32LittleEndian(duplicate, count);
            for (int index = 0; index < count; index++)
            { duplicate[4 + index * 3] = 1; duplicate[5 + index * 3] = 1; duplicate[6 + index * 3] = (byte)index; }
            Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseTasks(duplicate));
        }
    }

    [Fact]
    public void MaximumRewardCountCannotBypassMarkUniqueness()
    {
        byte[] raw = new byte[4 + DailyTaskDataParser.MaxRewards * DailyTaskDataParser.RewardRecordBytes];
        BinaryPrimitives.WriteInt32LittleEndian(raw, DailyTaskDataParser.MaxRewards);
        for (int index = 0; index < DailyTaskDataParser.MaxRewards; index++)
        {
            var row = raw.AsSpan(4 + index * DailyTaskDataParser.RewardRecordBytes);
            BinaryPrimitives.WriteUInt16LittleEndian(row, (ushort)(index + 1)); row[2] = 1;
            BinaryPrimitives.WriteUInt32LittleEndian(row[3..], 1);
            BinaryPrimitives.WriteUInt32LittleEndian(row[7..], (uint)(index % 8 + 1));
        }
        Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseRewards(raw));
    }

    [Fact]
    public void OversizedAndDefaultSpansFailClosed()
    {
        Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseTasks(default));
        Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseRewards(default));
        Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseTasks(new byte[DailyTaskDataParser.MaxTaskBytes + 1]));
        Assert.Throws<CatalogDecodeException>(() => DailyTaskDataParser.ParseRewards(new byte[DailyTaskDataParser.MaxRewardBytes + 1]));
    }

    [Fact]
    public void CallerMutationCannotChangeRetainedDataOrBoundNames()
    {
        byte[] raw = Convert.FromBase64String((string)PythonDailyCatalogVectors.Tasks().First()[1]!);
        var table = DailyTaskDataParser.ParseTasks(raw);
        var rewards = DailyTaskDataParser.ParseRewards(Convert.FromBase64String((string)PythonDailyCatalogVectors.Rewards().First()[1]!));
        var texts = new Dictionary<uint, string?> { [38681] = " original " };
        var items = new HashSet<uint>();
        var preview = DailyTaskCatalogBinder.Bind(table, rewards, texts, items);
        Array.Fill(raw, (byte)255); texts[38681] = "changed"; items.Add(uint.MaxValue);
        Assert.Equal(" original ", Assert.Single(preview.Tasks).Name);
        Assert.Equal((ushort)1, Assert.Single(table.Tasks).Index);
        Assert.Equal((uint)10, preview.ToPlanningDefinitions().Tasks[0].Awards[0].Value);
        var replacement = table.Tasks.SetItem(0, table.Tasks[0] with { Index = 9, ConditionParams = [1, 2, 3] });
        Assert.Equal((ushort)9, replacement[0].Index);
        Assert.Equal((ushort)1, preview.Tasks[0].Data.Index);
        Assert.Equal((ushort)7, preview.Tasks[0].Data.ConditionParams[0]);
    }

    [Fact]
    public void CancellationPrecedesParsingAndBinding()
    {
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        Assert.Throws<OperationCanceledException>(() => DailyTaskDataParser.ParseTasks([], cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => DailyTaskDataParser.ParseRewards([], cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => DailyTaskCatalogBinder.Bind(null!, null!, null!, null!, cancellation.Token));
    }

    [Fact]
    public void MissingTypedMetadataDoesNotCreatePreview()
    {
        var tasks = DailyTaskDataParser.ParseTasks(Convert.FromBase64String((string)PythonDailyCatalogVectors.Tasks().First()[1]!));
        var rewards = DailyTaskDataParser.ParseRewards(Convert.FromBase64String((string)PythonDailyCatalogVectors.Rewards().First()[1]!));
        Assert.Throws<ArgumentNullException>(() => DailyTaskCatalogBinder.Bind(null!, rewards, new Dictionary<uint, string?>(), new HashSet<uint>()));
        Assert.Throws<ArgumentNullException>(() => DailyTaskCatalogBinder.Bind(tasks, null!, new Dictionary<uint, string?>(), new HashSet<uint>()));
        Assert.Throws<ArgumentNullException>(() => DailyTaskCatalogBinder.Bind(tasks, rewards, null!, new HashSet<uint>()));
        Assert.Throws<ArgumentNullException>(() => DailyTaskCatalogBinder.Bind(tasks, rewards, new Dictionary<uint, string?>(), null!));
    }

    private static Dictionary<string, object?> Project(DailyTaskDataRow row) => new()
    {
        ["index"] = row.Index, ["group"] = row.Group, ["id"] = row.Id, ["mission_name_text_id"] = row.MissionNameTextId,
        ["condition_kind"] = row.ConditionKind, ["condition_params"] = row.ConditionParams,
        ["function_kind"] = row.FunctionKind, ["function_arg1"] = row.FunctionArg1, ["function_arg2"] = row.FunctionArg2,
        ["awards"] = row.Awards.Select(award => new { kind = award.Kind, id = award.Id, value = award.Value })
    };
    private static object Project(DailyTaskRewardRow row) => new
    {
        id = row.Id, kind = row.Kind, value = row.Value, mark = row.Mark,
        awards = row.Awards.Select(award => new { kind = award.Kind, id = award.Id, value = award.Value })
    };
    private static void AssertJson(string expected, object actual) =>
        LazyAssert.True(JsonNode.DeepEquals(JsonNode.Parse(expected), JsonSerializer.SerializeToNode(actual)),
            () => $"Expected {expected}; actual {JsonSerializer.Serialize(actual)}");
}
