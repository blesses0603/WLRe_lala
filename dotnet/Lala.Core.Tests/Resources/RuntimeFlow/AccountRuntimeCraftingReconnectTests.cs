using Lala.Core.Inventory;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Crafting_assessment_reconnects_without_reusing_old_catalog_or_receive_evidence()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var reconnect = AccountSignal(); var allowReplacement = AccountSignal(); var refresh = AccountSignal();
        var releaseRefresh = AccountSignal(); var finish = AccountSignal();
        int blockRefresh = 0;
        source.BeforeObserve = async _ =>
        {
            if (Volatile.Read(ref blockRefresh) != 0)
            { refresh.TrySetResult(); await releaseRefresh.Task.WaitAsync(AccountGuard); }
        };
        var first = verification.Run(AccountVerify, async client =>
        {
            await client.WaitFor(allowReplacement.Task); await AccountVerify(client);
        });
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(reconnect.Task); await client.CloseSendAndExpectEof();
        }, async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources,
            new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMilliseconds(100), MaximumRetryDelay = TimeSpan.FromMilliseconds(100) });
        var run = runtime.RunAsync();
        try
        {
            var ready = await AccountPublicationWhen(runtime, value => ReceivingPublication(value) && value.Publication!.Catalogs is not null);
            var original = runtime.InspectCraftingMaterials(99, 1);
            Assert.Same(ready, original.Basis); Assert.NotNull(original.Preflight);
            Volatile.Write(ref blockRefresh, 1);
            var pending = runtime.WaitForPublicationChangeAsync(ready); reconnect.SetResult();
            var retired = await pending.WaitAsync(AccountGuard); Assert.NotSame(ready, retired);
            Assert.Null(retired.Publication?.Catalogs);
            var replacement = await AccountPublicationWhen(runtime, value => value.Connection.Generation == generation + 1);
            Assert.NotEqual(ready.Publication!.Receive.Attempt, replacement.Publication?.Receive.Attempt);
            Assert.Null(replacement.Publication?.Catalogs);
            allowReplacement.SetResult(); await refresh.Task.WaitAsync(AccountGuard);
            var receiving = await AccountPublicationWhen(runtime, value => value.Connection.Generation == generation + 1 && ReceivingPublication(value));
            Assert.Null(receiving.Publication!.Catalogs);
            var absent = runtime.InspectCraftingMaterials(99, 1);
            Assert.Same(receiving, absent.Basis); Assert.Null(absent.Preflight);
            Assert.Equal(CraftingMaterialAssessmentOutcome.CatalogsUnavailable, absent.Outcome);
            Assert.NotEqual(ready.Publication.Receive.Attempt, receiving.Publication.Receive.Attempt);
            Assert.Equal(ready.Publication.Receive.Revision, receiving.Publication.Receive.Revision); // Revision resets per attempt.
            Assert.Same(receiving, await runtime.WaitForPublicationChangeAsync(ready).WaitAsync(AccountGuard));
            var bound = runtime.WaitForPublicationChangeAsync(receiving); releaseRefresh.SetResult();
            var current = await bound.WaitAsync(AccountGuard);
            Assert.Same(receiving.Publication.Receive, current.Publication!.Receive);
            Assert.NotNull(current.Publication.Catalogs); Assert.NotNull(ready.Publication.Catalogs);
            Assert.NotSame(ready.Publication.Catalogs, current.Publication.Catalogs);
            Assert.Equal(generation + 1, current.Connection.Generation);
            var rebound = runtime.InspectCraftingMaterials(99, 1);
            Assert.Same(current, rebound.Basis); Assert.NotNull(rebound.Preflight);
            Assert.NotSame(original.Preflight!.Crafting, rebound.Preflight!.Crafting);
            Assert.Same(current.Publication.Receive.State.Bag, rebound.Preflight.Bag);
            Assert.Equal(CraftingMaterialAssessmentOutcome.Evaluated, rebound.Outcome);
            Assert.Same(ready.Publication.Receive.State.Crafting, original.Preflight.Crafting);
            Assert.NotNull(original.Basis.Publication!.Catalogs);
            runtime.Stop(); Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { reconnect.TrySetResult(); allowReplacement.TrySetResult(); releaseRefresh.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

}
