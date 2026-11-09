using System.Collections.Immutable;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Inventory;
using Xunit;

namespace Lala.Core.Tests.Resources;
public sealed partial class ResourceRuntimeBootstrapTests
{
    [Theory]
    [InlineData("stop")]
    [InlineData("hold")]
    [InlineData("begin")]
    [InlineData("disconnect")]
    public async Task Maintenance_joins_exact_publication_and_revokes_without_historical_fallback(string retirement)
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
            await client.Send(new Packet(23, 5, [2]),
                new Packet(23, 11, new PacketWriter().U16(20).U8(200).U8(1).U32(123).Raw(new byte[44]).Build()));
            await client.WaitFor(update.Task);
            await client.Send(new Packet(23, 11, []));
            await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        // Private synthetic trust seam checks framed receive + SQLite wiring only.
        // No retained reviewed-positive item payload or production admission is claimed.
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        var credentials = new AccountCredentials();
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), credentials, resources);
        var before = runtime.InspectMaintenance(50, [0, 0]);
        Assert.Same(runtime.PublicationSnapshot, before.Basis);
        Assert.Equal(MaintenanceAssessmentOutcome.NoPublication, before.Outcome);
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        var run = runtime.RunAsync();
        try
        {
            await preparing.Task.WaitAsync(AccountGuard);
            var receiving = await AccountPublicationWhen(runtime, p => p.Publication?.Receive.State.PlayerKnowledge.Equipment.UnresolvedEquips?.Length == 1);
            var missing = runtime.InspectMaintenance(50, [0, 0]);
            Assert.Same(receiving, missing.Basis); Assert.Equal(MaintenanceAssessmentOutcome.CatalogsUnavailable, missing.Outcome);
            release.SetResult();
            var bound = await AccountPublicationWhen(runtime, p => p.Publication?.Catalogs is not null);
            var result = runtime.InspectMaintenance(50, [0, 0]);
            Assert.Same(bound, result.Basis); Assert.Equal(MaintenanceAssessmentOutcome.Evaluated, result.Outcome);
            Assert.Empty(result.Targets); Assert.Null(result.RepairSupply);
            Assert.True(result.ResourceHeld); Assert.False(result.CanSendCommands);
            Assert.Equal(nameof(MaintenanceAssessment), result.ToString());
            Assert.False(bound.Publication!.Catalogs!.RuntimeAdmitted);
            AssertSyntheticMaintenanceProjection(bound);
            foreach (var threshold in new[] { -1, 250, int.MaxValue })
                Assert.Equal(MaintenanceAssessmentOutcome.InvalidOptions, runtime.InspectMaintenance(threshold, [0, 0]).Outcome);
            Assert.Equal(MaintenanceAssessmentOutcome.InvalidOptions, runtime.InspectMaintenance(50, default).Outcome);
            Assert.Equal(MaintenanceAssessmentOutcome.InvalidOptions, runtime.InspectMaintenance(50, [0]).Outcome);
            Assert.Equal(MaintenanceAssessmentOutcome.InvalidOptions, runtime.InspectMaintenance(50, [65535, 0]).Outcome);
            resources.Invalidate();
            var revoked = runtime.InspectMaintenance(50, [0, 0]);
            Assert.Equal(MaintenanceAssessmentOutcome.CatalogsUnavailable, revoked.Outcome);
            Assert.Same(bound.Publication.Receive, revoked.Basis.Publication!.Receive);
            Assert.Empty(revoked.Targets); Assert.Empty(revoked.RepairStock); Assert.Null(revoked.RepairSupply);
            update.SetResult();
            await AccountPublicationWhen(runtime, p => p.Publication?.Receive.State.PlayerKnowledge.Equipment.UnresolvedEquips?.Length == 0);
            Assert.Equal(MaintenanceAssessmentOutcome.CatalogsUnavailable, runtime.InspectMaintenance(50, [0, 0]).Outcome);
            Assert.NotNull(result.Basis.Publication!.Catalogs);
            switch (retirement)
            {
                case "stop": runtime.Stop(); break;
                case "hold": Assert.True(session.Hold(generation)); break;
                case "begin": session.Begin("replacement", "offline"); break;
                default: session.Disconnect(); break;
            }
            var retired = runtime.InspectMaintenance(50, [0, 0]);
            Assert.Null(retired.Basis.Publication); Assert.Equal(MaintenanceAssessmentOutcome.NoPublication, retired.Outcome);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.Equal(MaintenanceAssessmentOutcome.NoPublication, runtime.InspectMaintenance(50, [0, 0]).Outcome);
        }
        finally { release.TrySetResult(); update.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    private static void AssertSyntheticMaintenanceProjection(AccountRuntimePublicationSnapshot received)
    {
        var original = received.Publication!; var c = original.Catalogs!;
        var rows = new Dictionary<ushort, ItemDataRow>
        {
            [20] = new(20, "synthetic worn", 0, 0, 144, 0, 0, new() { Kind = 1, Special = 0, FitType = 1 }),
            [10] = new(10, "synthetic repair", 0, 0, 0, 0, 0, new() { Kind = 25, Special = 130 })
        };
        var catalogs = new OfflineRuntimeCandidate(c.EveIndexes, rows, c.Talks, c.Texts, c.Recipes,
            c.Stages, c.Doors, c.SceneNames, c.Expedition, c.Npcs, c.SourceSha256, c.PortalObservations);
        // Catalog binding alone does not rewrite published knowledge. A subsequent
        // ordinary receive applies the existing fit resolver before target inspection.
        var boundOnly = received with { Publication = new(original.Receive, catalogs) };
        Assert.Empty(MaintenanceKnowledge.Inspect(boundOnly, 50, [10, 0]).Targets);
        var previous = original.Receive.State;
        var reduced = CombatKnowledgeReceiveReducer.Apply(previous.PlayerKnowledge, previous.Companions,
            previous.Local.Battle, new ServerLiveDataEvent(new BagSnapshotEvent(2, [])),
            catalog: AccountRuntime.ProjectKnowledgeCatalog(rows, null));
        var receivedAgain = boundOnly with { Publication = new(original.Receive with
            { State = new ServiceStateSnapshot(playerKnowledge: reduced.Player, companions: reduced.Companions) }, catalogs) };
        Assert.Single(MaintenanceKnowledge.Inspect(receivedAgain, 50, [10, 0]).Targets);
        Assert.Single(previous.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Empty(MaintenanceKnowledge.Inspect(boundOnly, 50, [10, 0]).Targets);
        var equipment = KnowledgeEquipment.FromItem(original.Receive.State.PlayerKnowledge.Equipment.UnresolvedEquips!.Value.Single());
        var player = new PlayerKnowledgeSnapshot { Equipment = new() { Equips = [equipment] } };
        var input = JsonNode.Parse("""{"ready":true,"reliable":true,"items":{"2":{"item_id":10,"count":3,"damage":0}}}""")!;
        var bag = MaintenanceKnowledgeTests.Bag(input);
        var state = new ServiceStateSnapshot(playerKnowledge: player, bag: bag);
        var basis = received with { Publication = new(original.Receive with { State = state }, catalogs) };
        var result = MaintenanceKnowledge.Inspect(basis, 50, [10, 0]);
        Assert.Same(basis, result.Basis); Assert.Same(equipment, Assert.Single(result.Targets).Equipment);
        Assert.Same(bag.Items[2], result.RepairSupply); Assert.Equal(3, Assert.Single(result.RepairStock).Count);
        Assert.False(result.CanSendCommands); Assert.Empty(bag.Holds); Assert.Empty(bag.Reserved);
        // Replacing a full record with sparse appearance must not reuse its old damage.
        var sparse = player with { Equipment = new() { Equips = [new(20, 1)] } };
        var replacement = basis with { Publication = new(original.Receive with
            { State = new ServiceStateSnapshot(playerKnowledge: sparse, bag: bag) }, catalogs) };
        var unknown = MaintenanceKnowledge.Inspect(replacement, 50, [10, 0]);
        Assert.Empty(unknown.Targets); Assert.Null(unknown.RepairSupply);
        Assert.Single(result.Targets); Assert.NotNull(result.RepairSupply);
        Assert.Same(c, received.Publication!.Catalogs);
    }
}
