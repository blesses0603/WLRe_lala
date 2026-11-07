using System.Collections.Immutable;
using System.Globalization;
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
/// authority. Missing catalogs remain unknown; resource hold defaults to true.
/// Daily catalogs are retained for inspection only: receive observers never
/// run catalog activation, reward settlement, Request, Tick or any automatic operation.</summary>
public sealed record ServiceObservationInputs(double ObservedAt)
{
    public WorldSceneCatalog? WorldCatalog { get; init; }
    public DailyCatalogInput DailyCatalog { get; init; } = new(null, null);
    public CraftingScheduleContext? CraftingSchedules { get; init; }
    public ImmutableDictionary<ushort, bool>? ItemStackRules { get; init; }
    public ImmutableDictionary<uint, ImmutableArray<uint>>? NpcSkills { get; init; }
    public bool ResourceHeld { get; init; } = true;
}

/// <summary>Bind caller inputs to the exact current snapshot. Reusing inputs from a stale
/// publication is rejected even when its role/count happen to equal the current values.</summary>
public sealed record ServiceObservationContext(ServiceStateSnapshot Basis, ServiceObservationInputs Inputs);

public sealed record ServiceLocalEvidence(string Phase, WorldPlayer? Player, BigInteger PacketCount);
/// <summary>All pre-dispatch observers see the previous player/phase and the new packet count;
/// dispatch_local supplies the post evidence. Neither side certifies world/resource readiness.</summary>
public sealed record ServiceObservationEvidence(string EventType, ServiceLocalEvidence BeforeLocal,
    ServiceLocalEvidence AfterLocal, ServiceObservationInputs Inputs)
{
    // apply_daily_tasks/apply_cube do not read the bag. Any future pre-live observer
    // must use this exact owned snapshot, never a contradictory external RewardBag.
    public required BagReceiveSnapshot BeforeObserversBag { get; init; }
    // apply_storage can add session stackability evidence before apply_live runs.
    public required BagReceiveSnapshot BeforeLiveBag { get; init; }
    public required BagReceiveSnapshot AfterLiveBag { get; init; }
}
public sealed record ServiceObserverCoverage(string SourceFunction, bool Composed);

/// <summary>Bounded publication, deliberately not a full Python State replacement. Each domain
/// is immutable. See ServiceStateCoordinator.ObserverOrder for the explicitly omitted stages.
/// Shared stackability maps must agree when both supplied; an absent map inherits the other.
/// Companion S8 buffers carry source insertion order. Import them explicitly alongside any
/// local follow:* attributes, or omit local to derive those values from the ordered buffers.</summary>
public sealed class ServiceStateSnapshot
{
    public ServiceStateSnapshot(LocalStateSnapshot? local = null, DailyTaskState? dailyTasks = null,
        TimeCubeState? timeCube = null, PotionStorageSnapshot? recovery = null,
        GuildEventSnapshot? guild = null, ImmutableHashSet<ActivityKind>? activities = null,
        StorageReceiveSnapshot? storage = null, ExpeditionReceiveSnapshot? expedition = null,
        ServiceObservationEvidence? observation = null, CraftingReceiveSnapshot? crafting = null,
        BagReceiveSnapshot? bag = null, CompanionReceiveSnapshot? companions = null)
    {
        Companions = companions ?? CompanionReceiveSnapshot.Empty;
        var attributes = CompanionAttributes(Companions);
        Local = local ?? new(session: new() { Attributes = attributes });
        var localAttributes = Local.Session.Attributes.Where(pair => pair.Key.StartsWith("follow:", StringComparison.Ordinal));
        if (localAttributes.Count() != attributes.Count || localAttributes.Any(pair =>
            !attributes.TryGetValue(pair.Key, out var values) || !SameMap(pair.Value, values)))
            throw new ArgumentException("Local and companion attributes must agree; import ordered companion buffers explicitly.");
        DailyTasks = dailyTasks ?? new();
        TimeCube = timeCube ?? new();
        Recovery = recovery ?? PotionStorageSnapshot.Empty;
        Guild = guild ?? GuildEventSnapshot.Empty;
        Activities = activities ?? [];
        Storage = storage ?? StorageReceiveSnapshot.Empty;
        Bag = bag ?? BagReceiveSnapshot.Empty;
        if (Storage.ServerStackable is { } storageRules && Bag.ServerStackable is { } bagRules && !SameMap(storageRules, bagRules))
            throw new ArgumentException("Storage and bag must agree on the shared server stackability observations.");
        var rules = Bag.ServerStackable ?? Storage.ServerStackable;
        if (!ReferenceEquals(Storage.ServerStackable, rules)) Storage = Storage with { ServerStackable = rules };
        if (!ReferenceEquals(Bag.ServerStackable, rules)) Bag = Bag with { ServerStackable = rules };
        Crafting = crafting ?? CraftingReceiveSnapshot.Empty;
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
    public CraftingReceiveSnapshot Crafting { get; }
    public BagReceiveSnapshot Bag { get; }
    public CompanionReceiveSnapshot Companions { get; }
    public ServiceObservationEvidence? Observation { get; }

    private static bool SameMap<TKey, TValue>(ImmutableDictionary<TKey, TValue> left,
        ImmutableDictionary<TKey, TValue> right) where TKey : notnull =>
        left.Count == right.Count && left.All(pair => right.TryGetValue(pair.Key, out var value) && EqualityComparer<TValue>.Default.Equals(pair.Value, value));

    private static ImmutableDictionary<string, ImmutableDictionary<string, long>> CompanionAttributes(CompanionReceiveSnapshot companions) =>
        companions.Attributes.ToImmutableDictionary(pair => string.Create(CultureInfo.InvariantCulture, $"follow:{pair.Key}"),
            pair => pair.Value.ToImmutableDictionary(value => string.Create(CultureInfo.InvariantCulture, $"{value.Kind}:{value.Parameter}"), value => value.Value));
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
        new("apply_guild", true), new("apply_activity", true), new("apply_crafting", true),
        new("apply_storage", true), new("apply_live", false), new("apply_points_event", false),
        new("apply_party", false), new("apply_expedition", true), new("apply_instances", false),
        new("dispatch_local", true), new("apply_tent", false), new("observe_shop_evidence", false),
        new("observe_efficiency", false), new("apply_actions", false), new("apply_ark", false)
    ];

    /// <summary>apply_live is intentionally not marked complete above. Only these
    /// receive slices run at that stage; player/battle knowledge and equipment are omitted.</summary>
    public static ImmutableArray<string> LiveReceiveSlices { get; } = ["bag", "companions"];

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
        return ApplyDecoded(ServerProtocol.Decode(packet, state.Player?.RoleId, context.Inputs.CraftingSchedules), context.Inputs);
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
        var crafting = CraftingReducer.Apply(state.Crafting, observation, before.Player?.RoleId, inputs.ObservedAt);
        var storage = RoomStorageReducer.Apply(state.Storage, observation);
        // apply_storage writes the same inventory.server_stackable map consumed by
        // apply_live. Import it even for empty/invalid material receipts, before bag reduction.
        var bag = ReferenceEquals(state.Bag.ServerStackable, storage.ServerStackable) ? state.Bag :
            state.Bag with { ServerStackable = storage.ServerStackable };
        var beforeLiveBag = bag;
        bag = BagReceiveReducer.Apply(bag, observation, inputs.ItemStackRules);
        var companions = CompanionReceiveReducer.ApplyBeforeLocal(state.Companions, observation,
            before.Player?.RoleId, inputs.NpcSkills);
        // Only bag and companion receive slices of apply_live are composed. Player/battle
        // knowledge, equipment, apply_points_event and apply_party remain omitted.
        var expedition = ExpeditionReceiveReducer.Apply(state.Expedition, observation, inputs.ObservedAt);
        // apply_instances is not composed.
        // apply_live clears the shared S8 slot buffer on companion deletion/reassignment.
        // Preserve every other entity, and let dispatch_local write the current S8 value once.
        var attributes = state.Local.Session.Attributes;
        foreach (var index in state.Companions.Attributes.Keys.Except(companions.Attributes.Keys))
            attributes = attributes.Remove(string.Create(CultureInfo.InvariantCulture, $"follow:{index}"));
        var stagedBase = ReferenceEquals(attributes, state.Local.Session.Attributes) ? state.Local :
            new LocalStateSnapshot(state.Local.Session with { Attributes = attributes }, state.Local.World, state.Local.Battle);
        var stagedLocal = new LocalStateCoordinator(stagedBase, inputs.WorldCatalog);
        var local = stagedLocal.Apply(observation);
        companions = CompanionReceiveReducer.ObserveLocalAttribute(companions, observation);
        // No post-local observers are composed yet; see the complete ObserverOrder above.
        var after = new ServiceLocalEvidence(local.Phase, local.Player, local.PacketCount);
        var next = new ServiceStateSnapshot(local, daily, cube, recovery, guild, activities, storage,
            expedition, new(observation.Type, before, after, inputs)
            {
                BeforeObserversBag = state.Bag, BeforeLiveBag = beforeLiveBag, AfterLiveBag = bag
            }, crafting, bag, companions);
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
