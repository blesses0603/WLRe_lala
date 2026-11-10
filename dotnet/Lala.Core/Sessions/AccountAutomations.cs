using System.Collections.Immutable;
using System.Diagnostics;
using Lala.Core.Battle;
using Lala.Core.Expedition;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private sealed class AutomaticStopException(string message) : Exception(message);
    private sealed record AutomaticRun(CancellationTokenSource Stop, Task Task);
    private readonly Dictionary<string, AutomaticRun> automaticRuns = [];
    private ImmutableDictionary<string, GameAutomationStatus> automationStatus = ImmutableDictionary<string, GameAutomationStatus>.Empty;
    public ImmutableDictionary<string, GameAutomationStatus> Automations { get { lock (gate) return automationStatus; } }
    private void AutomationMessage(string kind, bool enabled, string message)
    { lock (gate) automationStatus = automationStatus.SetItem(kind, new(kind, enabled, message)); }

    public async Task SetAutomationAsync(string kind, bool enabled, GameAutomationSettings? settings = null)
    {
        if (kind is not ("battle" or "expedition" or "daily" or "roaming" or "alchemy" or "craft" or "ark" or "guild")) throw new ProtocolException("未知的自動功能。");
        AutomaticRun? previous;
        lock (gate) automaticRuns.TryGetValue(kind, out previous);
        if (previous is not null)
        {
            await previous.Stop.CancelAsync().ConfigureAwait(false);
            await previous.Task.ConfigureAwait(false);
            lock (gate) { if (automaticRuns.GetValueOrDefault(kind) == previous) automaticRuns.Remove(kind); }
            previous.Stop.Dispose();
        }
        if (!enabled) { AutomationMessage(kind, false, "已停止接續；已送出的操作仍等待伺服器結果。"); return; }
        settings ??= new();
        if (settings.ExpeditionMinHours is < 0 or > 24 || settings.ExpeditionMinFaith is < 1 or > 100 || settings.ExpeditionMinSuccess is < 0 or > 100 ||
            settings.RequiredParty.IsDefault || settings.RequiredParty.Length > 4 || settings.RequiredParty.Distinct().Count() != settings.RequiredParty.Length)
            throw new ProtocolException("自動功能設定超出有效範圍。");
        lock (gate)
        {
            if (retired || !CanSendGameActions) throw new ProtocolException("請先完成登入與資源準備。");
            if (kind == "alchemy")
            {
                var publication = PublicationSnapshot.Publication!;
                _ = ManualGameCommands.Plan(new("alchemy", settings.AlchemyMode, Count: settings.AlchemyRuns, Ingredients: settings.AlchemyMaterials),
                    publication.Receive.State, publication.Catalogs!, Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency, resources.CurrentResourceKey!);
            }
            if (automaticRuns.ContainsKey(kind)) throw new ProtocolException("此自動功能已在切換中。");
            var cancellation = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
            automaticRuns[kind] = new(cancellation, Task.Run(() => RunAutomaticAsync(kind, settings, cancellation.Token)));
        }
    }
    private async Task RunAutomaticAsync(string kind, GameAutomationSettings settings, CancellationToken token)
    {
        AutomationMessage(kind, true, "已啟用，等待可操作的伺服器狀態。");
        try
        {
            using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(250));
            int alchemyCompleted = 0;
            while (await timer.WaitForNextTickAsync(token).ConfigureAwait(false))
            {
                if (!CanSendGameActions) { AutomationMessage(kind, false, "連線或資源已失效，自動功能已停止。"); return; }
                if (ActionStatus?.Pending == true || actionLane.CurrentCount == 0) continue;
                try
                {
                    if (kind == "roaming") { await RoamOnceAsync(token).ConfigureAwait(false); AutomationMessage(kind, true, NavigationStatus.Message); continue; }
                    var action = kind == "alchemy" ? new GameAction("alchemy", settings.AlchemyMode, Ingredients: settings.AlchemyMaterials) : NextAutomaticAction(kind, settings, token);
                    if (action is null) continue;
                    await QueueAction(action, token, true).ConfigureAwait(false);
                    if (kind == "alchemy" && ++alchemyCompleted >= settings.AlchemyRuns) { AutomationMessage(kind, false, $"已確認完成 {alchemyCompleted} 次煉金。"); return; }
                    AutomationMessage(kind, true, ActionStatus?.Message ?? "等待下一筆可操作資料。");
                }
                catch (ProtocolException error)
                {
                    if (ActionStatus?.Uncertain == true) { AutomationMessage(kind, false, "操作結果不明，已停止自動接續；請重新登入同步。"); return; }
                    AutomationMessage(kind, true, error.Message);
                }
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (AutomaticStopException error) { AutomationMessage(kind, false, error.Message); }
        catch (Lala.Core.World.NavigationException error) { AutomationMessage(kind, false, error.Message); }
        catch (Exception) { AutomationMessage(kind, false, "自動功能遇到錯誤，已停止。"); return; }
        finally { if (token.IsCancellationRequested) AutomationMessage(kind, false, "已停止自動接續。"); }
    }
    private GameAction? NextAutomaticAction(string kind, GameAutomationSettings settings, CancellationToken token)
    {
        var observed = PublicationSnapshot;
        if (observed.Publication is not {} publication || publication.Catalogs is not {} c) return null;
        var s = publication.Receive.State;
        if (kind == "battle")
        {
            var battle = s.Local.Battle;
            if (battle.Active != true && s.Local.Session.EventFlow is { Blocked: true, AwaitingResponse: false, LastSource: "S20-7" or "S20-10" or "S20-11" or "S20-13" or "S20-14" or "S20-15" or "S20-16" or "S20-17" } && !s.Local.Session.NpcDialogue.Active)
                return new("event", "continue");
            if (battle.Active != true || battle.Round is not > 0) return null;
            if (battle.Units.Any(u => u.Hp == 0 && (settings.StopOnPlayerDeath && u.Layout.Pid == s.Player!.RoleId || settings.StopOnPartnerDeath && u.Layout.MasterId == s.Player!.RoleId)))
                throw new AutomaticStopException("角色或夥伴已陣亡，依設定停止 AI。");
            var team = s.Party.OwnTeam(s.Player!.RoleId);
            bool missing = settings.RequiredParty.Any(id => id != s.Player.RoleId && team?.Members.Contains(id) != true);
            foreach (var unit in battle.Units.Where(u => (u.Layout.Pid == s.Player.RoleId || u.Layout.MasterId == s.Player.RoleId) && u.Hp > 0 && !u.Exited))
            {
                if (battle.CommandAt(unit.Slot) is not null) continue;
                var profile = unit.Layout.Pid == s.Player.RoleId ? settings.Player : settings.Partner;
                return new("battle", missing ? "escape" : "auto", unit.Layout.Pid, battle.Round.Value,
                    X: unit.Layout.Col, Y: unit.Layout.Row, Scene: s.Player.Scene, BattleProfile: profile);
            }
            return null;
        }
        if (s.Local.Battle.Active == true || s.Local.Session.EventFlow.Blocked || s.Activities.Count != 0) return null;
        if (kind == "ark") return NextArkAction(s, settings);
        if (kind == "craft")
        {
            var craft = s.Crafting.Crafting;
            if (!craft.Ready || craft.Uncertain || craft.Pending is not null) return null;
            if (craft.Running && craft.Queue.TryGetValue(craft.Active, out var row))
                return Lala.Core.Inventory.CraftingReducer.Elapsed(craft, row, Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency) >= Math.Max(1, row.BaseTime) ? new("craft", "complete") : null;
            if (craft.Queue.Count == 0) throw new AutomaticStopException("排程已全部完成。");
            return new("craft", "start");
        }
        if (kind is "daily" or "guild")
        {
            if (settings.DailyCube && s.TimeCube.Ready && s.TimeCube.Count > 0 && s.TimeCube.Pending is null && !s.TimeCube.Uncertain) return new("cube");
            if (settings.DailyRewards && c.OptionalDailyCatalog is {} daily && s.DailyTasks.Ready && s.DailyTasks.GroupsReady && s.DailyTasks.Pending is null && !s.DailyTasks.Uncertain &&
                Lala.Core.Automation.DailyTaskService.Candidates(s.DailyTasks, daily.ToPlanningDefinitions()).Any()) return new("daily", "ready");
            if (settings.GuildSign && s.GuildActions.SignState == 1 && !s.GuildActions.SignAttempted && !s.GuildActions.Uncertain) return new("guild", "sign");
            if (settings.GuildDonate && s.GuildActions.Remaining is > 0 && s.GuildActions.Allow && s.GuildActions.Pending is null && !s.GuildActions.Uncertain)
                return new("guild", "donate", Index: settings.DonationSellId, Count: settings.DonationTarget, Values: ImmutableDictionary<string, int>.Empty.Add("budget", settings.GoldBudget));
            return null;
        }
        var e = s.Expedition;
        if (!e.Ready || !e.OutpostReady || e.Uncertain || e.Pending is not null || e.Level is not {} level || !c.Expedition.Levels.TryGetValue(level, out var lv)) return null;
        double now = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
        if (settings.ExpeditionAutoClaim)
        {
            var completed = e.Teams.Values.FirstOrDefault(t => t.Quest != 0 && t.Due is {} due && due <= now);
            if (completed is not null) return new("expedition", "claim", Index: completed.Index);
        }
        if (!e.Teams.Values.Any(t => t.Index <= lv.Teams && t.Quest == 0)) return null;
        var occupied = e.Teams.Values.Where(t => t.Quest != 0).SelectMany(t => t.Members).ToHashSet();
        if (settings.RestoreItem is {} restore)
        {
            var low = e.Roles.Values.Where(r => r.State == 0 && !occupied.Contains(r.NpcId) && r.Faith < settings.ExpeditionMinFaith).OrderBy(r => r.Index).FirstOrDefault();
            if (low is not null)
            {
                var stock = s.Bag.Items.Values.Where(i => !i.OriginalRecord.Locked && i.OriginalRecord.LimitedTime == 0 && i.OriginalRecord.AvailableTime == 0 && (restore == 0 || i.ItemId == restore))
                    .GroupBy(i => i.ItemId).Select(g => new { Id = g.Key, Count = g.Aggregate(System.Numerics.BigInteger.Zero, (sum, i) => sum + Lala.Core.Inventory.BagReceiveReducer.Available(s.Bag, i.Index)), Gain = ExpeditionTaskInspection.FaithGain(c.Items.GetValueOrDefault(g.Key)) ?? 0 })
                    .Where(i => i.Gain > 0 && i.Count * i.Gain >= settings.ExpeditionMinFaith - low.Faith).OrderBy(i => (settings.ExpeditionMinFaith - low.Faith + i.Gain - 1) / i.Gain).ThenBy(i => i.Id).FirstOrDefault();
                if (stock is not null) return new("expedition", "restore", stock.Id, low.Index, settings.ExpeditionMinFaith);
            }
        }
        var roles = e.Roles.Values.Where(r => r.State == 0 && !occupied.Contains(r.NpcId) && r.Faith >= settings.ExpeditionMinFaith)
            .Select(r => new ExpeditionRole(r.Index, r.NpcId, r.Faith, r.Stats.Level, r.Stats.Degree, r.Stats.Potential, r.Stats.Str, r.Stats.Con, r.Stats.Int, r.Stats.Wis, r.Stats.Agi)).Take(64).ToArray();
        var npcs = c.Npcs.ToDictionary(p => (int)p.Key, p => new ExpeditionNpc(p.Value.Element, p.Value.Kind, p.Value.Original));
        var areas = e.Teams.Values.Where(t => t.Quest != 0).Select(t => c.Expedition.Tasks.GetValueOrDefault(t.Quest)?.Area).ToHashSet();
        foreach (var task in e.Quests.Values.Distinct().Select(id => c.Expedition.Tasks.GetValueOrDefault(id)).Where(t => t is not null).OrderByDescending(t => t!.Minutes))
        {
            token.ThrowIfCancellationRequested();
            if (task!.Difficulty > lv.Difficulty || areas.Contains(task.Area) || ExpeditionTaskInspection.DurationSeconds(task.Minutes, lv.Reduction) <= settings.ExpeditionMinHours * 3600) continue;
            var condition = new ExpeditionCondition(task.Condition[0], task.Condition[1], task.Condition[2]);
            var recommendations = task.Recommendations.Select(r => new Lala.Core.Expedition.ExpeditionRecommendation(new(r.Condition[0], r.Condition[1], r.Condition[2]), r.Bonus)).ToArray();
            var selected = ExpeditionTeams.ChooseMembers(condition, recommendations, task.SuccessRate, task.FaithCost, roles, settings.ExpeditionMinFaith, npcs, token);
            if (selected.Count == 0) continue;
            var assessment = InspectExpeditionTask(task.Id, [..selected.Select(i => (byte)i)]);
            if (assessment.ConditionMet != true || assessment.Success is not { Complete: true } rate || rate.Percent < settings.ExpeditionMinSuccess) continue;
            return new("expedition", "dispatch", task.Id, Values: selected.Select((slot, i) => KeyValuePair.Create(i.ToString(), slot)).ToImmutableDictionary());
        }
        return null;
    }
    private async Task DrainAutomationsAsync()
    {
        AutomaticRun[] pending; lock (gate) pending = automaticRuns.Values.ToArray();
        await Task.WhenAll(pending.Select(run => run.Task)).ConfigureAwait(false);
        foreach (var run in pending) run.Stop.Dispose();
        lock (gate) automaticRuns.Clear();
    }
    private GameAction? NextArkAction(Lala.Core.State.ServiceStateSnapshot s, GameAutomationSettings settings)
    {
        var ark = s.Ark;
        if (!ark.Ready || ark.Uncertain) return null;
        if (ark.Question is { Selected: null } q && ark.Pending?.Kind == "question")
        {
            var answer = Lala.Core.Social.Ark.ArkArithmeticSolver.Solve(q);
            if (answer is {} id) return new("ark", "answer", Index: q.Options.IndexOf(id) + 1);
            AutomationMessage("ark", true, "題目已載入；等待人工選答。"); return null;
        }
        if (ark.Pending is not null) return null;
        if (settings.ArkQuestions && ark.EventsReady)
        {
            var question = ark.Events.Values.FirstOrDefault(e => !e.Main && e.Id > 0 && e.Kind == 3 && e.Planet <= Math.Min(ark.Planet, (byte)20));
            if (question is not null) return new("ark", "question", question.Id, question.Index);
        }
        if (settings.ArkDispatch && ark.Ship is { Total: 0 } && ark.Starcoin is { Ready: true, Reliable: true })
        {
            var agent = ark.Agents.Values.Where(a => a.Planet == 0).OrderBy(a => a.Index).FirstOrDefault();
            if (agent is not null) return new("ark", "dispatch", Index: agent.Index, Count: settings.ArkHours, Values: ImmutableDictionary<string, int>.Empty.Add("budget", settings.StarBudget));
        }
        return null;
    }
}
