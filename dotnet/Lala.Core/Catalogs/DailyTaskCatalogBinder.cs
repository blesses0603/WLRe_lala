using System.Collections.Immutable;
using Lala.Core.Automation;

namespace Lala.Core.Catalogs;

public sealed record BoundDailyTaskRow(DailyTaskDataRow Data, string Name, byte Cycle, int? Goal);

/// <summary>
/// A non-authorizing preview of supplied tables and metadata. No token, source verification, activation,
/// or DailyCatalogInput factory is provided. Names and all raw fields remain available for inspection.
/// </summary>
public sealed class DailyTaskCatalogPreview
{
    public ImmutableArray<BoundDailyTaskRow> Tasks { get; }
    public ImmutableArray<DailyTaskRewardRow> Rewards { get; }
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    internal DailyTaskCatalogPreview(ImmutableArray<BoundDailyTaskRow> tasks, ImmutableArray<DailyTaskRewardRow> rewards) =>
        (Tasks, Rewards) = (tasks, rewards);

    /// <summary>
    /// Projects only fields consumed by the existing offline planner. This is not a verified runtime input.
    /// A future activation layer must independently verify the exact sources and same-runtime metadata before
    /// constructing DailyCatalogInput. Do not invent an identity token from parser or binding success.
    /// </summary>
    public DailyTaskCatalog ToPlanningDefinitions() => new(
        Tasks.Select(row => new TaskDefinition(row.Cycle, row.Data.Group, row.Data.Index, row.Data.Id, row.Goal, row.Data.Awards)).ToImmutableArray(),
        Rewards.Select(row => new ChestDefinition(row.Kind, checked((byte)row.Mark), row.Value, row.Awards)).ToImmutableArray());
}

/// <summary>Pure daily_task_catalog.bind_catalog/goal port; caller-supplied metadata is not proof of provenance.</summary>
public static class DailyTaskCatalogBinder
{
    /// <param name="texts">Stable caller-supplied text snapshot; values are preserved, not trimmed.</param>
    /// <param name="itemIds">Stable caller-supplied item identifiers. Existence only, not item usability or source verification.</param>
    public static DailyTaskCatalogPreview Bind(DailyTaskDataTable tasks, DailyTaskRewardTable rewards,
        IReadOnlyDictionary<uint, string?> texts, IReadOnlySet<uint> itemIds, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(tasks);
        ArgumentNullException.ThrowIfNull(rewards);
        ArgumentNullException.ThrowIfNull(texts);
        ArgumentNullException.ThrowIfNull(itemIds);
        var groups = tasks.Groups.ToDictionary(row => row.Group);
        var rows = ImmutableArray.CreateBuilder<BoundDailyTaskRow>();
        var indices = new HashSet<ushort>();
        var slots = new HashSet<(byte Group, byte Id)>();
        foreach (var row in tasks.Tasks)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!groups.TryGetValue(row.Group, out var group))
                throw new CatalogDecodeException("Daily task is missing its group");
            if (group.MissionKind != 1) continue; // Shiny Pass belongs to a different protocol.
            byte cycle = group.RefreshKind;
            if (row.Index == 0 || !indices.Add(row.Index) || !slots.Add((row.Group, row.Id)) ||
                row.Id < 1 || row.Id > (cycle == 1 ? 8 : 12))
                throw new CatalogDecodeException("Invalid or duplicate daily task index or progress slot");
            if (!texts.TryGetValue(row.MissionNameTextId, out string? name) || !HasPythonNonWhitespace(name))
                throw new CatalogDecodeException("Daily task name is missing");
            ValidateItemAwards(row.Awards, itemIds);
            rows.Add(new(row, name!, cycle, Goal(row.ConditionKind, row.ConditionParams[0], row.ConditionParams[1], row.ConditionParams[2])));
        }
        if (rows.Count == 0) throw new CatalogDecodeException("No daily or weekly tasks");
        foreach (var row in rewards.Rewards)
        {
            cancellationToken.ThrowIfCancellationRequested();
            ValidateItemAwards(row.Awards, itemIds);
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(rows.ToImmutable(), rewards.Rewards);
    }

    public static int? Goal(byte conditionKind, ushort first, ushort second, ushort third) => conditionKind switch
    {
        3 or 5 => 1,
        1 or 2 or 4 or 7 or 8 or 12 or 14 or 16 or 18 or 19 or 20 => first,
        6 or 9 or 10 or 11 or 15 or 17 => second,
        13 when first is 1 or 6 => second,
        13 when first is 2 or 3 or 4 or 5 => third,
        _ => null
    };

    private static void ValidateItemAwards(ImmutableArray<TaskAward> awards, IReadOnlySet<uint> itemIds)
    {
        foreach (var award in awards)
            if (award.Kind is 10 or 11 && !itemIds.Contains(award.Id))
                throw new CatalogDecodeException("Daily task or reward chest item is missing");
    }

    // Python str.strip also recognizes the four ASCII information separators.
    private static bool HasPythonNonWhitespace(string? value) => value is not null &&
        value.Any(character => !char.IsWhiteSpace(character) && character is not (>= '\u001c' and <= '\u001f'));
}
