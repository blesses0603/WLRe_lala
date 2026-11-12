using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Core.Social;
using Lala.Core.State;
using Lala.Core.World;
using Lala.Core.World.Portals;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static ServiceStateSnapshot GameState() => new(local: new(new() { Phase = "world_ready", InitialDataComplete = true },
        new() { Phase = "world_ready", Player = ProtocolLayouts.ReadWorldPlayer(new(AccountWorld.Payload.Span)) }));

    [Theory]
    [InlineData("verified")]
    [InlineData("position_unknown")]
    [InlineData("destination_unknown")]
    [InlineData("conflict")]
    public async Task Gameplay_travel_uses_only_unambiguous_verified_entry_and_destination(string kind)
    {
        var c = (await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var template = c.Stages.Values.First();
        var stages = new ushort[] { 101, 102, 103 }.ToDictionary(id => id, id => template with { Id = id });
        var key = new EventPortalKey(101, 9);
        var projection = new OfflineEventPortalProjection(
            new Dictionary<EventPortalKey, EventPortalPosition> { [key] = new(101, 9, 25, 30, kind != "position_unknown", null, "synthetic", null, "eve_convey", null) },
            new Dictionary<EventPortalKey, EventPortalDestination> { [key] = new(101, 9, 102, kind != "destination_unknown") },
            kind == "conflict" ? new Dictionary<EventPortalKey, string> { [key] = "conflicting_event_destination" } : null);
        var catalog = new OfflineRuntimeCandidate(c.EveIndexes, c.Items, c.Talks, c.Texts, c.Recipes, stages, c.Doors, c.SceneNames,
            c.Expedition, c.Npcs, c.SourceSha256, new(projection, c.PortalObservations.Coverage));
        if (kind == "verified") Assert.Equal(new GameTravelLeg(101, 9, 102, 25, 30), Assert.Single(GameTravelPlanner.Plan(catalog, 101, 102)));
        else Assert.Throws<NavigationException>(() => GameTravelPlanner.Plan(catalog, 101, 102));
        Assert.Throws<NavigationException>(() => GameTravelPlanner.Plan(catalog, 101, 103));
        Assert.Empty(GameTravelPlanner.Plan(catalog, 101, 101));
    }

    [Fact]
    public async Task Gameplay_party_flag_does_not_accept_unrelated_nearby_or_already_matching_state_as_ack()
    {
        var catalog = (await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var state = CommandState.With(GameState(), party: new() { Enabled = true });
        var plan = ManualGameCommands.Plan(new("party", "flag"), state, catalog, 10, "synthetic");
        Assert.False(plan.Acknowledged(state));
        var unrelated = CommandState.With(state, party: state.Party with { Status = "路人資料更新" });
        Assert.False(plan.Acknowledged(unrelated));
        plan.ObserveReceipt!(new(1, 33, 2, "team_flag", "", Code: 2)); Assert.False(plan.Acknowledged(unrelated));
        plan.ObserveReceipt!(new(2, 33, 2, "team_flag", "", Code: 1)); Assert.True(plan.Acknowledged(unrelated));
    }

    [Theory]
    [InlineData("party")]
    [InlineData("companion")]
    [InlineData("attributes")]
    [InlineData("tent")]
    [InlineData("alchemy")]
    [InlineData("cube")]
    [InlineData("storage")]
    [InlineData("field_item")]
    [InlineData("instance")]
    [InlineData("guild")]
    [InlineData("expedition")]
    [InlineData("craft")]
    [InlineData("portal")]
    [InlineData("ark")]
    public async Task Gameplay_never_admits_an_intent_during_server_event_or_before_world_ack(string kind)
    {
        var catalog = (await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var state = GameState();
        var blocked = CommandState.With(state, local: new(state.Local.Session with { EventFlow = new() { Blocked = true } }, state.Local.World, state.Local.Battle));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(new(kind), blocked, catalog, 10, "synthetic"));
        var early = CommandState.With(state, local: new(state.Local.Session with { Phase = "world_received" }, state.Local.World with { Phase = "world_received" }, state.Local.Battle));
        Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(new(kind), early, catalog, 10, "synthetic"));
    }

    [Theory]
    [InlineData("S20-7", true)]
    [InlineData("S20-10", true)]
    [InlineData("S20-17", true)]
    [InlineData("S20-6", false)]
    [InlineData("S20-37", false)]
    [InlineData("S6-2 kind=1", false)]
    public async Task Gameplay_event_continuation_requires_real_server_permission(string source, bool allowed)
    {
        var catalog = (await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var state = GameState(); state = CommandState.With(state, local: new(state.Local.Session with
            { EventFlow = new() { Blocked = true, LastSource = source } }, state.Local.World, state.Local.Battle));
        if (!allowed) { Assert.Throws<ProtocolException>(() => ManualGameCommands.Plan(new("event"), state, catalog, 10, "synthetic")); return; }
        var plan = ManualGameCommands.Plan(new("event"), state, catalog, 10, "synthetic");
        Assert.Equal((20, 6), ((int)plan.Packet.Main, (int)plan.Packet.Sub));
        var pending = plan.Begin(state); Assert.True(pending.Local.Session.EventFlow.AwaitingResponse);
        Assert.False(plan.Acknowledged(pending)); Assert.Equal(state.PacketCount, pending.PacketCount);
        var ack = CommandState.With(pending, local: new(SessionEventReducer.Apply(pending.Local.Session, new EventEndEvent()), pending.Local.World, pending.Local.Battle));
        Assert.False(plan.Acknowledged(ack));
        plan.ObserveReceipt!(new(1,20,8,"event_end",""));
        Assert.True(plan.Acknowledged(ack));
    }

    [Fact]
    public async Task Gameplay_crafting_add_waits_for_matching_schedule_and_exact_cupboard_deduction()
    {
        var c = (await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var recipe = new RuntimeRecipe(new(500, 0, 0, 8, 1, [new(20, 2)], 30, 0, 0, 0, 0, 0, 0, 1), 0);
        var catalog = new OfflineRuntimeCandidate(c.EveIndexes, c.Items, c.Talks, c.Texts,
            new([recipe], new Dictionary<ushort, RuntimeRecipe> { [500] = recipe }), c.Stages, c.Doors, c.SceneNames, c.Expedition, c.Npcs, c.SourceSha256, c.PortalObservations);
        var state = GameState();
        var crafting = new CraftingReceiveSnapshot { Crafting = new() { Ready = true }, Furniture = new()
            { Ready = true, Owner = 17, CurrentOwner = 17, Items = ImmutableDictionary<ushort, CraftFurnitureSnapshot>.Empty.Add(1, new(1, 8, 0, 0, 0)), ItemOrder = [1] } };
        var storage = new StorageReceiveSnapshot { Storage = new() { Materials = new() { Ready = true,
            Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(1, new(1, 20, 4)), ItemOrder = [1] } } };
        state = new(local: state.Local, bag: new() { Ready = true, Reliable = true }, crafting: crafting, storage: storage);
        var plan = ManualGameCommands.Plan(new("craft", "add", 500, Count: 2), state, catalog, 10, "synthetic");
        Assert.Equal(new byte[] { 1, 0, 244, 1, 2, 0, 1, 0, 1, 0, 4, 0, 0 }, plan.Packet.Payload.ToArray());
        Assert.False(plan.Acknowledged(state));
        plan.ObserveReceipt!(new(1, 64, 16, "craft_added", "", 501, 2)); Assert.False(plan.Acknowledged(state));
        plan.ObserveReceipt!(new(2, 64, 16, "craft_added", "", 500, 2)); Assert.False(plan.Acknowledged(state));
        var deducted = new ServiceStateSnapshot(local: state.Local, bag: state.Bag, crafting: crafting,
            storage: storage with { Storage = storage.Storage with { Materials = storage.Storage.Materials with { Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty, ItemOrder = [] } } });
        Assert.True(plan.Acknowledged(deducted));
        Assert.Single(state.Storage.Storage.Materials.Items); Assert.Empty(state.Crafting.Crafting.Queue);
    }
}
