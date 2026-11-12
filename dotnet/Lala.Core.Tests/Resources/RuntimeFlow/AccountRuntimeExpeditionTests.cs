using Lala.Core.Expedition;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Theory]
    [InlineData("stop")]
    [InlineData("hold")]
    [InlineData("begin")]
    [InlineData("disconnect")]
    public async Task Expedition_assessment_preserves_exact_historical_join_and_observes_revocation(string retirement)
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
            // Synthetic S31 role and level evidence plus a known empty S23 bag.
            var role = new PacketWriter().U8(1).U16(1).U8(0).U16(1).U16(2).U16(3).U16(4).U16(5)
                .U8(20).Raw(new byte[5]).U8(100).U32(0).U8(0).U16(0).U8(0).U8(0).U16(0).Build();
            await client.Send(new Packet(31, 6, new PacketWriter().U8(4).U8(1).Raw(role).Build()),
                new Packet(31, 21, new PacketWriter().U8(0).U32(0).Build()), new Packet(23, 5, [2]));
            await client.WaitFor(update.Task);
            await client.Send(new Packet(31, 35, new PacketWriter().U8(1).U8(64).U32(unchecked((uint)-7)).Build()));
            await client.WaitFor(finish.Task);
            // Fails if inspection introduces any game-command packet beyond the login fixture.
            await client.ExpectClosedAfterRetirement();
        });
        // Existing white-box trust simulation exercises the real receive/resource join using
        // synthetic Unity/SQLite data, not production source admission or reviewed faith stock.
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        var credentials = new AccountCredentials();
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), credentials, resources);
        var created = runtime.InspectExpeditionTask(1, [1]);
        Assert.Same(runtime.PublicationSnapshot, created.Basis);
        Assert.Equal(new[] { ExpeditionAssessmentIssue.NoPublication }, created.Issues);
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        var run = runtime.RunAsync();
        try
        {
            await preparing.Task.WaitAsync(AccountGuard);
            var receiving = await AccountPublicationWhen(runtime, p => p.Publication?.Receive.State.Bag.Ready == true);
            var unavailable = runtime.InspectExpeditionTask(1, [1]);
            Assert.Same(receiving, unavailable.Basis); Assert.Null(unavailable.Basis.Publication!.Catalogs);
            Assert.Contains(ExpeditionAssessmentIssue.CatalogsUnavailable, unavailable.Issues);
            Assert.Null(unavailable.DurationSeconds); Assert.False(unavailable.RecoveryStockComplete);
            Assert.Equal(2, unavailable.ObservedFreeSlots);
            release.SetResult();
            var bound = await AccountPublicationWhen(runtime, p => p.Publication?.Catalogs is not null);
            var state = bound.Publication!.Receive.State;
            var result = runtime.InspectExpeditionTask(1, [1]);
            Assert.Same(bound, result.Basis); Assert.Same(state, result.Basis.Publication!.Receive.State);
            Assert.Same(bound.Publication.Catalogs, result.Basis.Publication.Catalogs);
            Assert.NotNull(result.DurationSeconds); Assert.NotNull(result.Success); Assert.NotNull(result.ConditionMet);
            Assert.Equal(0, Assert.Single(result.RoleFaith).Deficit);
            Assert.True(result.RecoveryStockComplete); Assert.Empty(result.RecoveryStock); Assert.Empty(result.UnknownRecoveryItemIds);
            Assert.Equal(2, result.ObservedFreeSlots);
            Assert.True(result.ResourceHeld); Assert.False(result.CanSendCommands);
            Assert.False(bound.Publication.Catalogs!.RuntimeAdmitted);
            Assert.Same(state, runtime.Publication!.Receive.State);
            Assert.True(state.Bag.Holds.SequenceEqual(runtime.Publication.Receive.State.Bag.Holds));
            update.SetResult();
            var changed = await AccountPublicationWhen(runtime, p => p.Publication?.Receive.State.Expedition.Roles[1].Faith == -7);
            var unsupported = runtime.InspectExpeditionTask(1, [1]);
            Assert.Same(changed, unsupported.Basis); Assert.NotSame(result.Basis, unsupported.Basis);
            Assert.Contains(ExpeditionAssessmentIssue.UnsupportedRoleValues, unsupported.Issues);
            Assert.Null(unsupported.ConditionMet); Assert.Null(unsupported.Success); Assert.Null(unsupported.RoleFaith[0].Deficit);
            Assert.Equal(-7, unsupported.RoleFaith[0].Faith);
            Assert.Equal(100, result.RoleFaith[0].Faith);
            resources.Invalidate();
            var revoked = runtime.InspectExpeditionTask(1, [1]);
            Assert.Null(revoked.Basis.Publication!.Catalogs);
            Assert.Same(changed.Publication!.Receive, revoked.Basis.Publication.Receive);
            Assert.Contains(ExpeditionAssessmentIssue.CatalogsUnavailable, revoked.Issues);
            Assert.Null(revoked.DurationSeconds); Assert.False(revoked.RecoveryStockComplete);
            switch (retirement)
            {
                case "stop": runtime.Stop(); break;
                case "hold": Assert.True(session.Hold(generation)); break;
                case "begin": session.Begin("replacement", "offline"); break;
                default: session.Disconnect(); break;
            }
            var retired = runtime.InspectExpeditionTask(1, [1]);
            Assert.Null(retired.Basis.Publication);
            Assert.Equal(new[] { ExpeditionAssessmentIssue.NoPublication }, retired.Issues);
            Assert.NotNull(result.Basis.Publication.Catalogs); Assert.Equal(100, result.RoleFaith[0].Faith);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.Null(runtime.InspectExpeditionTask(1, [1]).Basis.Publication);
        }
        finally { release.TrySetResult(); update.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }
}
