using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Activities;
using Lala.Core.Automation;
using Lala.Core.Battle;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Lala.Core.Instances;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.Social.Ark;
using Lala.Core.World;
using Lala.Core.World.Tent;
using Lala.Core.World.Shop;

namespace Lala.Core.State;

/// <summary>Explicit inputs for one offline observation, not resource verification or action
/// authority. Missing catalogs remain unknown; resource hold defaults to true.
/// Daily catalogs are retained for inspection only: receive observers never
/// run catalog activation, reward settlement, Request, Tick or any automatic operation.</summary>
public sealed record ServiceObservationInputs(double ObservedAt)
{
    public WorldSceneCatalog? WorldCatalog { get; init; }
    /// <summary>Caller-declared kind=1 instance map IDs, not verified provenance or
    /// permission to enter. Defaults to empty and is never inferred from WorldCatalog.</summary>
    public ImmutableHashSet<ushort> DeclaredMainCatalogMapIds { get; init; } = ImmutableHashSet<ushort>.Empty;
    public DailyCatalogInput DailyCatalog { get; init; } = new(null, null);
    public CraftingScheduleContext? CraftingSchedules { get; init; }
    public ImmutableDictionary<ushort, bool>? ItemStackRules { get; init; }
    public ImmutableDictionary<uint, ImmutableArray<uint>>? NpcSkills { get; init; }
    /// <summary>Per-observation, unverified skill-key/item-fit mappings. Omitted means
    /// unknown; these declarations neither activate catalogs nor authorize any action.</summary>
    public CombatKnowledgeCatalog? KnowledgeCatalog { get; init; }
    /// <summary>Optional observed NPC labels for efficiency display only; never loaded or verified.</summary>
    public ImmutableDictionary<uint, string>? NpcNames { get; init; }
    /// <summary>A completed runtime read, required only when a bound pending Ark question
    /// consumes it. Null means no read supplied, distinct from an observed Absent runtime.</summary>
    public ArkRuntimeObservation? ArkRuntime { get; init; }
    /// <summary>Optional second runtime read at question-text loading; omission reuses ArkRuntime.</summary>
    public ArkRuntimeObservation? ArkQuestionRuntime { get; init; }
    public ArkQuestionMemoryAvailability ArkMemoryAvailability { get; init; } = ArkQuestionMemoryAvailability.Deferred;
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
    public required PlayerKnowledgeSnapshot AfterLivePlayerKnowledge { get; init; }
    /// <summary>Exact updated knowledge stats supplied before local S8 dispatch.</summary>
    public required AttributeAllocationContext AllocationContext { get; init; }
    public required NpcShopObservationContext ShopContext { get; init; }
    public required EfficiencyKnowledgeSnapshot EfficiencyKnowledge { get; init; }
    public required GuildActionsReceiveContext GuildActionsContext { get; init; }
    /// <summary>Null unless this observation consumed a runtime read. Does not mean unavailable.</summary>
    public ArkReceiveContext? ArkContext { get; init; }
    /// <summary>Identity-bound output only, never executed, saved, or replayed automatically.</summary>
    public ArkQuestionMemoryIntent? ArkMemoryIntent { get; init; }
}
public sealed record ServiceObserverCoverage(string SourceFunction, bool Composed);

/// <summary>Bounded publication, deliberately not a full Python State replacement. Each domain
/// is immutable. See ServiceStateCoordinator.ObserverOrder for the composed receive stages.
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
        BagReceiveSnapshot? bag = null, CompanionReceiveSnapshot? companions = null,
        PartyEventSnapshot? party = null, InstanceReceiveSnapshot? instances = null, TentReceiveSnapshot? tent = null,
        PlayerKnowledgeSnapshot? playerKnowledge = null, AttributeAllocationSnapshot? attributeAllocation = null,
        NpcShopEvidenceSnapshot? shopEvidence = null, EfficiencySnapshot? efficiency = null,
        GuildActionsReceiveSnapshot? guildActions = null, ArkReceiveSnapshot? ark = null)
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
        Party = party ?? PartyEventSnapshot.Empty;
        Instances = instances ?? InstanceReceiveSnapshot.Empty;
        Tent = tent ?? TentReceiveSnapshot.Empty;
        PlayerKnowledge = playerKnowledge ?? PlayerKnowledgeSnapshot.Empty;
        AttributeAllocation = attributeAllocation ?? AttributeAllocationSnapshot.Empty;
        ShopEvidence = shopEvidence ?? NpcShopEvidenceSnapshot.Empty;
        Efficiency = efficiency ?? EfficiencySnapshot.Empty;
        GuildActions = guildActions ?? GuildActionsReceiveSnapshot.Empty;
        Ark = ark ?? ArkReceiveSnapshot.Empty;
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
    public PartyEventSnapshot Party { get; }
    public InstanceReceiveSnapshot Instances { get; }
    public TentReceiveSnapshot Tent { get; }
    public PlayerKnowledgeSnapshot PlayerKnowledge { get; }
    public AttributeAllocationSnapshot AttributeAllocation { get; }
    public NpcShopEvidenceSnapshot ShopEvidence { get; }
    public EfficiencySnapshot Efficiency { get; }
    public GuildActionsReceiveSnapshot GuildActions { get; }
    public ArkReceiveSnapshot Ark { get; }
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
/// Source observer order is preserved; non-receive paths remain outside this boundary.
/// Decode, validation and all reductions stage privately; only a fully successful observation publishes one new snapshot and packet count.
/// This transactional failure behavior is deliberately stronger than Python/LocalStateCoordinator
/// for malformed hand-built events. It does not invent deduplication or session/role resets.
/// No AccountSession, lifecycle, transport, commands, clocks, callbacks or resource loading.</summary>
public sealed class ServiceStateCoordinator
{
    // Full retained State.apply entry order; composing a receive subset does not port its action helpers.
    public static ImmutableArray<ServiceObserverCoverage> ObserverOrder { get; } =
    [
        new("apply_daily_tasks", true), new("apply_cube", true), new("apply_recovery", true),
        new("apply_guild", true), new("apply_activity", true), new("apply_crafting", true),
        new("apply_storage", true), new("apply_live", true), new("apply_points_event", true),
        new("apply_party", true), new("apply_expedition", true), new("apply_instances", true),
        new("dispatch_local", true), new("apply_tent", true), new("observe_shop_evidence", true),
        new("observe_efficiency", true), new("apply_actions", true), new("apply_ark", true)
    ];

    /// <summary>Composed receive-only apply_live slices, not command/learned-skill helpers,
    /// runtime catalog activation or a claim of complete combat_resources migration.</summary>
    public static ImmutableArray<string> LiveReceiveSlices { get; } = ["bag", "companions", "combat_knowledge"];

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
        ArgumentNullException.ThrowIfNull(context.Inputs.DeclaredMainCatalogMapIds);
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
        // Python resolves pending player equipment before apply_inventory can return.
        // Remaining knowledge writes are disjoint from the bag/companion branches; retain
        // all three results, then run each existing slice exactly once.
        var knowledge = CombatKnowledgeReceiveReducer.Apply(state.PlayerKnowledge, state.Companions,
            state.Local.Battle, observation, before.Player?.RoleId, inputs.KnowledgeCatalog);
        bag = BagReceiveReducer.Apply(bag, observation, inputs.ItemStackRules);
        var companions = CompanionReceiveReducer.ApplyBeforeLocal(knowledge.Companions, observation,
            before.Player?.RoleId, inputs.NpcSkills);
        // apply_points_event sees this packet's updated knowledge, never raw local S8
        // buffers (which have not been dispatched yet). Widen without narrowing/clamping.
        var allocationContext = new AttributeAllocationContext
        {
            PlayerStats = knowledge.Player.Stats.ToImmutableDictionary(pair => pair.Key,
                pair => new BigInteger(pair.Value), StringComparer.Ordinal)
        };
        var allocation = AttributeAllocationReducer.Apply(state.AttributeAllocation, observation, allocationContext);
        var party = PartyEventReducer.Apply(state.Party, observation, inputs.ObservedAt, before.Player?.RoleId);
        var expedition = ExpeditionReceiveReducer.Apply(state.Expedition, observation, inputs.ObservedAt);
        var instances = InstanceReceiveReducer.Apply(state.Instances, observation, new()
        {
            OwnRoleId = before.Player?.RoleId, DeclaredMainCatalogMapIds = inputs.DeclaredMainCatalogMapIds
        }, inputs.ObservedAt);
        // apply_live clears the shared S8 slot buffer on companion deletion/reassignment.
        // Preserve every other entity, and let dispatch_local write the current S8 value once.
        var attributes = state.Local.Session.Attributes;
        foreach (var index in state.Companions.Attributes.Keys.Except(companions.Attributes.Keys))
            attributes = attributes.Remove(string.Create(CultureInfo.InvariantCulture, $"follow:{index}"));
        var stagedBase = new LocalStateSnapshot(state.Local.Session with { Attributes = attributes },
            state.Local.World, knowledge.Battle);
        var stagedLocal = new LocalStateCoordinator(stagedBase, inputs.WorldCatalog);
        var local = stagedLocal.Apply(observation);
        companions = CompanionReceiveReducer.ObserveLocalAttribute(companions, observation);
        // Tent observes the new role/scene, including world-player resets and position changes.
        // The same per-observation world catalog is consumed; no previous catalog is retained.
        var tent = TentReceiveReducer.Apply(state.Tent, observation, local.Player?.RoleId,
            local.Player?.Scene, inputs.WorldCatalog);
        // The remaining State.apply observers all consume genuine post-local evidence.
        var shopContext = new NpcShopObservationContext(local.PacketCount, bag, local.Session.Gold);
        var shop = NpcShopEvidence.Observe(state.ShopEvidence, observation, shopContext);
        var efficiencyKnowledge = EfficiencyKnowledgeProjector.Project(knowledge.Player, companions,
            local.Player, inputs.NpcNames);
        var efficiency = EfficiencyReceiveReducer.Apply(state.Efficiency, efficiencyKnowledge, observation, inputs.ObservedAt);
        var guildActionsContext = new GuildActionsReceiveContext(local.Player?.RoleId, guild, local.Session.Gold);
        var guildActions = GuildActionsReceiveReducer.Apply(state.GuildActions, observation, guildActionsContext);
        // Only the source question-current branch reads runtime. Missing input must not
        // masquerade as an actual unavailable catalog and freeze imported pending state.
        var readsArkRuntime = observation is ArkQuestionEvent or ArkAnswerResultEvent &&
            state.Ark.Role is not (null or 0) && state.Ark.Role == local.Player?.RoleId &&
            state.Ark.Pending is { Kind: "question" };
        if (readsArkRuntime && inputs.ArkRuntime is null)
            throw new InvalidOperationException("A completed Ark runtime observation is required for this pending question receipt.");
        // Absent is an inert placeholder only on branches that provably do not read
        // runtime; those branches expose no ArkContext and do not claim unavailability.
        var arkContext = new ArkReceiveContext(local.Player?.RoleId, daily.Generation,
            inputs.ArkRuntime ?? ArkRuntimeObservation.Absent)
        {
            QuestionRuntime = inputs.ArkQuestionRuntime, MemoryAvailability = inputs.ArkMemoryAvailability
        };
        var ark = ArkReceiveReducer.Apply(state.Ark, observation, arkContext);
        var after = new ServiceLocalEvidence(local.Phase, local.Player, local.PacketCount);
        var next = new ServiceStateSnapshot(local, daily, cube, recovery, guild, activities, storage,
            expedition, new(observation.Type, before, after, inputs)
            {
                BeforeObserversBag = state.Bag, BeforeLiveBag = beforeLiveBag, AfterLiveBag = bag,
                AfterLivePlayerKnowledge = knowledge.Player, AllocationContext = allocationContext,
                ShopContext = shopContext, EfficiencyKnowledge = efficiencyKnowledge,
                GuildActionsContext = guildActionsContext, ArkContext = readsArkRuntime ? arkContext : null,
                ArkMemoryIntent = ark.MemoryIntent
            }, crafting, bag, companions, party, instances, tent, knowledge.Player, allocation,
            shop, efficiency, guildActions, ark.State);
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
