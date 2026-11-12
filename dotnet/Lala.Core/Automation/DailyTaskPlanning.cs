using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Automation;

public enum DailyClaimAction { ClaimReady, Task, Chest }
public static partial class DailyTaskService
{
    public static bool HasFlag(ushort flag, int id, bool wide = false) => id >= 1 && id <= (wide ? 16 : 8) && (flag & (1 << (id - 1))) != 0;
    public static bool Received(DailyTaskState state, byte cycle, int id) => cycle == 1
        ? HasFlag(state.Marks.DailyDone, id) : HasFlag(state.Marks.WeeklyDone, id, true);
    public static bool ChestReceived(DailyTaskState state, byte kind, byte mark) => HasFlag(kind switch
    {
        1 => state.Marks.DailyReward, 2 => state.Marks.DailyEventA,
        3 => state.Marks.WeeklyReward, 4 => state.Marks.WeeklyEventA,
        _ => throw new ProtocolException("任務寶箱種類無效")
    }, mark);
    public static ImmutableArray<TaskRow> TaskRows(DailyTaskState state, DailyTaskCatalog catalog)
    {
        ValidateCatalog(catalog);
        return catalog.Tasks.Where(t => t.Group == (t.Cycle == 1 ? state.DailyGroup : state.WeeklyGroup)).Select(t =>
        {
            var counts = t.Cycle == 1 ? state.DailyProgress : state.WeeklyProgress;
            byte? count = state.Ready && t.Id <= counts.Length ? counts[t.Id - 1] : null;
            bool claimed = Received(state, t.Cycle, t.Id);
            return new TaskRow(t, count, claimed, state.Ready && state.GroupsReady && t.Goal > 0 && count >= t.Goal && !claimed);
        }).OrderBy(r => r.Definition.Cycle).ThenBy(r => !r.Eligible).ThenBy(r => r.Definition.Id).ToImmutableArray();
    }
    public static ImmutableArray<ChestRow> ChestRows(DailyTaskState state, DailyTaskCatalog catalog)
    {
        ValidateCatalog(catalog);
        return catalog.Rewards.Where(r => r.Kind is not (2 or 4) || (r.Kind == 2 ? state.DailyEventActive : state.WeeklyEventActive))
            .Select(r =>
            {
                byte cycle = (byte)(r.Kind <= 2 ? 1 : 2); bool claimed = ChestReceived(state, r.Kind, r.Mark);
                return new ChestRow(r, cycle, claimed, state.Ready && state.GroupsReady &&
                    (cycle == 1 ? state.DailyValue : state.WeeklyValue) >= r.Value && !claimed);
            }).OrderBy(r => r.Cycle).ThenBy(r => r.Definition.Kind).ThenBy(r => r.Definition.Value).ToImmutableArray();
    }
    public static ImmutableArray<TaskCandidate> Candidates(DailyTaskState state, DailyTaskCatalog catalog)
    {
        var candidates = ImmutableArray.CreateBuilder<TaskCandidate>();
        foreach (var row in TaskRows(state, catalog).Where(r => r.Eligible))
        {
            var d = row.Definition;
            candidates.Add(new(TaskClaimKind.Task, d.Cycle, d.Index, d.Id, [], d.Awards));
        }
        var chests = ChestRows(state, catalog);
        foreach (byte cycle in new byte[] { 1, 2 })
        {
            var rows = chests.Where(r => r.Cycle == cycle && r.Eligible).ToArray();
            if (rows.Length != 0) candidates.Add(new(TaskClaimKind.Chest, cycle, null, null,
                rows.Select(r => new ChestFlag(r.Definition.Kind, r.Definition.Mark)).ToImmutableArray(),
                rows.SelectMany(r => r.Definition.Awards).ToImmutableArray()));
        }
        return candidates.ToImmutable();
    }
    public static long SlotsNeeded(ImmutableArray<TaskAward> awards)
    {
        long needed = 0; bool seen = false;
        if (awards.IsDefault) throw new ProtocolException("沒有可驗證的獎勵");
        foreach (var award in awards)
        {
            if (award.Kind == 0) continue;
            seen = true;
            if (award.Value == 0) throw new ProtocolException("獎勵數量無效");
            if (award.Kind is 10 or 11) needed = checked(needed + award.Value);
            else if (award.Kind is not (1 or 2 or 6 or 12 or 28 or 29 or 30 or 31))
                throw new ProtocolException("獎勵含未支援種類／隨機福袋，無法確認背包空間");
        }
        if (!seen) throw new ProtocolException("沒有可驗證的獎勵");
        return needed;
    }
    public static TaskFingerprint Fingerprint(DailyTaskState state, TaskCandidate candidate, string? token) =>
        new(state.Generation, state.DailyGroup, state.WeeklyGroup, token, candidate.Kind, candidate.Cycle, candidate.Index,
            string.Join(";", candidate.Flags.Select(f => $"{f.Kind}:{f.Mark}")));
    public static string Guard(DailyTaskState state, AutomationContext context)
    {
        if (!context.WorldReady || !context.InitialDataComplete || context.RoleId is null or 0) return "等待角色與世界同步";
        if (state.RoleId != context.RoleId || !state.Ready || !state.GroupsReady) return "等待完整每日／每週進度與當期群組同步";
        if (state.Uncertain) return "任務領取結果不明，請重新登入同步";
        if (state.Pending is not null) return "等待任務標記、獎勵與背包確認";
        var issue = context.CoordinationProblem(false); if (issue.Length != 0) return issue;
        if (context.BagOperationsBusy(false)) return "等待其他背包操作結束";
        return context.InstanceRewardActive ? "等待副本獎勵確認" : "";
    }
    // This is deliberately private: callers select by verified catalog index/cycle, not fabricated award candidates.
    private static AutomationPlan<DailyTaskState> Begin(DailyTaskState state, AutomationContext context, TaskCandidate candidate, string? token, double now)
    {
        var issue = Guard(state, context); if (issue.Length != 0) throw new ProtocolException(issue);
        var key = Fingerprint(state, candidate, token);
        if (state.Handled.Contains(key)) throw new ProtocolException("本項已要求領取，等待新的伺服器任務狀態");
        long slots = SlotsNeeded(candidate.Awards);
        issue = context.Bag.Problem(slots); if (issue.Length != 0) throw new ProtocolException(issue);
        var expected = ImmutableDictionary.CreateBuilder<int, long>();
        foreach (var award in candidate.Awards.Where(a => a.Kind is 10 or 11))
        {
            if (award.Id is < 1 or > 65535) throw new ProtocolException("任務獎勵物品 ID 無效");
            int id = (int)award.Id; expected[id] = expected.GetValueOrDefault(id) + award.Value;
        }
        var before = context.Bag.ItemTotals();
        if (expected.Count > 0 && before is null) throw new ProtocolException("背包物品數量尚未確認");
        var packet = candidate.Kind == TaskClaimKind.Task
            ? new Packet(124, 1, new PacketWriter().U16(candidate.Index!.Value).Build())
            : new Packet(124, 2, new PacketWriter().U8(candidate.Cycle).Build());
        return new(state with
        {
            Handled = state.Handled.Add(key),
            Pending = new(candidate, token, context.RoleId!.Value, state.Generation, now + 20, false,
                slots, context.Bag.Revision, expected.ToImmutable(), before),
            Status = candidate.Kind == TaskClaimKind.Task ? "已要求領取任務獎勵" : "已要求領取活躍寶箱"
        }, packet);
    }
    public static AutomationPlan<DailyTaskState> Request(DailyTaskState state, AutomationContext context,
        DailyCatalogInput input, DailyClaimAction action, double now, int? index = null, int? cycle = null)
    {
        AutomationChecks.Clock(now); AutomationChecks.Resource(context.ResourceHeld);
        if (!context.WorldAcknowledged) throw new ProtocolException("等待世界初始化確認");
        if (input.Catalog is null) throw new ProtocolException(input.Note);
        ValidateCatalogInput(input);
        if (state.CatalogToken != input.Token) throw new ProtocolException("等待同版任務資料同步");
        IEnumerable<TaskCandidate> candidates = Candidates(state, input.Catalog);
        if (action == DailyClaimAction.Task)
        {
            if (index is null or < 1 or > 65535) throw new ProtocolException("任務索引無效");
            candidates = candidates.Where(c => c.Kind == TaskClaimKind.Task && c.Index == index);
        }
        else if (action == DailyClaimAction.Chest)
        {
            if (cycle is not (1 or 2)) throw new ProtocolException("任務週期無效");
            candidates = candidates.Where(c => c.Kind == TaskClaimKind.Chest && c.Cycle == cycle);
        }
        else if (action != DailyClaimAction.ClaimReady) throw new ProtocolException("未知的每日任務操作");
        var candidate = candidates.FirstOrDefault();
        if (candidate is null) throw new ProtocolException("目前沒有伺服器確認已達標且未領取的項目");
        return Begin(state, context, candidate, input.Token, now);
    }
    public static AutomationPlan<DailyTaskState> Tick(DailyTaskState state, AutomationContext context, DailyCatalogInput input, double now)
    {
        AutomationChecks.Clock(now);
        if (state.Pending is { } p)
        {
            if (p.Role != context.RoleId || p.Token != input.Token || p.Generation != state.Generation)
                state = state with { Pending = null, Uncertain = true, Status = "角色／官方版本／任務週期變動，停止重送" };
            else
            {
                bool marked = p.Candidate.Kind == TaskClaimKind.Task ? Received(state, p.Candidate.Cycle, p.Candidate.Id!.Value)
                    : p.Candidate.Flags.All(f => ChestReceived(state, f.Kind, f.Mark));
                if (marked && p.Notice && ItemsReceived(context.Bag, p))
                    state = state with { Pending = null, Status = "伺服器已確認領取標記與獎勵通知" };
                else if (now >= p.Due)
                    state = state with { Pending = null, Uncertain = true, Status = "每日任務領獎逾時，結果不明；請重新登入同步" };
            }
            return new(state);
        }
        if (context.ResourceHeld) return new(state);
        ValidateCatalogInput(input);
        if (state.CatalogToken is not null && state.CatalogToken != input.Token)
            state = state with { Ready = false, GroupsReady = false, Handled = [], Status = "官方任務資料版本變動，等待重新同步" };
        state = state with { CatalogToken = input.Token, CatalogReady = input.Catalog is not null };
        if (input.Catalog is null) return new(state with { Rows = [], Chests = [], Status = input.Note });
        state = state with { Rows = TaskRows(state, input.Catalog), Chests = ChestRows(state, input.Catalog) };
        // Pending settlement/timeout above still runs while disabled, held, or world confirmation is absent.
        if (!context.WorldAcknowledged || !state.Enabled || !context.AutomationEnabled || context.ResourceHeld) return new(state);
        var issue = Guard(state, context); if (issue.Length != 0) return new(state with { Status = issue });
        string? error = null;
        foreach (var candidate in Candidates(state, input.Catalog))
        {
            if (state.Handled.Contains(Fingerprint(state, candidate, input.Token))) continue;
            try { return Begin(state, context, candidate, input.Token, now); }
            catch (ProtocolException ex) { error ??= ex.Message; }
        }
        return new(state with { Status = error ?? "等待任務進度；已達標項目會自動領獎" });
    }
    private static bool ItemsReceived(RewardBag bag, TaskPending pending)
    {
        if (pending.ItemRewards.Count == 0) return true;
        var after = bag.ItemTotals();
        return pending.ItemBefore is not null && after is not null && bag.Revision > pending.BagRevision &&
            pending.ItemRewards.All(p => after.GetValueOrDefault(p.Key) - pending.ItemBefore.GetValueOrDefault(p.Key) >= p.Value);
    }
    private static void ValidateCatalogInput(DailyCatalogInput input)
    {
        if (input.Catalog is not null && string.IsNullOrWhiteSpace(input.Token))
            throw new ProtocolException("等待同版任務資料同步");
    }
    private static void ValidateCatalog(DailyTaskCatalog catalog)
    {
        if (catalog.Tasks.IsDefaultOrEmpty || catalog.Rewards.IsDefault || catalog.Tasks.Any(t => t.Cycle is not (1 or 2) ||
            t.Index == 0 || t.Id < 1 || t.Id > (t.Cycle == 1 ? 8 : 12) || t.Awards.IsDefault) ||
            catalog.Rewards.Any(r => r.Kind is < 1 or > 4 || r.Mark is < 1 or > 8 || r.Value == 0 || r.Awards.IsDefault) ||
            catalog.Tasks.Select(t => t.Index).Distinct().Count() != catalog.Tasks.Length ||
            catalog.Tasks.Select(t => (t.Group, t.Id)).Distinct().Count() != catalog.Tasks.Length ||
            catalog.Rewards.Select(r => (r.Kind, r.Mark)).Distinct().Count() != catalog.Rewards.Length)
            throw new ProtocolException("每日任務官方資料格式無效");
    }
}
