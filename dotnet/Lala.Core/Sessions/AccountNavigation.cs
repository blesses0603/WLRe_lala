using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.State;
using Lala.Core.World;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private readonly SemaphoreSlim navigationGate = new(1, 1);
    private readonly SemaphoreSlim navigationSourceGate = new(1, 1);
    private CancellationTokenSource? navigationStop;
    private Task? navigationRun;
    private readonly List<Task> navigationPreviews = [];
    private GameNavigationStatus navigationStatus = new(false, "尚未啟動導航");
    private BigInteger? estimatedBaseFix;
    private uint? estimatedRole;
    private FourPointRoamingCircuit? roamingCircuit;
    public GameNavigationStatus NavigationStatus
    {
        get
        {
            lock (gate)
            {
                var state = connection.Publication?.State;
                return state is { Player: {} player } && player.RoleId == estimatedRole && player.Scene == navigationStatus.Scene && state.Local.World.Location.Confirmed?.PacketNumber == estimatedBaseFix
                    ? navigationStatus : navigationStatus with { EstimatedX = null, EstimatedY = null };
            }
        }
    }
    private void NavigationMessage(GameNavigationStatus status) { lock (gate) navigationStatus = status; }
    public Task<GameNavigationRoute> PreviewNavigationAsync(ushort scene, ushort x, ushort y, bool synchronize = false,
        string mode = "land", bool smooth = false, CancellationToken token = default)
    {
        lock (gate)
        {
            if (retired) throw new NavigationException("連線已結束。");
            navigationPreviews.RemoveAll(task => task.IsCompleted);
            if (navigationPreviews.Count >= 4) throw new NavigationException("導航規劃佇列已滿。");
            var task = Task.Run(() => PreviewNavigationOwnedAsync(scene, x, y, synchronize, mode, smooth, token));
            navigationPreviews.Add(task); return task;
        }
    }
    private async Task<GameNavigationRoute> PreviewNavigationOwnedAsync(ushort scene, ushort x, ushort y, bool synchronize,
        string mode, bool smooth, CancellationToken token)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(stop.Token, token);
        await navigationSourceGate.WaitAsync(linked.Token).ConfigureAwait(false);
        try { return await PreviewNavigationCoreAsync(scene, x, y, synchronize, mode, smooth, linked.Token).ConfigureAwait(false); }
        finally { navigationSourceGate.Release(); }
    }
    private async Task DrainNavigationPreviewsAsync()
    {
        Task[] pending; lock (gate) pending = navigationPreviews.ToArray();
        try { await Task.WhenAll(pending).ConfigureAwait(false); } catch (Exception) { }
        lock (gate) navigationPreviews.Clear();
    }
    private async Task<GameNavigationRoute> PreviewNavigationCoreAsync(ushort scene, ushort x, ushort y, bool synchronize,
        string mode, bool smooth, CancellationToken token)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(stop.Token, token);
        VerifiedNavigationSource source; ServiceStateSnapshot state; Lala.Core.Catalogs.OfflineRuntimeCandidate catalogs;
        lock (gate)
        {
            if (!CurrentCatalogsLocked(out var c) || connection.Publication is not { Phase: AccountReceivePhase.Running } p || p.State.Player?.Scene != scene)
                throw new NavigationException("請先登入並選擇目前角色所在的地圖。");
            state = p.State; catalogs = c!;
            source = resources.CreateNavigationSource() ?? throw new NavigationException("已驗證的導航來源不可用。");
        }
        if (!catalogs.Stages.TryGetValue(scene, out var stage)) throw new NavigationException("目前地圖沒有已核對的場景對應。");
        if (scene is 10000 or 10298 or 10299 or >= 63501 and <= 65500 || stage.ModelId is 10000 or 10004 or 10005)
            throw new NavigationException("小屋內不提供自動導航。");
        var fix = state.Local.World.Location.Confirmed ?? throw new NavigationException("尚未同步角色起點。");
        LogicalNavigationCoordinate start;
        lock (gate)
        {
            if (estimatedRole == state.Player!.RoleId && estimatedBaseFix == fix.PacketNumber && navigationStatus.Scene == scene && navigationStatus.EstimatedX is {} ex && navigationStatus.EstimatedY is {} ey)
                start = new(ex, ey);
            else if (state.Local.World.Location.ConfirmedIsCurrent && fix.Scene == scene) start = new(fix.X, fix.Y);
            else throw new NavigationException("角色起點尚未確認。");
        }
        var entry = await source.LoadAsync(stage.ModelId, mode, synchronize, linked.Token).ConfigureAwait(false);
        if(state.Local.World.Navigation is {Stale:true,InvalidationScope:"house"})
        {
            var sceneCatalog=new WorldSceneCatalog(catalogs.Stages.Keys.ToImmutableHashSet());
            if(WorldObstacleScope.HouseScene(scene,sceneCatalog)==false)
            {
                var expected=state.Local.World.Navigation.Revision;uint expectedRole=state.Player!.RoleId;
                var attempt=connection.Publication?.Attempt??throw new NavigationException("連線已中斷。");
                state=await connection.ApplyCommandAsync(attempt,current=>
                {
                    lock(gate)
                    {
                        if(!source.IsCurrent||!CurrentCatalogsLocked(out var active)||!ReferenceEquals(active,catalogs)
                            ||current.Player?.RoleId!=expectedRole||current.Player.Scene!=scene||current.Local.World.Navigation.Revision!=expected
                            ||current.Local.World.Navigation.InvalidationScope!="house")throw new NavigationException("圖資重建期間場景已改變。");
                    }
                    var nav=current.Local.World.Navigation with{Stale=false,Reasons=[],InvalidationScope=null,Revision=expected+1,
                        RuntimeGeometryVerified=true,GeometryResourceKey=source.Identity,GeometryModel=stage.ModelId};
                    return CommandState.With(current,local:new(current.Local.Session,current.Local.World with{Navigation=nav},current.Local.Battle));
                },linked.Token).ConfigureAwait(false);
            }
        }
        var identity = new OfflineNavigationIdentity(source.Identity, source.DataVersion);
        var stages = new OfflineNavigationStages(identity, catalogs.Stages.Values, linked.Token);
        var preview = new OfflineLogicalNavigationPreview(identity, stages, [entry], linked.Token);
        var route = preview.Route(scene, start, new(x, y), navigation: state.Local.World.Navigation, travelMode: mode, smooth: smooth, cancellationToken: linked.Token);
        uint role = state.Player!.RoleId; var revision = state.Local.World.Navigation.Revision; var baseFix = fix.PacketNumber;
        bool Current()
        {
            lock (gate)
            {
                var p = connection.Publication;
                return !retired && source.IsCurrent && CurrentCatalogsLocked(out var c) && ReferenceEquals(c, catalogs) && p is { Phase: AccountReceivePhase.Running } &&
                    p.State.Player?.RoleId == role && p.State.Player.Scene == scene && !p.State.Local.World.Navigation.Stale &&
                    p.State.Local.World.Navigation.Revision == revision && p.State.Local.World.Location.Confirmed?.PacketNumber == baseFix;
            }
        }
        if (!Current()) throw new NavigationException("規劃期間角色位置、圖資或障礙已改變，請重新規劃。");
        return new(entry, route, role, baseFix, Current);
    }
    public async Task NavigateAsync(ushort scene, ushort x, ushort y, bool synchronize = true, CancellationToken token = default)
    {
        await SetAutomationAsync("roaming", false).ConfigureAwait(false);
        await NavigateCoreAsync(scene, x, y, synchronize, token).ConfigureAwait(false);
    }
    private async Task NavigateCoreAsync(ushort scene, ushort x, ushort y, bool synchronize, CancellationToken token)
    {
        await navigationGate.WaitAsync(token).ConfigureAwait(false);
        Task running;
        try
        {
            await StopNavigationCoreAsync().ConfigureAwait(false);
            lock (gate)
            {
                if (retired || !CanSendGameActions) throw new NavigationException("請先完成登入與資源準備。");
                navigationStop = CancellationTokenSource.CreateLinkedTokenSource(stop.Token, token);
                var cancellation = navigationStop.Token;
                running = navigationRun = Task.Run(() => DriveTravelAsync(scene, x, y, synchronize, cancellation));
            }
        }
        finally { navigationGate.Release(); }
        await running.ConfigureAwait(false);
    }
    public async Task StopNavigationAsync()
    {
        await SetAutomationAsync("roaming", false).ConfigureAwait(false);
        await navigationGate.WaitAsync().ConfigureAwait(false);
        try { await StopNavigationCoreAsync().ConfigureAwait(false); }
        finally { navigationGate.Release(); }
    }
    private async Task RoamOnceAsync(GameAutomationSettings settings,CancellationToken token)
    {
        var p = PublicationSnapshot.Publication;
        if (p?.Receive.State.Player is not {} player || p.Catalogs is not {} catalogs || !catalogs.Stages.TryGetValue(player.Scene, out var stage)) return;
        if (p.Receive.State.Local.Battle.Active == true || p.Receive.State.Local.Session.EventFlow.Blocked) return;
        if(MovementPauseReason(p.Receive.State) is {} pause){NavigationMessage(NavigationStatus with{Running=false,Message=pause});return;}
        VerifiedNavigationSource source;
        lock (gate) source = resources.CreateNavigationSource() ?? throw new NavigationException("導航資源不可用。");
        await navigationSourceGate.WaitAsync(token).ConfigureAwait(false);
        OfflineNavigationCacheEntry entry;
        try { entry = await source.LoadAsync(stage.ModelId, "land", true, token).ConfigureAwait(false); }
        finally { navigationSourceGate.Release(); }
        var fix=p.Receive.State.Local.World.Location.Confirmed??throw new NavigationException("尚無伺服器確認的徘徊中心。");
        var circuit=roamingCircuit;
        if(circuit is not null&&(circuit.Role!=player.RoleId||circuit.Scene!=player.Scene))throw new NavigationException("角色或地圖已改變，請重新啟動徘徊。");
        LogicalNavigationCoordinate origin=new(fix.X,fix.Y);
        lock(gate)
        {
            if(estimatedRole==player.RoleId&&estimatedBaseFix==fix.PacketNumber&&navigationStatus.EstimatedX is {} ex&&navigationStatus.EstimatedY is {} ey)origin=new(ex,ey);
            else if(!p.Receive.State.Local.World.Location.ConfirmedIsCurrent)throw new NavigationException("徘徊起點尚未確認。");
            if(circuit is not null&&circuit.BaseFix!=fix.PacketNumber)
            {
                if(navigationStatus.EstimatedX!=fix.X||navigationStatus.EstimatedY!=fix.Y)circuit=null;
                else circuit.BaseFix=fix.PacketNumber;
            }
        }
        circuit??=new(player.RoleId,player.Scene,origin,fix.PacketNumber,roamingCircuit?.Next??0);
        var identity=new OfflineNavigationIdentity(source.Identity,source.DataVersion);
        var preview=new OfflineLogicalNavigationPreview(identity,new(identity,catalogs.Stages.Values,token),[entry],token);
        // A verified ordinary-map refresh also resolves an early house-scoped invalidation.
        var goal=circuit.Goals[circuit.Next];
        var route=await PreviewNavigationAsync(player.Scene,(ushort)goal.X,(ushort)goal.Y,false,token:token).ConfigureAwait(false);
        var live=connection.Publication?.State??throw new NavigationException("連線已中斷。");
        circuit.Preflight(preview,live.Local.World.Navigation,token);circuit.Validate(route.Route);
        roamingCircuit=circuit;
        var steps=route.ExecutionSteps(token);var initial=route.Points[0];
        lock(gate){estimatedRole=route.Role;estimatedBaseFix=route.BaseFix;navigationStatus=new(true,$"四點徘徊：前往第 {circuit.Next+1} 點",player.Scene,initial.X,initial.Y,0,steps.Length);}
        try
        {
            foreach(var step in steps)
            {
                await Task.Delay(200,token).ConfigureAwait(false);
                var observed=connection.Publication;
                if(observed is null||!route.IsCurrent||observed.State.Local.Battle.Active==true||observed.State.Local.Session.EventFlow.Blocked
                    ||CoordinationReason("roaming",observed.State,catalogs) is not null
                    ||MovementPauseReason(observed.State) is not null
                    ||FieldRecoveryPlanning.Next(observed.State,catalogs,settings) is not null)return;
                await actionLane.WaitAsync(token).ConfigureAwait(false);
                try
                {
                    await connection.SendGameAsync(observed.Attempt,()=>
                    {
                        var current=connection.Publication?.State;
                        if(current is not null&&MovementPauseReason(current) is {} hold)throw new AutomaticPauseException(hold);
                        if(!CanSendGameActions||!route.IsCurrent||current is null||current.Local.Battle.Active==true||current.Local.Session.EventFlow.Blocked||current.Activities.Count>0||CoordinationReason("roaming",current,catalogs) is not null)
                            throw new NavigationException("場景或角色狀態已改變，暫停徘徊。");
                        var team=current.Party.OwnTeam(route.Role);
                        if(team is not null&&team.LeaderId!=route.Role)throw new NavigationException("隊員跟隨隊長，不能自行徘徊。");
                        return CandidateCommands.Walk((int)step.X,(int)step.Y);
                    },token).ConfigureAwait(false);
                    await connection.ApplyCommandAsync(observed.Attempt,current=>CommandState.With(current,local:new(current.Local.Session,
                        WorldEventReducer.Apply(current.Local.World,new MovementRequestEvent((ushort)step.X,(ushort)step.Y)),current.Local.Battle)),token).ConfigureAwait(false);
                    lock(gate)navigationStatus=navigationStatus with{EstimatedX=step.X,EstimatedY=step.Y,Completed=navigationStatus.Completed+1};
                }
                finally{actionLane.Release();}
            }
            circuit.Advance();
        }
        finally{lock(gate)navigationStatus=navigationStatus with{Running=false};}
    }
    private async Task StopNavigationCoreAsync()
    {
        CancellationTokenSource? cancellation; Task? pending;
        lock (gate) { cancellation = navigationStop; pending = navigationRun; }
        if (cancellation is not null) await cancellation.CancelAsync().ConfigureAwait(false);
        if (pending is not null) { try { await pending.ConfigureAwait(false); } catch (OperationCanceledException) { } catch (NavigationException) { } }
        cancellation?.Dispose();
        lock (gate) { navigationStop = null; navigationRun = null; navigationStatus = navigationStatus with { Running = false, Message = "已停止導航；位置仍以伺服器資料為準" }; }
    }
    private async Task DriveNavigationAsync(ushort scene, ushort x, ushort y, bool synchronize, CancellationToken token)
    {
        try
        {
            while (true)
            {
                token.ThrowIfCancellationRequested();
                var s = connection.Publication?.State ?? throw new NavigationException("連線已中斷。");
                if (s.Player?.Scene != scene) throw new NavigationException("地圖已改變，舊導航已停止。");
                if (MovementPauseReason(s) is {} pause)
                { NavigationMessage(NavigationStatus with { Running = true, Message = pause }); await Task.Delay(250, token).ConfigureAwait(false); continue; }
                NavigationMessage(NavigationStatus with { Running = true, Message = synchronize ? "同步並規劃同版導航資料" : "規劃導航路線", Scene = scene });
                var route = await PreviewNavigationAsync(scene, x, y, synchronize, token: token).ConfigureAwait(false);
                var steps = route.ExecutionSteps(token); bool replan = false;
                var initial = route.Points[0];
                lock (gate) { estimatedRole = route.Role; estimatedBaseFix = route.BaseFix; navigationStatus = new(true, "移動中（本機推算）", scene, initial.X, initial.Y, 0, steps.Length); }
                foreach (var step in steps)
                {
                    await Task.Delay(200, token).ConfigureAwait(false);
                    if (!route.IsCurrent) { replan = true; break; }
                    await actionLane.WaitAsync(token).ConfigureAwait(false);
                    try
                    {
                        var p = connection.Publication ?? throw new NavigationException("連線已中斷。");
                        if (MovementPauseReason(p.State) is not null) { replan = true; break; }
                        await connection.SendGameAsync(p.Attempt, () =>
                        {
                            var current = connection.Publication?.State;
                            if(current is not null&&MovementPauseReason(current) is{} pause)throw new AutomaticPauseException(pause);
                            if (!CanSendGameActions || !route.IsCurrent || current?.Local.Battle.Active == true || current?.Local.Session.EventFlow.Blocked != false || current.Activities.Count > 0)
                                throw new NavigationException("移動前角色或場景狀態已改變。");
                            var team = current.Party.OwnTeam(route.Role);
                            if (team is not null && team.LeaderId != route.Role) throw new NavigationException("隊員跟隨隊長，不能自行導航。");
                            return CandidateCommands.Walk((int)step.X, (int)step.Y);
                        }, token).ConfigureAwait(false);
                        await connection.ApplyCommandAsync(p.Attempt, state =>
                        {
                            var world = WorldEventReducer.Apply(state.Local.World, new MovementRequestEvent((ushort)step.X, (ushort)step.Y));
                            return CommandState.With(state, local: new(state.Local.Session, world with { LocalMovement = new("running", new(scene, (ushort)step.X, (ushort)step.Y, "local_prediction")) }, state.Local.Battle));
                        }, token).ConfigureAwait(false);
                        lock (gate) navigationStatus = navigationStatus with { EstimatedX = step.X, EstimatedY = step.Y, Completed = navigationStatus.Completed + 1 };
                    }
                    catch(AutomaticPauseException){replan=true;break;}
                    finally { actionLane.Release(); }
                }
                if (replan) continue;
                NavigationMessage(NavigationStatus with { Running = false, Message = "路線已走完（本機推算，等待伺服器位置確認）" });
                return;
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { NavigationMessage(NavigationStatus with { Running = false, Message = "已取消導航" }); }
        catch (Exception error)
        {
            string message = error is NavigationException or ProtocolException ? error.Message : "導航未完成，已停止移動；請檢查圖資與連線。";
            NavigationMessage(NavigationStatus with { Running = false, Message = message });
            throw new NavigationException(message);
        }
    }
    private async Task DriveTravelAsync(ushort target, ushort x, ushort y, bool synchronize, CancellationToken token)
    {
        try
        {
            var p = PublicationSnapshot.Publication ?? throw new NavigationException("連線已結束。");
            var catalog = p.Catalogs ?? throw new NavigationException("已驗證圖資不可用。");
            uint role = p.Receive.State.Player!.RoleId;
            var legs = GameTravelPlanner.Plan(catalog, p.Receive.State.Player.Scene, target);
            foreach (var leg in legs)
            {
                token.ThrowIfCancellationRequested();
                var current = PublicationSnapshot.Publication;
                if (current?.Receive.State.Player is not {} player || player.RoleId != role || player.Scene != leg.Scene || !ReferenceEquals(current.Catalogs, catalog))
                    throw new NavigationException("跨圖期間角色或資源已變更。");
                await DriveNavigationAsync(leg.Scene, leg.X, leg.Y, synchronize, token).ConfigureAwait(false);
                token.ThrowIfCancellationRequested();
                if (connection.Publication?.State.Player?.Scene == leg.Destination) continue; // Server may trigger the boundary while walking.
                var arrived = NavigationStatus;
                if (arrived.Scene != leg.Scene || arrived.EstimatedX is not {} ex || arrived.EstimatedY is not {} ey || Math.Abs(ex - leg.X) > 2 || Math.Abs(ey - leg.Y) > 2)
                    throw new NavigationException("尚未走到出口範圍，跨圖已停止。");
                NavigationMessage(arrived with { Running = true, Message = $"通過出口 {leg.Door}，等待伺服器確認地圖 {leg.Destination}" });
                await QueueAction(new("portal", Target: leg.Destination, Index: leg.Door, Scene: leg.Scene), token, true).ConfigureAwait(false);
                if (connection.Publication?.State.Player?.Scene != leg.Destination) throw new NavigationException("伺服器未確認預期目的地。");
            }
            await DriveNavigationAsync(target, x, y, synchronize, token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { NavigationMessage(NavigationStatus with { Running = false, Message = "已停止跨圖導航。" }); }
        catch (Exception error) { NavigationMessage(NavigationStatus with { Running = false, Message = error is NavigationException or ProtocolException ? error.Message : "跨圖導航未完成，已停止。" }); }
    }
}
