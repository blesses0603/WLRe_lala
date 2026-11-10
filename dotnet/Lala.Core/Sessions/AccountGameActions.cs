using System.Collections.Immutable;
using System.Diagnostics;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private readonly SemaphoreSlim actionLane = new(1, 1);
    private readonly HashSet<string> uncertainActions = [];
    private readonly List<Task> actionRuns = [];
    private GameActionStatus? actionStatus;
    private ImmutableArray<string> actionLog = [];
    private GameSocialCatalog? socialCatalog;
    private Lala.Core.Resources.VerifiedSocialSource? socialSource;
    private ImmutableDictionary<uint, string> socialTexts = ImmutableDictionary<uint, string>.Empty;
    public GameActionStatus? ActionStatus { get { lock (gate) return actionStatus; } }
    public ImmutableArray<string> ActionLog { get { lock (gate) return actionLog; } }
    public bool CanSendGameActions
    {
        get { lock (gate) return uncertainActions.Count == 0 && CurrentCatalogsLocked(out _) && connection.Publication?.State is { Phase: "world_ready", Local.Session.InitialDataComplete: true }; }
    }
    private void ReportAction(GameActionStatus status)
    {
        lock (gate)
        {
            if (actionStatus == status) return;
            actionStatus = status;
            actionLog = actionLog.Add($"{DateTimeOffset.UtcNow.ToOffset(TimeSpan.FromHours(8)):HH:mm:ss}　{status.Label}：{status.Message}");
            if (actionLog.Length > 200) actionLog = actionLog.RemoveRange(0, actionLog.Length - 200);
        }
    }
    /// <summary>One semantic operation through the account-owned, serialized transport.
    /// Resources and live identity are rechecked at the actual write. Pending consumption is
    /// serialized; uncertainty blocks that action family until this runtime is replaced.</summary>
    public Task ExecuteActionAsync(GameAction action, CancellationToken token = default)
        => QueueAction(action, token, false);
    private Task QueueAction(GameAction action, CancellationToken token, bool completeReceiptAfterStop)
    {
        ArgumentNullException.ThrowIfNull(action);
        lock (gate)
        {
            if (retired) throw new ProtocolException("連線已結束，操作不會送出。");
            actionRuns.RemoveAll(task => task.IsCompleted);
            if (actionRuns.Count >= 8) throw new ProtocolException("操作佇列已滿，請稍候。");
            var task = Task.Run(() => ExecuteActionCoreAsync(action, token, completeReceiptAfterStop));
            actionRuns.Add(task); return task;
        }
    }
    private async Task ExecuteActionCoreAsync(GameAction action, CancellationToken token, bool completeReceiptAfterStop)
    {
        ArgumentNullException.ThrowIfNull(action);
        if (!await actionLane.WaitAsync(0, token).ConfigureAwait(false)) throw new ProtocolException("上一筆操作正在等待伺服器確認。");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token);
        Guid attempt = default; GameActionPlan? plan = null; ServiceStateSnapshot? basis = null;
        bool writeAttempted = false;
        try
        {
            Lala.Core.Catalogs.OfflineRuntimeCandidate catalogs;
            lock (gate)
            {
                if (!CurrentCatalogsLocked(out var current) || connection.Publication is not { Phase: AccountReceivePhase.Running } receive)
                    throw new ProtocolException("連線或已驗證資源不可用，請先完成登入。");
                catalogs = current!; attempt = receive.Attempt;
            }
            if (action.Kind == "ark" || action.Kind == "guild" && action.Operation == "donate")
            {
                if (socialSource?.IsCurrent != true || socialCatalog is null)
                {
                    var source = resources.CreateSocialSource() ?? throw new ProtocolException("同版社交資料來源尚未就緒。");
                    ReportAction(new("社交資料", "正在載入同版價格與方舟資料", true));
                    GameSocialCatalog loaded;
                    try { loaded = await source.LoadAsync(linked.Token).ConfigureAwait(false); }
                    catch (Exception error) when (error is IOException or Lala.Core.Resources.ResourceValidationException or Lala.Core.Resources.BundleSourceException or Lala.Core.Resources.UnityTextAssetException)
                    { throw new ProtocolException("同版社交資料尚未載入成功，操作未送出。", error); }
                    lock (gate) { if (!source.IsCurrent) throw new ProtocolException("資料載入期間資源已失效。"); socialSource = source; socialCatalog = loaded; socialTexts = catalogs.Texts.ToImmutableDictionary(); }
                }
            }
            await connection.ApplyCommandAsync(attempt, state =>
            {
                linked.Token.ThrowIfCancellationRequested();
                basis = state;
                plan = ManualGameCommands.Plan(action, state, catalogs, Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency,
                    resources.CurrentResourceKey ?? throw new ProtocolException("啟動資源已失效。"), socialCatalog);
                lock (gate) if (uncertainActions.Count != 0) throw new ProtocolException("先前操作結果不明，請重新登入同步，避免重複消耗。");
                return plan.Begin(state);
            }, linked.Token).ConfigureAwait(false);
            ReportAction(new(plan!.Label, "正在送出", true));
            long lastReceipt = connection.Publication?.Events.LastOrDefault()?.Sequence ?? 0;
            await connection.SendGameAsync(attempt, () =>
            {
                var observed = connection.ReadPublication();
                lock (gate)
                {
                    if (!CurrentCatalogsLocked(out var current) || !ReferenceEquals(current, catalogs) ||
                        observed.Publication is not { Phase: AccountReceivePhase.Running } actual || actual.Attempt != attempt ||
                        actual.State.Player?.RoleId != basis!.Player?.RoleId || actual.State.Player?.Scene != basis.Player?.Scene ||
                        !Equals(ActionStamp(actual.State, plan.Domain), ActionStamp(basis, plan.Domain)))
                        throw new ProtocolException("操作前角色、資源或相關資料已變更，請重新確認。");
                }
                writeAttempted = true;
                return plan.Packet;
            }, linked.Token).ConfigureAwait(false);
            var acknowledgementToken = completeReceiptAfterStop ? stop.Token : linked.Token;
            if (plan.AfterWrite is not null) await connection.ApplyCommandAsync(attempt, plan.AfterWrite, acknowledgementToken).ConfigureAwait(false);
            ReportAction(new(plan.Label, "已送出，等待伺服器確認", true));
            if (!plan.AwaitAcknowledgement) { ReportAction(new(plan.Label, "已送出，結果以伺服器後續回報為準")); return; }
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(acknowledgementToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(20));
            while (true)
            {
                var changed = connection.PublicationChanged;
                var observed = connection.ReadPublication();
                if (observed.Publication is not { Phase: AccountReceivePhase.Running } current || current.Attempt != attempt)
                    throw new ProtocolException("連線已中斷，操作結果尚未確認。");
                lock (gate) if (!CurrentCatalogsLocked(out _)) throw new ProtocolException("資源已失效，操作結果尚未確認。");
                foreach (var receipt in current.Events.Where(e => e.Sequence > lastReceipt)) { plan.ObserveReceipt?.Invoke(receipt); lastReceipt = receipt.Sequence; }
                if (plan.Acknowledged(current.State)) break;
                if (changed is null) throw new ProtocolException("連線已結束。");
                await changed.WaitAsync(timeout.Token).ConfigureAwait(false);
            }
            if (plan.Finish is not null) await connection.ApplyCommandAsync(attempt, plan.Finish, acknowledgementToken).ConfigureAwait(false);
            ReportAction(new(plan.Label, "已收到伺服器狀態更新"));
        }
        catch (Exception error)
        {
            if (writeAttempted && plan is not null) lock (gate) uncertainActions.Add(plan.Domain);
            string message = writeAttempted ? (error is ProtocolException reason ? reason.Message + "　" : "") + "結果未確認，已停止重送；請重新登入同步。" : error is ProtocolException p ? p.Message : "操作未送出，請確認連線與目前資料。";
            ReportAction(new(plan?.Label ?? "操作", message, Uncertain: writeAttempted));
            if (!writeAttempted && basis is not null && plan is not null)
            {
                // A rejected pre-write intent must release only its own local pending evidence.
                try { await connection.ApplyCommandAsync(attempt, state => ClearUnsent(state, plan.Domain, basis), stop.Token).ConfigureAwait(false); }
                catch (Exception) { /* Connection retirement already revokes this attempt. */ }
            }
            throw new ProtocolException(message);
        }
        finally { actionLane.Release(); }
    }
    private async Task DrainGameActionsAsync()
    {
        Task[] pending; lock (gate) pending = actionRuns.ToArray();
        try { await Task.WhenAll(pending).ConfigureAwait(false); } catch (Exception) { /* Each caller retains its operation outcome. */ }
        lock (gate) actionRuns.Clear();
    }
    private static object ActionStamp(ServiceStateSnapshot s, string domain) => domain switch
    {
        "party" => s.Party, "companion" => s.Companions, "attributes" => s.PlayerKnowledge,
        "inventory" or "alchemy" => (s.Bag.Revision, s.Storage.Storage.Revision),
        "tent" => (s.Tent.Scene, s.Tent.Visible, s.Tent.DeployedScene, s.Tent.Inside),
        "battle" => (s.Local.Battle.BattleCount, s.Local.Battle.Round, s.Local.Battle.Active, s.Bag.Revision),
        "rewards" => (s.TimeCube.Count, s.Bag.Revision, s.DailyTasks.Generation),
        "guild" => (s.Guild.Serial, s.GuildActions.Epoch, s.GuildActions.SignState),
        "expedition" => s.Expedition.Revision, "craft" => s.Crafting.Crafting.Revision,
        "instance" or "instance-list" or "instance-reward" => s.Instances,
        "npc" => (s.Local.Battle.Active, s.Player?.Scene), "ark" => (s.Ark.Generation, s.Ark.Starcoin.Revision, s.Ark.Question?.Selected),
        _ => s.PacketCount
    };
    private static ServiceStateSnapshot ClearUnsent(ServiceStateSnapshot s, string domain, ServiceStateSnapshot basis) => domain switch
    {
        "attributes" => CommandState.With(s, points: basis.AttributeAllocation),
        "tent" => CommandState.With(s, tent: s.Tent with { Pending = null, EntryContext = basis.Tent.EntryContext }),
        "rewards" => CommandState.With(s, cube: s.TimeCube with { Pending = null }, daily: s.DailyTasks with { Pending = null }),
        "guild" => CommandState.With(s, guildActions: s.GuildActions with { Pending = null, SignAttempted = basis.GuildActions.SignAttempted }),
        "npc" => CommandState.With(s, local: new(s.Local.Session with { NpcDialogue = basis.Local.Session.NpcDialogue, EventFlow = basis.Local.Session.EventFlow }, s.Local.World, s.Local.Battle)),
        _ => s
    };
}
