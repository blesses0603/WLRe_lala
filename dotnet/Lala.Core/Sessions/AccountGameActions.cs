using System.Collections.Immutable;
using System.Diagnostics;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private readonly SemaphoreSlim actionLane = new(1, 1);
    private readonly EventContinuationGuard eventContinuation=new();
    private readonly BattleSubmissionGuard battleSubmissions=new();
    private readonly HashSet<string> uncertainActions = [];
    private readonly List<Task> actionRuns = [];
    private GameActionStatus? actionStatus;
    private readonly GameActionHistory actionHistory = new();
    private GameSocialCatalog? socialCatalog;
    private Lala.Core.Resources.VerifiedSocialSource? socialSource;
    private ImmutableDictionary<uint, string> socialTexts = ImmutableDictionary<uint, string>.Empty;
    public GameActionStatus? ActionStatus { get { lock (gate) return actionStatus; } }
    public ImmutableArray<string> ActionLog { get { lock (gate) return connection.Publication?.State.Player?.RoleId is {} role&&role!=actionHistory.Role?[]:actionHistory.Lines; } }
    public bool CanSendGameActions
    {
        get { lock (gate) return uncertainActions.Count == 0 && CurrentCatalogsLocked(out _) && connection.Publication?.State is { Phase: "world_ready", Player.RoleId:>0, Local.Session.InitialDataComplete: true }; }
    }
    private void ReportAction(GameActionStatus status, object operation, uint? forRole=null, bool background=false)
    {
        lock (gate)
        {
            var currentRole=connection.Publication?.State.Player?.RoleId;
            var role=forRole??currentRole;
            if (!background) actionStatus = status;
            // Late completion of an old role cannot erase the new role's history.
            if (currentRole is not null && role != currentRole) return;
            actionHistory.Record(operation, role, status);
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
    private async Task ExecuteActionCoreAsync(GameAction action, CancellationToken token, bool completeReceiptAfterStop, ServerEventSync? sync=null)
    {
        ArgumentNullException.ThrowIfNull(action);
        // Protocol event replies must not deadlock behind a portal operation waiting
        // for that event to finish. Only this private, owned worker bypasses the ACK
        // lane; physical writes still use the account transport's protocol gate.
        bool ownsLane = sync is null;
        if (sync is not null && action is not { Kind: "event", Operation: "continue" or "post_battle" }) throw new InvalidOperationException();
        if (ownsLane && !await actionLane.WaitAsync(0, token).ConfigureAwait(false)) throw new ProtocolException("上一筆操作正在等待伺服器確認。");
        object operation = new();
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token);
        Guid attempt = default; GameActionPlan? plan = null; ServiceStateSnapshot? basis = null;
        bool writeAttempted = false;
        GameReceiptWatch? receiptWatch=null;IDisposable? receiptLease=null;
        try
        {
            Lala.Core.Catalogs.OfflineRuntimeCandidate catalogs;
            lock (gate)
            {
                if (!CurrentCatalogsLocked(out var current) || connection.Publication is not { Phase: AccountReceivePhase.Running } receive)
                    throw new ProtocolException("連線或已驗證資源不可用，請先完成登入。");
                if(sync is not null && (receive.Attempt!=sync.Attempt || receive.State.Player?.RoleId!=sync.Role || receive.State.Player?.Scene!=sync.Scene))
                    throw new ProtocolException("事件所屬角色、連線或場景已變更。");
                catalogs = current!; attempt = receive.Attempt;
            }
            if (action.Kind == "ark" || action.Kind == "guild" && action.Operation == "donate")
            {
                if (socialSource?.IsCurrent != true || socialCatalog is null)
                {
                    var source = resources.CreateSocialSource() ?? throw new ProtocolException("同版社交資料來源尚未就緒。");
                    ReportAction(new("社交資料", "正在載入同版價格與方舟資料", true),operation);
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
                if(sync is not null && (state.Player?.RoleId!=sync.Role || state.Player?.Scene!=sync.Scene))
                    throw new ProtocolException("事件所屬角色或場景已變更。");
                basis = state;
                plan = ManualGameCommands.Plan(action, state, catalogs, Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency,
                    resources.CurrentResourceKey ?? throw new ProtocolException("啟動資源已失效。"), socialCatalog);
                lock (gate) if (uncertainActions.Count != 0) throw new ProtocolException("先前操作結果不明，請重新登入同步，避免重複消耗。");
                return plan.Begin(state);
            }, linked.Token).ConfigureAwait(false);
            if (plan is null) throw new ProtocolException("操作規劃尚未完成。");
            if (sync is null) ReportAction(new(plan.Label, "正在送出", true),operation,basis!.Player?.RoleId);
            if(plan.ObserveReceipt is not null){receiptWatch=new(plan);receiptLease=connection.WatchReceipts(attempt,receiptWatch);}
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
                    // Ignore receipts that arrived while this command was waiting for
                    // the owned transport lane; only observe the write boundary onward.
                    lastReceipt = actual.Events.LastOrDefault()?.Sequence ?? 0;
                    if(action.Kind is "battle" or "event" && !connection.IsBatchDrained(actual.Attempt))
                        throw new ProtocolException("正在接收本批資料，待整批完成後再下令。");
                    receiptWatch?.Arm(lastReceipt);
                    if(action.Kind=="battle")battleSubmissions.Admit(actual.State,action,actual.Attempt);
                    if(action.Kind=="event")
                    {
                        if(action.Operation=="post_battle")eventContinuation.AdmitPostBattle(actual.State,action,actual.Attempt);
                        else
                        {
                        long? expected=null;
                        if(action.Key is not null)
                        {
                            if(!long.TryParse(action.Key,System.Globalization.NumberStyles.None,System.Globalization.CultureInfo.InvariantCulture,out var value))throw new ProtocolException("事件接續許可識別無效。");
                            expected=value;
                        }
                        eventContinuation.Admit(actual.State,actual.Events,expected,actual.Attempt);
                        }
                    }
                }
                writeAttempted = true;
                return plan.Packet;
            }, linked.Token).ConfigureAwait(false);
            if (sync is not null) { sync.Sent++; ReportEventSync(sync, $"已接續 {sync.Sent} 步，等待伺服器確認", pending:true); }
            var acknowledgementToken = completeReceiptAfterStop ? stop.Token : linked.Token;
            if (plan.ContinueNpcChoice) await ContinueNpcChoiceAsync(attempt, action, basis!, catalogs, acknowledgementToken).ConfigureAwait(false);
            if (plan.AfterWrite is not null) await connection.ApplyCommandAsync(attempt, plan.AfterWrite, acknowledgementToken).ConfigureAwait(false);
            if (sync is null) ReportAction(new(plan.Label, "已送出，等待伺服器確認", true),operation,basis!.Player?.RoleId);
            if (!plan.AwaitAcknowledgement) { ReportAction(new(plan.Label, "已送出，結果以伺服器後續回報為準"),operation,basis!.Player?.RoleId); return; }
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(acknowledgementToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(20));
            while (true)
            {
                var changed = connection.PublicationChanged;
                var observed = connection.ReadPublication();
                if (observed.Publication is not { Phase: AccountReceivePhase.Running } current || current.Attempt != attempt)
                    throw new ProtocolException("連線已中斷，操作結果尚未確認。");
                if(current.State.Player?.RoleId!=basis!.Player?.RoleId)
                    throw new ProtocolException("角色已改變，不會把另一角色的資料當作本次操作結果。");
                lock (gate) if (!CurrentCatalogsLocked(out _)) throw new ProtocolException("資源已失效，操作結果尚未確認。");
                if (receiptWatch?.Acknowledged(current.State) ?? plan.Acknowledged(current.State)) break;
                if (changed is null) throw new ProtocolException("連線已結束。");
                await changed.WaitAsync(timeout.Token).ConfigureAwait(false);
            }
            if (plan.Finish is not null) await connection.ApplyCommandAsync(attempt, plan.Finish, acknowledgementToken).ConfigureAwait(false);
            if (sync is null) ReportAction(new(plan.Label, "已收到伺服器狀態更新"),operation,basis!.Player?.RoleId);
            else ReportEventSync(sync, $"已接續 {sync.Sent} 步（進行中）", pending:true);
        }
        catch (Exception error)
        {
            bool uncertain = writeAttempted && error is not GameActionRefusedException;
            if (uncertain && plan is not null) lock (gate) uncertainActions.Add(plan.Domain);
            string message = error is GameActionRefusedException refused ? refused.Message : writeAttempted ? (error is ProtocolException reason ? reason.Message + "　" : "") + "結果未確認，已停止重送；請重新登入同步。" : error is ProtocolException p ? p.Message : "操作未送出，請確認連線與目前資料。";
            if (sync is null) ReportAction(new(plan?.Label ?? "操作", message, Uncertain: uncertain),operation,basis?.Player?.RoleId);
            else if (writeAttempted) ReportEventSync(sync, message, uncertain:true);
            if (!writeAttempted && basis is not null && plan is not null)
            {
                // A rejected pre-write intent must release only its own local pending evidence.
                try { await connection.ApplyCommandAsync(attempt, state => ClearUnsent(state, plan.Domain, basis), stop.Token).ConfigureAwait(false); }
                catch (Exception) { /* Connection retirement already revokes this attempt. */ }
            }
            throw new ProtocolException(message);
        }
        finally { receiptLease?.Dispose();if(ownsLane)actionLane.Release(); }
    }
    private async Task DrainGameActionsAsync()
    {
        Task[] pending; lock (gate) pending = actionRuns.ToArray();
        try { await Task.WhenAll(pending).ConfigureAwait(false); } catch (Exception) { /* Each caller retains its operation outcome. */ }
        lock (gate) actionRuns.Clear();
    }
    private static object ActionStamp(ServiceStateSnapshot s, string domain) => domain switch
    {
        "shop" or "inventory_manual" => (s.Phase,s.Local.Session.InitialDataComplete,s.Bag,s.Local.Session.Gold,
            s.Local.Session.NpcDialogue,s.Local.Session.EventFlow,s.Local.Session.PostBattle,s.Local.Battle.Active,s.Activities,s.PlayerKnowledge,s.Companions),
        "party" => s.Party, "companion" => s.Companions, "attributes" => s.PlayerKnowledge,
        "maintenance"=>(s.Bag.Revision,s.PlayerKnowledge,s.Companions),
        "event" => (s.Local.Battle.Active,s.Local.Battle.BattleCount,s.Local.Session.NpcDialogue.Active),
        "inventory" or "alchemy" => (s.Bag.Revision, s.Storage.Storage.Revision),
        "field_supply" => (s.Bag.Revision, s.Bag.UseFailed, s.Recovery, s.PlayerKnowledge, s.Companions, s.Local.Battle.Active, s.Local.Session.EventFlow, s.Activities),
        "tent" => (s.Tent.Scene, s.Tent.Visible, s.Tent.DeployedScene, s.Tent.Inside),
        "battle" => (s.Local.Battle.BattleCount, s.Local.Battle.Round, s.Local.Battle.Active, s.Bag.Revision),
        "rewards" => (s.TimeCube.Count, s.Bag.Revision, s.DailyTasks.Generation),
        "guild" => (s.Guild.Serial, s.GuildActions.Epoch, s.GuildActions.SignState),
        "expedition" => s.Expedition.Revision, "craft" => s.Crafting.Crafting.Revision,
        "instance-reward" => (s.Instances,s.Bag,s.Local.Battle.Active,s.Local.Session.EventFlow),
        "instance" or "instance-list" => s.Instances,
        "npc" => (s.Local.Battle.Active, s.Player?.Scene, s.Local.Session.NpcDialogue.EffectPacket, s.Local.Session.NpcDialogue.OptionIndex), "ark" => (s.Ark.Generation, s.Ark.Starcoin.Revision, s.Ark.Question?.Selected),
        _ => s.PacketCount
    };
    private static ServiceStateSnapshot ClearUnsent(ServiceStateSnapshot s, string domain, ServiceStateSnapshot basis) => domain switch
    {
        "attributes" => CommandState.With(s, points: basis.AttributeAllocation),
        "event" when s.Player?.RoleId==basis.Player?.RoleId&&s.Player?.Scene==basis.Player?.Scene
            &&s.Local.Battle.BattleCount==basis.Local.Battle.BattleCount&&s.Local.Battle.Active==basis.Local.Battle.Active
            &&s.Local.Session.EventFlow is {LastSource:"C20-6",AwaitingResponse:true} flow&&flow.RequestsSent==basis.Local.Session.EventFlow.RequestsSent+1
            =>CommandState.With(s,local:new(s.Local.Session with{EventFlow=basis.Local.Session.EventFlow,
                PostBattle=s.Local.Session.PostBattle.Battle==basis.Local.Session.PostBattle.Battle&&s.Local.Session.PostBattle.ExitPacket==basis.Local.Session.PostBattle.ExitPacket
                    ?s.Local.Session.PostBattle with{Phase=basis.Local.Session.PostBattle.Phase}:s.Local.Session.PostBattle},s.Local.World,s.Local.Battle)),
        "tent" => CommandState.With(s, tent: s.Tent with { Pending = null, EntryContext = basis.Tent.EntryContext }),
        "rewards" => CommandState.With(s, cube: s.TimeCube with { Pending = null }, daily: s.DailyTasks with { Pending = null }),
        "guild" => CommandState.With(s, guildActions: s.GuildActions with { Pending = null, SignAttempted = basis.GuildActions.SignAttempted }),
        "npc" when s.Local.Session.NpcDialogue.EffectPacket == basis.Local.Session.NpcDialogue.EffectPacket && s.Player?.Scene == basis.Player?.Scene &&
            s.Local.Session.EventFlow.LastSource is "NPC 手動操作" or "C20-6" or "C20-8"
            => CommandState.With(s, local: new(s.Local.Session with { NpcDialogue = basis.Local.Session.NpcDialogue, EventFlow = basis.Local.Session.EventFlow }, s.Local.World, s.Local.Battle)),
        _ => s
    };
}
