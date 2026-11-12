using Lala.Core.Inventory;
using Lala.Core.Catalogs;
using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Theory]
    [InlineData("stop", 17u)]
    [InlineData("hold", 0u)]
    [InlineData("begin", 17u)]
    [InlineData("disconnect", 17u)]
    public async Task Crafting_assessment_uses_exact_join_and_retains_historical_sources(string retirement, uint roleId)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var preparing = AccountSignal(); var release = AccountSignal(); var update = AccountSignal(); var finish = AccountSignal();
        source.BeforeObserve = async _ => { preparing.TrySetResult(); await release.Task.WaitAsync(AccountGuard); };
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client);
            var world = new Packet(3, 1, new PacketWriter().U32(roleId).U8(0).U16(101).U16(20).U16(30)
                .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
            await client.Send(world, new Packet(62, 4, new PacketWriter().U32(roleId).Build()), new Packet(23, 5, [2]));
            await client.WaitFor(update.Task);
            await client.Send(new Packet(64, 1, [0]));
            await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        // White-box synthetic catalog trust tests real framed receive + SQLite joins,
        // not production source admission or official-server acceptance.
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        var credentials = new AccountCredentials();
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), credentials, resources);
        var created = runtime.InspectCraftingMaterials(1, 1);
        Assert.Same(runtime.PublicationSnapshot, created.Basis);
        Assert.Equal(CraftingMaterialAssessmentOutcome.NoPublication, created.Outcome); Assert.Null(created.Preflight);
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        var run = runtime.RunAsync();
        try
        {
            await preparing.Task.WaitAsync(AccountGuard);
            var receiving = await AccountPublicationWhen(runtime, p => p.Publication?.Receive.State.Bag.Ready == true);
            var missing = runtime.InspectCraftingMaterials(1, 1);
            Assert.Same(receiving, missing.Basis);
            Assert.Equal(CraftingMaterialAssessmentOutcome.CatalogsUnavailable, missing.Outcome); Assert.Null(missing.Preflight);
            release.SetResult();
            var bound = await AccountPublicationWhen(runtime, p => p.Publication?.Catalogs is not null);
            var itemId = bound.Publication!.Catalogs!.Recipes.Products.Keys.Single();
            var result = runtime.InspectCraftingMaterials(itemId, 2);
            Assert.Same(bound, result.Basis);
            Assert.Equal(CraftingMaterialAssessmentOutcome.Evaluated, result.Outcome);
            var preflight = Assert.IsType<CraftingPreflightResult>(result.Preflight);
            var state = bound.Publication.Receive.State;
            Assert.Equal(roleId, preflight.RoleId);
            Assert.Equal(itemId, result.ItemId); Assert.Equal(2, result.BatchCount);
            Assert.Same(state.Crafting, preflight.Crafting); Assert.Same(state.Bag, preflight.Bag);
            Assert.Same(state.Storage.Storage, preflight.Storage);
            Assert.Equal(bound.Publication.Catalogs.Recipes.Catalog, preflight.Recipes.Catalog);
            Assert.Equal(CraftingPreflightSource.OfflineRuntimeCandidate, preflight.Recipes.Source);
            var expected = CraftingMaterialPreflight.Evaluate(preflight.Recipes, itemId, 2, roleId,
                state.Crafting, state.Bag, state.Storage.Storage);
            Assert.Equal(expected.Blocker, preflight.Blocker);
            Assert.Equal(CraftingPreflightBlocker.ProductClosed, preflight.Blocker);
            Assert.Equal(CraftingPreflightBlocker.AmbiguousProduct, runtime.InspectCraftingMaterials(123, 1).Preflight!.Blocker);
            Assert.Equal(CraftingPreflightBlocker.UnknownRecipe, runtime.InspectCraftingMaterials(0, 1).Preflight!.Blocker);
            Assert.True(result.ResourceHeld); Assert.False(result.CanSendCommands); Assert.False(preflight.CanSendPackets);
            Assert.Equal(nameof(CraftingMaterialAssessment), result.ToString());
            Assert.False(bound.Publication.Catalogs.RuntimeAdmitted);
            AssertSyntheticMaterialProjection(bound);

            // Explicitly missing identity is distinct from a known zero. This direct
            // inspection fixture supplies a synthetic snapshot, not a runtime receive claim.
            var noIdentity = bound with { Publication = bound.Publication with
                { Receive = bound.Publication.Receive with { State = new ServiceStateSnapshot() } } };
            var unknown = CraftingMaterialInspection.Inspect(noIdentity, itemId, 1);
            Assert.Equal(CraftingMaterialAssessmentOutcome.RoleIdentityUnknown, unknown.Outcome);
            Assert.Null(unknown.Preflight); Assert.Same(noIdentity, unknown.Basis);

            // Pending is not produced by this receive-only runtime. Imported observations
            // exercise retention, not an assertion that the runtime issued a command.
            var seededCrafting = state.Crafting with { Crafting = state.Crafting.Crafting with
                { Ready = true, Pending = "synthetic pending", Uncertain = true } };
            var seededState = new ServiceStateSnapshot(local: state.Local, crafting: seededCrafting,
                bag: state.Bag, storage: state.Storage);
            var seeded = bound with { Publication = bound.Publication with
                { Receive = bound.Publication.Receive with { State = seededState } } };
            var pending = CraftingMaterialInspection.Inspect(seeded, itemId, 2);
            Assert.Same(seeded, pending.Basis); Assert.Same(seededCrafting, pending.Preflight!.Crafting);
            Assert.Equal("synthetic pending", pending.Preflight.Crafting.Crafting.Pending);
            Assert.True(pending.Preflight.Crafting.Crafting.Uncertain); Assert.False(pending.CanSendCommands);
            Assert.Equal(result.Outcome, pending.Outcome); Assert.Equal(preflight.Blocker, pending.Preflight.Blocker);

            resources.Invalidate();
            var revoked = runtime.InspectCraftingMaterials(itemId, 2);
            Assert.Equal(CraftingMaterialAssessmentOutcome.CatalogsUnavailable, revoked.Outcome);
            Assert.Null(revoked.Preflight); Assert.Same(bound.Publication.Receive, revoked.Basis.Publication!.Receive);
            update.SetResult();
            var uncertain = await AccountPublicationWhen(runtime, p => p.Publication?.Receive.State.Crafting.Crafting.Uncertain == true);
            Assert.False(uncertain.Publication!.Receive.State.Crafting.Crafting.Ready);
            Assert.Equal(CraftingMaterialAssessmentOutcome.CatalogsUnavailable, runtime.InspectCraftingMaterials(itemId, 1).Outcome);
            Assert.False(preflight.Crafting.Crafting.Uncertain);
            Assert.NotNull(result.Basis.Publication!.Catalogs);
            switch (retirement)
            {
                case "stop": runtime.Stop(); break;
                case "hold": Assert.True(session.Hold(generation)); break;
                case "begin": session.Begin("replacement", "offline"); break;
                default: session.Disconnect(); break;
            }
            var retired = runtime.InspectCraftingMaterials(itemId, 2);
            Assert.Null(retired.Basis.Publication); Assert.Null(retired.Preflight);
            Assert.Equal(CraftingMaterialAssessmentOutcome.NoPublication, retired.Outcome);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.Equal(CraftingMaterialAssessmentOutcome.NoPublication, runtime.InspectCraftingMaterials(itemId, 2).Outcome);
        }
        finally { release.TrySetResult(); update.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    private static void AssertSyntheticMaterialProjection(AccountRuntimePublicationSnapshot received)
    {
        // Explicit direct-inspection fixture: replace recipe and inventory observations
        // with synthetic inputs. This does NOT claim the closed retained fixture recipe
        // was opened by a packet, and never mutates the runtime's publication/catalogs.
        var original = received.Publication!;
        var c = original.Catalogs!;
        var recipe = new RuntimeRecipe(new(500, 0, 0, 8, 1, [new(20, 2)], 30, 0, 0, 0, 0, 0, 0, 1), 0);
        var recipes = new RuntimeRecipeCandidate([recipe], new Dictionary<ushort, RuntimeRecipe> { [500] = recipe });
        var catalogs = new OfflineRuntimeCandidate(c.EveIndexes, c.Items, c.Talks, c.Texts, recipes,
            c.Stages, c.Doors, c.SceneNames, c.Expedition, c.Npcs, c.SourceSha256, c.PortalObservations);
        var craft = new CraftingReceiveSnapshot
        {
            Crafting = new() { Ready = true, Pending = "synthetic pending", Uncertain = true },
            Furniture = new() { Ready = true, Owner = original.Receive.State.Player!.RoleId,
                Items = ImmutableDictionary<ushort, CraftFurnitureSnapshot>.Empty.Add(1, new(1, 8, 0, 0, 0)), ItemOrder = [1] }
        };
        var storage = new StorageReceiveSnapshot { Storage = new() { Materials = new()
            { Ready = true, Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(1, new(1, 20, 4)), ItemOrder = [1] } } };
        var state = new ServiceStateSnapshot(local: original.Receive.State.Local,
            crafting: craft, bag: new() { Ready = true, Reliable = true }, storage: storage);
        var basis = received with { Publication = new(original.Receive with { State = state }, catalogs) };
        var assessed = CraftingMaterialInspection.Inspect(basis, 500, 2);
        Assert.Same(basis, assessed.Basis); Assert.Equal(CraftingMaterialAssessmentOutcome.Evaluated, assessed.Outcome);
        Assert.True(assessed.Preflight!.Success); Assert.False(assessed.CanSendCommands);
        Assert.Same(craft, assessed.Preflight.Crafting); Assert.True(craft.Crafting.Uncertain);
        Assert.Equal("synthetic pending", assessed.Preflight.Crafting.Crafting.Pending);
        Assert.Equal(new CraftingMaterialNeed(20, 4), Assert.Single(assessed.Preflight.Needs));
        Assert.Equal(new CraftingMaterialAllocation(CraftingMaterialSource.Materials, 1, 20, 4, 4, null),
            Assert.Single(assessed.Preflight.Allocations));
        var shortage = CraftingMaterialInspection.Inspect(basis, 500, 3);
        Assert.Equal(CraftingPreflightBlocker.MaterialShortage, shortage.Preflight!.Blocker);
        Assert.Equal(new BigInteger(2), shortage.Preflight.MissingCount); Assert.Empty(shortage.Preflight.Allocations);
        foreach (int invalid in new[] { int.MinValue, 0, 256, int.MaxValue })
            Assert.Equal(CraftingPreflightBlocker.InvalidBatchCount, CraftingMaterialInspection.Inspect(basis, 500, invalid).Preflight!.Blocker);
        // Preserve the intentionally different offline helper contract.
        var offline = CraftingMaterialPreflight.Evaluate(assessed.Preflight.Recipes, 500, 2, null,
            craft with { Furniture = craft.Furniture with { Owner = null } }, state.Bag, storage.Storage);
        Assert.True(offline.Success);
        Assert.Equal(new BigInteger(4), storage.Storage.Materials.Items[1].Count);
        Assert.Single(assessed.Preflight.Allocations); Assert.Empty(state.Bag.Holds);
        Assert.Same(c, received.Publication!.Catalogs);
    }
}
