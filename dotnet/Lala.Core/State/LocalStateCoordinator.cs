using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Lala.Core.Inventory;
using Lala.Core.Sessions;
using Lala.Core.World;

namespace Lala.Core.State;

/// <summary>Immutable publication of the three local dispatch domains, not the full game State.
/// Phase and packet count must agree when both projections are supplied. A missing projection
/// inherits those shared values; player identity has exactly one source, World.Player.</summary>
public sealed class LocalStateSnapshot
{
    public LocalStateSnapshot(SessionEventSnapshot? session = null, WorldEventSnapshot? world = null,
        BattleEventSnapshot? battle = null)
    {
        Session = session ?? new() { Phase = world?.Phase ?? "disconnected", PacketCount = world?.PacketCount ?? 0 };
        World = world ?? new() { Phase = Session.Phase, PacketCount = Session.PacketCount };
        if (Session.Phase != World.Phase || Session.PacketCount != World.PacketCount)
            throw new ArgumentException("Local projections must agree on phase and packet count.");
        Battle = battle ?? BattleEventSnapshot.Empty;
    }

    public SessionEventSnapshot Session { get; }
    public WorldEventSnapshot World { get; }
    public BattleEventSnapshot Battle { get; }
    public string Phase => Session.Phase;
    public BigInteger PacketCount => Session.PacketCount;
    public WorldPlayer? Player => World.Player;
}

/// <summary>Single-writer, offline composition of dispatch_local and State.apply's packet counter.
/// Each decoded observation, including ignored/unsupported events and local send observations,
/// increments once before dispatch. Decoding failures do not count. Helpers do not count.
/// No service observers, automatic requests, I/O, AccountSession or transport lifecycle run here.
/// Capture immutable Snapshot() results on the owner thread before passing them to other threads.</summary>
public sealed class LocalStateCoordinator
{
    private readonly Thread writer = Thread.CurrentThread;
    private readonly WorldSceneCatalog? currentCatalog;
    private LocalStateSnapshot state;

    public LocalStateCoordinator(LocalStateSnapshot? initial = null, WorldSceneCatalog? currentCatalog = null)
    {
        state = initial ?? new();
        this.currentCatalog = currentCatalog;
    }

    public void AssertWriter()
    {
        if (!ReferenceEquals(Thread.CurrentThread, writer))
            throw new InvalidOperationException("Local state may only be accessed by its owning thread; use immutable snapshots.");
    }

    public LocalStateSnapshot Snapshot() { AssertWriter(); return state; }

    /// <summary>Decodes against the current player identity, then applies exactly one observation.
    /// This is an offline packet entry point, not a frame reader or network receiver.</summary>
    public LocalStateSnapshot Apply(Packet packet)
    {
        AssertWriter();
        return Apply(ServerProtocol.Decode(packet, state.Player?.RoleId));
    }

    public LocalStateSnapshot Apply(ServerEvent observation, double? observedAt = null)
    {
        AssertWriter();
        ArgumentNullException.ThrowIfNull(observation);
        AdvancePacketCount();
        // These type partitions mirror state_events.py's disjoint domain kind sets.
        // Unknown and service-only observations deliberately reach no local reducer.
        switch (observation)
        {
            case ServerLayoutEvent { Event: WorldPlayerEvent }:
            case PositionSnapshotEvent or MovementRequestEvent or NavigationGeometryChangeEvent or WalkEvent:
            case SceneNpcMoveEvent or SceneNpcVisibilityEvent or SceneNpcStatusEvent or SceneNpcTeleportEvent or SceneNpcShowEvent:
            case ServerSocialEvent { Event: NearbyLeaveEvent }:
            case ServerInventoryEvent { Event: CraftFurnitureEvent }:
                ReplaceWorld(WorldEventReducer.Apply(state.World, observation, currentCatalog, observedAt));
                if(observation is ServerLayoutEvent{Event:WorldPlayerEvent}||observation is PositionSnapshotEvent fix&&fix.RoleId==state.Player?.RoleId)
                    state=new(state.Session with{EventFlow=state.Session.EventFlow with{PermissionPacket=null,PermissionTracked=true}},state.World,state.Battle);
                break;
            case ServerLayoutEvent { Event: BattleStartEvent or BattleUnitsEvent }:
            case BattleAttributeSetEvent or RoundStartEvent or BattleUnitExitEvent or FightExitEvent
                or AttackResultEvent or WarStyleEvent or WinnerEvent:
                state = new(state.Session, state.World,
                    BattleEventReducer.Apply(state.Battle, observation, state.Player?.RoleId));
                if(observation is ServerLayoutEvent{Event:BattleStartEvent})
                    state=new(state.Session with{EventFlow=state.Session.EventFlow with{PermissionPacket=null,PermissionTracked=true}},state.World,state.Battle);
                break;
            case ServerLayoutEvent { Event: RoleListAvailableEvent }:
            case LoginResultEvent or MovementStopEvent or NpcEffectEvent or EventActiveEvent
                or EventContinuePermissionEvent or EventEndEvent or InitialDataCompleteEvent
                or AttributeSetEvent or UnimplementedServerEvent or EventRejectedEvent
                or GoldSnapshotEvent or GoldDeltaEvent or GoldLimitEvent:
                var session = SessionEventReducer.Apply(state.Session, observation);
                state = new(session, state.World with { Phase = session.Phase }, state.Battle);
                break;
        }
        return state;
    }

    /// <summary>Records an already-successful send observation only. Does not create or send a command.</summary>
    public LocalStateSnapshot Apply(BattleCommandSentEvent observation)
    {
        AssertWriter();
        ArgumentNullException.ThrowIfNull(observation);
        AdvancePacketCount();
        state = new(state.Session, state.World, BattleEventReducer.Apply(state.Battle, observation));
        return state;
    }

    public void RememberPosition(long roleId, ushort x, ushort y)
    {
        AssertWriter();
        ReplaceWorld(WorldEventReducer.RememberPosition(state.World, roleId, x, y));
    }

    public int ClearPositionHistory()
    {
        AssertWriter();
        var result = WorldEventReducer.ClearPositionHistory(state.World);
        ReplaceWorld(result.State);
        return result.Removed;
    }

    public void WaitForPosition()
    {
        AssertWriter();
        ReplaceWorld(WorldEventReducer.WaitForPosition(state.World));
    }

    public void ConfirmLocation(ushort scene, ushort x, ushort y, string source)
    {
        AssertWriter();
        ReplaceWorld(WorldEventReducer.ConfirmLocation(state.World, scene, x, y, source));
    }

    private void AdvancePacketCount()
    {
        var count = state.PacketCount + 1;
        state = new(state.Session with { PacketCount = count }, state.World with { PacketCount = count }, state.Battle);
    }

    private void ReplaceWorld(WorldEventSnapshot world) =>
        state = new(state.Session with { Phase = world.Phase }, world, state.Battle);
}
