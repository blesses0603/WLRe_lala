using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Activities;
using Lala.Core.Automation;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.World;

namespace Lala.Core.State;

/// <summary>Explicit inputs for one offline observation, not resource verification or action
/// authority. Missing catalogs/bag evidence remain unknown; resource hold defaults to true.
/// Daily catalogs and bag evidence are retained for inspection only: receive observers never
/// run catalog activation, reward settlement, Request, Tick or any automatic operation.</summary>
public sealed record ServiceObservationInputs(double ObservedAt)
{
    public WorldSceneCatalog? WorldCatalog { get; init; }
    public DailyCatalogInput DailyCatalog { get; init; } = new(null, null);
    public RewardBag Bag { get; init; } = new();
    public bool ResourceHeld { get; init; } = true;
}

/// <summary>Bind caller inputs to the exact current snapshot. Reusing inputs from a stale
/// publication is rejected even when its role/count happen to equal the current values.</summary>
public sealed record ServiceObservationContext(ServiceStateSnapshot Basis, ServiceObservationInputs Inputs);

public sealed record ServiceLocalEvidence(string Phase, WorldPlayer? Player, BigInteger PacketCount);
/// <summary>All pre-dispatch observers see the previous player/phase and the new packet count;
/// dispatch_local supplies the post evidence. Neither side certifies world/resource readiness.</summary>
public sealed record ServiceObservationEvidence(string EventType, ServiceLocalEvidence BeforeLocal,
    ServiceLocalEvidence AfterLocal, ServiceObservationInputs Inputs);
public sealed record ServiceObserverCoverage(string SourceFunction, bool Composed);

/// <summary>Bounded publication, deliberately not a full Python State replacement. Each domain
/// is immutable. See ServiceStateCoordinator.ObserverOrder for the explicitly omitted stages.</summary>
public sealed class ServiceStateSnapshot
{
    public ServiceStateSnapshot(LocalStateSnapshot? local = null, DailyTaskState? dailyTasks = null,
        TimeCubeState? timeCube = null, PotionStorageSnapshot? recovery = null,
        GuildEventSnapshot? guild = null, ImmutableHashSet<ActivityKind>? activities = null,
        StorageReceiveSnapshot? storage = null, ExpeditionReceiveSnapshot? expedition = null,
        ServiceObservationEvidence? observation = null)
    {
        Local = local ?? new();
        DailyTasks = dailyTasks ?? new();
        TimeCube = timeCube ?? new();
        Recovery = recovery ?? PotionStorageSnapshot.Empty;
        Guild = guild ?? GuildEventSnapshot.Empty;
        Activities = activities ?? [];
        Storage = storage ?? StorageReceiveSnapshot.Empty;
        Expedition = expedition ?? ExpeditionReceiveSnapshot.Empty;
        Observation = observation;
    }

    public LocalStateSnapshot Local { get; }
    public DailyTaskState DailyTasks { get; }
    public TimeCubeState TimeCube { get; }
    public PotionStorageSnapshot Recovery { get; }
    public GuildEventSnapshot Guild { get; }
    public ImmutableHashSet<ActivityKind> Activities { get; }
    public StorageReceiveSnapshot Storage { get; }
    public ExpeditionReceiveSnapshot Expedition { get; }
    public ServiceObservationEvidence? Observation { get; }
    public BigInteger PacketCount => Local.PacketCount;
    public string Phase => Local.Phase;
    public WorldPlayer? Player => Local.Player;
    public bool IsCompleteState => false;
    public override string ToString() => nameof(ServiceStateSnapshot);
}

/// <summary>Single-writer offline composition of the supported State.apply receive observers.
/// Source order is preserved, with explicit gaps. Decode, validation and all reductions stage
/// privately; only a fully successful observation publishes one new snapshot and packet count.
/// This transactional failure behavior is deliberately stronger than Python/LocalStateCoordinator
/// for malformed hand-built events. It does not invent deduplication or session/role resets.
/// No AccountSession, lifecycle, transport, commands, clocks, callbacks or resource loading.</summary>
public sealed class ServiceStateCoordinator
{
    // Full retained State.apply order, not merely the stages implemented by this coordinator.
    public static ImmutableArray<ServiceObserverCoverage> ObserverOrder { get; } =
    [
        new("apply_daily_tasks", true), new("apply_cube", true), new("apply_recovery", true),
        new("apply_guild", true), new("apply_activity", true), new("apply_crafting", false),
        new("apply_storage", true), new("apply_live", false), new("apply_points_event", false),
        new("apply_party", false), new("apply_expedition", true), new("apply_instances", false),
        new("dispatch_local", true), new("apply_tent", false), new("observe_shop_evidence", false),
        new("observe_efficiency", false), new("apply_actions", false), new("apply_ark", false)
    ];

    private readonly Thread writer = Thread.CurrentThread;
    private ServiceStateSnapshot state;

    public ServiceStateCoordinator(ServiceStateSnapshot? initial = null) => state = initial ?? new();

    public void AssertWriter()
    {
        if (!ReferenceEquals(Thread.CurrentThread, writer))
            throw new InvalidOperationException("Service state may only be accessed by its owning thread; use immutable snapshots.");
    }

    public ServiceStateSnapshot Snapshot() { AssertWriter(); return state; }

    public ServiceStateSnapshot Apply(Packet packet, ServiceObservationContext context)
    {
        Validate(context);
        ArgumentNullException.ThrowIfNull(packet);
        // Identity-sensitive decoding always uses the current local player, never external bag/catalog evidence.
        return ApplyDecoded(ServerProtocol.Decode(packet, state.Player?.RoleId), context.Inputs);
    }

    public ServiceStateSnapshot Apply(ServerEvent observation, ServiceObservationContext context)
    {
        Validate(context);
        ArgumentNullException.ThrowIfNull(observation);
        return ApplyDecoded(observation, context.Inputs);
    }

    private void Validate(ServiceObservationContext context)
    {
        AssertWriter();
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(context.Inputs);
        ArgumentNullException.ThrowIfNull(context.Inputs.DailyCatalog);
        ArgumentNullException.ThrowIfNull(context.Inputs.Bag);
        if (!ReferenceEquals(context.Basis, state))
            throw new InvalidOperationException("Observation inputs must be bound to the current service snapshot.");
        if (!double.IsFinite(context.Inputs.ObservedAt))
            throw new ArgumentOutOfRangeException(nameof(context), "A finite observation timestamp is required.");
    }

    private ServiceStateSnapshot ApplyDecoded(ServerEvent observation, ServiceObservationInputs inputs)
    {
        var count = state.PacketCount + 1;
        var before = new ServiceLocalEvidence(state.Phase, state.Player, count);
        // State.apply increments before observers. The private local coordinator increments
        // exactly once when dispatch occurs; no service reducer owns/increments this counter.
        var daily = observation switch
        {
            ServerLayoutEvent { Event: RoleListAvailableEvent } => DailyTaskService.RoleListAvailable(),
            ServerLayoutEvent { Event: WorldPlayerEvent world } => DailyTaskService.WorldPlayer(state.DailyTasks, world.Player.RoleId),
            ServerDailyTaskEvent value => DailyTaskService.Apply(state.DailyTasks, value.Event),
            _ => state.DailyTasks
        };
        var cube = observation switch
        {
            ServerLayoutEvent { Event: RoleListAvailableEvent } => TimeCubeService.RoleListAvailable(),
            ServerLayoutEvent { Event: WorldPlayerEvent world } => TimeCubeService.WorldPlayer(state.TimeCube, world.Player.RoleId),
            ServerTimeCubeEvent value => TimeCubeService.Apply(state.TimeCube, value.Event, before.Player?.RoleId, inputs.ObservedAt),
            _ => state.TimeCube
        };
        var recovery = RecoveryReducer.Apply(state.Recovery, observation);
        var guild = GuildEventReducer.Apply(state.Guild, observation, before.Player?.RoleId);
        var activities = ApplyActivities(state.Activities, observation, before.Player?.RoleId);
        // apply_crafting is not composed.
        var storage = RoomStorageReducer.Apply(state.Storage, observation);
        // apply_live (including inventory/knowledge), apply_points_event and apply_party are not composed.
        var expedition = ExpeditionReceiveReducer.Apply(state.Expedition, observation, inputs.ObservedAt);
        // apply_instances is not composed.
        var stagedLocal = new LocalStateCoordinator(state.Local, inputs.WorldCatalog);
        var local = stagedLocal.Apply(observation);
        // No post-local observers are composed yet; see the complete ObserverOrder above.
        var after = new ServiceLocalEvidence(local.Phase, local.Player, local.PacketCount);
        var next = new ServiceStateSnapshot(local, daily, cube, recovery, guild, activities, storage,
            expedition, new(observation.Type, before, after, inputs));
        state = next;
        return next;
    }

    private static ImmutableHashSet<ActivityKind> ApplyActivities(ImmutableHashSet<ActivityKind> current,
        ServerEvent observation, uint? ownRoleId)
    {
        // Rehydrate the existing bounded ActivityLocks reducer in private staging storage;
        // never share a mutable tracker or mutate a previously published activity set.
        var staged = new ActivityLocks();
        foreach (var activity in current) staged.Apply(ownRoleId, new(activity, true));
        switch (observation)
        {
            case ServerActivityEvent activity: staged.Apply(ownRoleId, activity.Event); break;
            case NavigationGeometryChangeEvent geometry: staged.GeometryChanged(ownRoleId, geometry.ClearActivityRole); break;
            case ServerLayoutEvent { Event: WorldPlayerEvent }: staged.WorldPlayerChanged(); break;
            default: return current;
        }
        return staged.Snapshot().ToImmutableHashSet();
    }
}
