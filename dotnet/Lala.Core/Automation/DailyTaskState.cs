using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Automation;

public enum TaskClaimKind { Task, Chest }
public sealed record ChestFlag(byte Kind, byte Mark);
public sealed record TaskDefinition(byte Cycle, byte Group, ushort Index, byte Id, int? Goal, ImmutableArray<TaskAward> Awards);
public sealed record ChestDefinition(byte Kind, byte Mark, uint Value, ImmutableArray<TaskAward> Awards);
public sealed record TaskRow(TaskDefinition Definition, byte? Progress, bool Received, bool Eligible);
public sealed record ChestRow(ChestDefinition Definition, byte Cycle, bool Received, bool Eligible);
/// <summary>Explicit same-runtime catalog input. Extraction, identity verification and activation remain caller responsibilities.</summary>
public sealed record DailyTaskCatalog(ImmutableArray<TaskDefinition> Tasks, ImmutableArray<ChestDefinition> Rewards);
public sealed record DailyCatalogInput(DailyTaskCatalog? Catalog, string? Token, string Note = "等待官方每日任務 Runtime");
public sealed record TaskCandidate(TaskClaimKind Kind, byte Cycle, ushort? Index, byte? Id,
    ImmutableArray<ChestFlag> Flags, ImmutableArray<TaskAward> Awards);
public sealed record TaskFingerprint(long Generation, byte? DailyGroup, byte? WeeklyGroup,
    string? Token, TaskClaimKind Kind, byte Cycle, ushort? Index, string Flags);
public sealed record TaskPending(TaskCandidate Candidate, string? Token, uint Role, long Generation,
    double Due, bool Notice, long Slots, long BagRevision,
    ImmutableDictionary<int, long> ItemRewards, ImmutableDictionary<int, long>? ItemBefore);
public sealed record DailyTaskState
{
    public bool Enabled { get; init; } = true;
    public TaskPending? Pending { get; init; }
    public bool Uncertain { get; init; }
    public ImmutableHashSet<TaskFingerprint> Handled { get; init; } = [];
    public uint? RoleId { get; init; }
    public long Generation { get; init; }
    public long Revision { get; init; }
    public string? CatalogToken { get; init; }
    public bool CatalogReady { get; init; }
    public ImmutableArray<TaskRow> Rows { get; init; } = [];
    public ImmutableArray<ChestRow> Chests { get; init; } = [];
    public bool GroupsAhead { get; init; }
    public bool AwaitingGroups { get; init; }
    public string Status { get; init; } = "等待每日／每週任務同步";
    public bool Ready { get; init; }
    public bool GroupsReady { get; init; }
    public byte? DailyGroup { get; init; }
    public byte? WeeklyGroup { get; init; }
    // Python defaults use None for these two values, not zero.
    public byte? DailyValue { get; init; }
    public byte? WeeklyValue { get; init; }
    public TaskMarks Marks { get; init; } = new(0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    public ImmutableArray<byte> DailyProgress { get; init; } = [];
    public ImmutableArray<byte> WeeklyProgress { get; init; } = [];
    public bool DailyEventActive { get; init; }
    public bool WeeklyEventActive { get; init; }
    public string LastNotice { get; init; } = "";
}

public static partial class DailyTaskService
{
    public static DailyTaskState RoleListAvailable() => new();
    public static DailyTaskState WorldPlayer(DailyTaskState state, uint role) =>
        (state.RoleId is not null && state.RoleId != role ? new DailyTaskState() : state) with { RoleId = role };
    private static DailyTaskState SetMarks(DailyTaskState state, TaskMarks marks) => state with
        { Marks = marks, DailyValue = marks.DailyValue, WeeklyValue = marks.WeeklyValue };
    public static DailyTaskState Apply(DailyTaskState state, DailyTaskEvent value)
    {
        state = state with { Revision = checked(state.Revision + 1) };
        switch (value)
        {
            case TaskSnapshot s:
                if (s.DailyProgress.IsDefault || s.DailyProgress.Length != 8 || s.WeeklyProgress.IsDefault || s.WeeklyProgress.Length != 12)
                    throw new ProtocolException("每日任務進度長度無效");
                if (state.Ready) state = state with
                { Uncertain = state.Uncertain || state.Pending is not null, Pending = null, Handled = [], Generation = checked(state.Generation + 1) };
                return SetMarks(state, s.Marks) with
                {
                    GroupsReady = state.GroupsAhead, AwaitingGroups = !state.GroupsAhead,
                    DailyProgress = s.DailyProgress, WeeklyProgress = s.WeeklyProgress,
                    DailyEventActive = s.DailyEventActive, WeeklyEventActive = s.WeeklyEventActive,
                    Ready = true, GroupsAhead = false, Status = "每日／每週進度已由伺服器同步"
                };
            case TaskGroups g:
                bool changed = state.DailyGroup is not null && (state.DailyGroup != g.DailyGroup || state.WeeklyGroup != g.WeeklyGroup);
                bool fresh = state.Ready && state.AwaitingGroups;
                if (!fresh && (changed || state.Ready)) state = state with
                { Uncertain = state.Uncertain || state.Pending is not null, Ready = false, Pending = null, Handled = [], Generation = checked(state.Generation + 1) };
                return state with { DailyGroup = g.DailyGroup, WeeklyGroup = g.WeeklyGroup, GroupsReady = true, GroupsAhead = !fresh, AwaitingGroups = false };
            case TaskMarksChanged m when state.Ready:
                var a = state.Marks; var b = m.Marks;
                bool regressed = (a.DailyDone & ~b.DailyDone) != 0 || (a.WeeklyDone & ~b.WeeklyDone) != 0 ||
                    (a.DailyReward & ~b.DailyReward) != 0 || (a.WeeklyReward & ~b.WeeklyReward) != 0 ||
                    (a.DailyEventA & ~b.DailyEventA) != 0 || (a.WeeklyEventA & ~b.WeeklyEventA) != 0;
                if (regressed || b.DailyValue < state.DailyValue || b.WeeklyValue < state.WeeklyValue)
                    state = state with
                    {
                        Uncertain = state.Uncertain || state.Pending is not null, Ready = false, GroupsReady = false,
                        Pending = null, Handled = [], Generation = checked(state.Generation + 1),
                        Status = "任務週期已變動，等待完整快照與群組同步"
                    };
                return SetMarks(state, m.Marks);
            case TaskProgress p:
                if (p.Cycle is not (1 or 2) || p.TaskId < 1 || p.TaskId > (p.Cycle == 1 ? 8 : 12))
                    throw new ProtocolException("每日任務進度種類或格位無效");
                if (!state.Ready) return state;
                var progress = p.Cycle == 1 ? state.DailyProgress : state.WeeklyProgress;
                if (p.Count < progress[p.TaskId - 1]) return state with
                {
                    Uncertain = state.Uncertain || state.Pending is not null, Ready = false, GroupsReady = false,
                    GroupsAhead = false, AwaitingGroups = false, Pending = null, Handled = [], Generation = checked(state.Generation + 1),
                    Status = "進度已重置，等待完整任務同步"
                };
                return p.Cycle == 1 ? state with { DailyProgress = progress.SetItem(p.TaskId - 1, p.Count) }
                    : state with { WeeklyProgress = progress.SetItem(p.TaskId - 1, p.Count) };
            case TaskError e:
                return state with { Enabled = false, Pending = null, Status = "伺服器拒絕，已停止自動領獎：" + e.Message };
            case TaskRewardNotice n when state.Pending is { } p && n.Kind == (p.Candidate.Kind == TaskClaimKind.Task ? 1 : 2):
                return state with { Pending = p with { Notice = true } };
            case TaskUnknownUpdate:
                return state with
                {
                    Uncertain = state.Uncertain || state.Pending is not null, Ready = false, GroupsReady = false,
                    GroupsAhead = false, AwaitingGroups = false, Pending = null, Handled = [], Generation = checked(state.Generation + 1),
                    Status = "未知的任務更新格式，等待重新登入同步"
                };
            default: return state;
        }
    }
    public static DailyTaskState SetAutomatic(DailyTaskState state, bool enabled, bool resourceHeld)
    {
        AutomationChecks.Resource(resourceHeld, !enabled);
        return state with { Enabled = enabled, Status = enabled ? "已啟用自動領獎" : "已暫停每日任務自動領獎" };
    }
    public static DailyTaskState Disconnect(DailyTaskState state) => state with
    {
        Enabled = false, Ready = false, GroupsReady = false, Uncertain = state.Uncertain || state.Pending is not null,
        Pending = null, Status = "連線結束，每日任務自動領獎已停止"
    };
}
