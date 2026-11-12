using System.Collections.Immutable;
using Lala.Core.Automation;

namespace Lala.Core.Catalogs;

public sealed record DailyTaskGroup(byte MissionKind, byte RefreshKind, byte Group);
public sealed record DailyTaskDataRow(ushort Index, byte Group, byte Id, uint MissionNameTextId,
    byte ConditionKind, ImmutableArray<ushort> ConditionParams, byte FunctionKind, byte FunctionArg1,
    byte FunctionArg2, ImmutableArray<TaskAward> Awards);
public sealed record DailyTaskRewardRow(ushort Id, byte Kind, uint Value, uint Mark, ImmutableArray<TaskAward> Awards);

/// <summary>Immutable layout observations. Missing groups remain visible until binding rejects them.</summary>
public sealed class DailyTaskDataTable
{
    public ImmutableArray<DailyTaskGroup> Groups { get; }
    public ImmutableArray<DailyTaskDataRow> Tasks { get; }
    public ImmutableArray<byte> MissingGroupIds { get; }
    internal DailyTaskDataTable(ImmutableArray<DailyTaskGroup> groups, ImmutableArray<DailyTaskDataRow> tasks,
        ImmutableArray<byte> missingGroupIds) => (Groups, Tasks, MissingGroupIds) = (groups, tasks, missingGroupIds);
}

public sealed class DailyTaskRewardTable
{
    public ImmutableArray<DailyTaskRewardRow> Rewards { get; }
    internal DailyTaskRewardTable(ImmutableArray<DailyTaskRewardRow> rewards) => Rewards = rewards;
}

/// <summary>
/// Bounded offline layout ports of daily_task_1275.parse_daily_tasks and daily_task_catalog.parse_rewards.
/// Version-agnostic syntax only: successful parsing never verifies origin, identity, or runtime authority.
/// </summary>
public static class DailyTaskDataParser
{
    public const int MaxGroups = 1_000;
    public const int MaxTasks = 50_000;
    public const int TaskRecordBytes = 36;
    public const int MaxTaskBytes = 8 + MaxGroups * 3 + MaxTasks * TaskRecordBytes;
    public const int MaxRewards = 1_000;
    public const int RewardRecordBytes = 47;
    public const int MaxRewardBytes = 4 + MaxRewards * RewardRecordBytes;

    public static DailyTaskDataTable ParseTasks(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (raw.Length is < 8 or > MaxTaskBytes) throw new CatalogDecodeException("Invalid daily task table length");
        // A stable byte snapshot prevents caller-owned backing memory from changing between reads.
        var reader = new CatalogReader(raw.ToArray(), cancellationToken);
        int groupCount = reader.Int32();
        if (groupCount is < 0 or > MaxGroups || groupCount * 3 + 4 > reader.Remaining)
            throw new CatalogDecodeException("Invalid daily task group count");
        var groups = ImmutableArray.CreateBuilder<DailyTaskGroup>(groupCount);
        var groupIds = new HashSet<byte>();
        for (int index = 0; index < groupCount; index++)
        {
            var row = new DailyTaskGroup(reader.UInt8(), reader.UInt8(), reader.UInt8());
            if (row.RefreshKind is not (1 or 2) || !groupIds.Add(row.Group))
                throw new CatalogDecodeException("Invalid or duplicate daily task group");
            groups.Add(row);
        }
        int taskCount = reader.Int32();
        if (taskCount is < 0 or > MaxTasks || reader.Remaining != taskCount * TaskRecordBytes)
            throw new CatalogDecodeException("Invalid daily task count or record length");
        var tasks = ImmutableArray.CreateBuilder<DailyTaskDataRow>(taskCount);
        var keys = new HashSet<(byte Group, ushort Index)>();
        var missing = new SortedSet<byte>();
        for (int index = 0; index < taskCount; index++)
        {
            ushort taskIndex = reader.UInt16();
            byte group = reader.UInt8(), id = reader.UInt8();
            uint name = reader.UInt32();
            byte condition = reader.UInt8();
            ImmutableArray<ushort> parameters = [reader.UInt16(), reader.UInt16(), reader.UInt16()];
            byte function = reader.UInt8(), arg1 = reader.UInt8(), arg2 = reader.UInt8();
            var row = new DailyTaskDataRow(taskIndex, group, id, name, condition, parameters,
                function, arg1, arg2, ReadAwards(ref reader, 2));
            if (!keys.Add((group, taskIndex))) throw new CatalogDecodeException("Duplicate daily task index");
            if (!groupIds.Contains(group)) missing.Add(group);
            tasks.Add(row);
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(groups.MoveToImmutable(), tasks.MoveToImmutable(), missing.ToImmutableArray());
    }

    public static DailyTaskRewardTable ParseRewards(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (raw.Length is < 4 or > MaxRewardBytes) throw new CatalogDecodeException("Invalid daily reward table length");
        var reader = new CatalogReader(raw.ToArray(), cancellationToken);
        int count = reader.Int32();
        if (count is < 1 or > MaxRewards || reader.Remaining != count * RewardRecordBytes)
            throw new CatalogDecodeException("Invalid daily reward count or record length");
        var rewards = ImmutableArray.CreateBuilder<DailyTaskRewardRow>(count);
        var ids = new HashSet<(byte Kind, ushort Id)>();
        var marks = new HashSet<(byte Kind, uint Mark)>();
        for (int index = 0; index < count; index++)
        {
            var row = new DailyTaskRewardRow(reader.UInt16(), reader.UInt8(), reader.UInt32(), reader.UInt32(), ReadAwards(ref reader, 4));
            if (row.Id == 0 || row.Kind is < 1 or > 4 || row.Mark is < 1 or > 8 || row.Value == 0 ||
                !ids.Add((row.Kind, row.Id)) || !marks.Add((row.Kind, row.Mark)))
                throw new CatalogDecodeException("Invalid or duplicate daily reward index or mark");
            rewards.Add(row);
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(rewards.MoveToImmutable());
    }

    private static ImmutableArray<TaskAward> ReadAwards(ref CatalogReader reader, int count)
    {
        var awards = ImmutableArray.CreateBuilder<TaskAward>(count);
        for (int index = 0; index < count; index++) awards.Add(new(reader.UInt8(), reader.UInt32(), reader.UInt32()));
        return awards.MoveToImmutable();
    }
}
