using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    private sealed class Selector(Func<AccountRoleSelectionRequest, CancellationToken, ValueTask<AccountRoleSelectionChoice?>> select) : IAccountRoleSelector
    {
        public ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken token) => select(request, token);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    public async Task InteractivePreparationDisclosesChoiceAndServicesHeartbeatWhilePending(byte index)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var offered = new TaskCompletionSource<AccountRoleSelectionRequest>(TaskCreationOptions.RunContinuationsAsynchronously);
        var choose = new TaskCompletionSource<AccountRoleSelectionChoice?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var heartbeat = Signal(); var entered = Signal(); var finish = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            var payload = Roles.Payload.ToArray(); payload[0] = index;
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), new Packet(63, 1, payload));
            await client.WaitFor(offered.Task);
            await client.Send(new Packet(1, 23)); await client.Expect(63, 5); heartbeat.SetResult();
            await client.Expect(63, 2, index); await client.Send(World, new Packet(1, 11));
            await client.Expect(12, 1); await client.Expect(3, 2); entered.SetResult();
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        var profile = new AccountConnectionProfile(verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, index == 1 ? 2 : 1, 1, 2);
        int calls = 0;
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), profile,
            new Input((disclosure, _) =>
            {
                Assert.Equal(AccountRoleSelectionMode.Interactive, disclosure.RoleSelectionMode);
                Assert.Null(disclosure.FixedRoleIndex);
                return ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"));
            }), roleSelector: new Selector(async (request, token) =>
            {
                calls++; offered.SetResult(request); return await choose.Task.WaitAsync(token);
            }));
        Assert.Equal(AccountRoleSelectionMode.Interactive, preparation.Disclosure.RoleSelectionMode);
        var run = preparation.RunAsync();
        var request = await offered.Task.WaitAsync(Guard);
        Assert.Equal(generation, request.Generation); Assert.NotEqual(Guid.Empty, request.HandshakeAttempt);
        Assert.NotEqual(Guid.Empty, request.RequestId); Assert.Single(request.Roles);
        await heartbeat.Task.WaitAsync(Guard);
        choose.SetResult(request.Choose(index)); await entered.Task.WaitAsync(Guard);
        Assert.False(preparation.Snapshot.CanSendCommands); Assert.Equal(1, calls);
        preparation.Stop(); finish.SetResult();
        Assert.True((await run.WaitAsync(Guard)).ResourcesReleased);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    public async Task InteractiveCancellationOrDeadlineDrainsLateCallbackWithoutRoleSend(int cause)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var offered = Signal(); var cancelled = Signal(); var release = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
            await client.ExpectClosedAfterRetirement();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))),
            new() { LoginTimeout = cause == 1 ? TimeSpan.FromSeconds(1) : TimeSpan.FromSeconds(20) },
            roleSelector: new Selector(async (request, token) =>
            {
                using var registration = token.Register(() => cancelled.TrySetResult());
                offered.SetResult(); await release.Task; return request.Choose(1);
            }));
        using var cancellation = new CancellationTokenSource();
        var run = runtime.RunAsync(cancellation.Token); await offered.Task.WaitAsync(Guard);
        if (cause == 0) runtime.Stop();
        if (cause == 2) session.Begin("replacement", "interactive");
        if (cause == 3) Assert.True(session.Hold(generation));
        if (cause == 4) cancellation.Cancel();
        await cancelled.Task.WaitAsync(Guard);
        Assert.False(run.IsCompleted);
        release.SetResult();
        Assert.True((await run.WaitAsync(Guard)).ResourcesReleased);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Theory]
    [InlineData(null)]
    [InlineData(0)]
    [InlineData(2)]
    public async Task InteractiveDeclinedOrAbsentRoleFailsClosed(int? choice)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
            await Assert.ThrowsAsync<IOException>(() => client.Next());
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))),
            roleSelector: new Selector((request, _) => ValueTask.FromResult(choice.HasValue ? request.Choose(choice.Value) : null)));
        var result = await runtime.RunAsync().WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.Single(result.Status.History); Assert.False(result.Status.History[0].LoginProtocolCompleted);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task InteractivePendingChoiceIsDrainedAfterEofOrProtocolFailure(bool protocolFailure)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var offered = Signal(); var cancelled = Signal(); var release = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
            await client.WaitFor(offered.Task);
            if (protocolFailure)
            {
                await client.Send(Roles); // A second role-list epoch is never accepted.
                // Explicit protocol retirement can close with FIN or reset on Windows.
                // The shared assertion also rejects pending packets and partial frames.
                await client.ExpectClosedAfterRetirement();
            }
            else await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))),
            roleSelector: new Selector(async (request, token) =>
            {
                using var registration = token.Register(() => cancelled.TrySetResult());
                offered.SetResult(); await release.Task; return request.Choose(1);
            }));
        var run = runtime.RunAsync();
        await cancelled.Task.WaitAsync(Guard); Assert.False(run.IsCompleted);
        release.SetResult(); Assert.True((await run.WaitAsync(Guard)).ResourcesReleased);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Fact]
    public async Task InteractiveChoiceFromPreviousRequestIsRejectedEvenForSameIndex()
    {
        AccountRoleSelectionChoice? previous = null;
        for (int pass = 0; pass < 2; pass++)
        {
            await using var verification = new Peer(); await using var formal = new Peer();
            var first = verification.Run(Verify);
            var second = formal.Run(async client =>
            {
                await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
                await Assert.ThrowsAsync<IOException>(() => client.Next());
            });
            var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
            await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
                new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))),
                roleSelector: new Selector((request, _) =>
                {
                    if (previous is null) { previous = request.Choose(1); return ValueTask.FromResult<AccountRoleSelectionChoice?>(null); }
                    return ValueTask.FromResult<AccountRoleSelectionChoice?>(previous);
                }));
            var result = await runtime.RunAsync().WaitAsync(Guard);
            Assert.True(result.ResourcesReleased); Assert.False(Assert.Single(result.Status.History).LoginProtocolCompleted);
            await Task.WhenAll(first, second).WaitAsync(Guard);
        }
    }

    [Theory]
    [InlineData("empty")]
    [InlineData("locked")]
    [InlineData("duplicate")]
    [InlineData("invalid")]
    public async Task InteractiveUnavailableRoleListNeverInvokesSelector(string kind)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var payload = Roles.Payload.ToArray();
        if (kind == "empty") payload = [];
        if (kind == "locked") payload[^35] = 1;
        if (kind == "duplicate") payload = payload.Concat(payload).ToArray();
        if (kind == "invalid") payload[0] = 3;
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), new Packet(63, 1, payload));
            await client.ExpectClosedAfterRetirement();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        int calls = 0;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))),
            roleSelector: new Selector((request, _) => { calls++; return ValueTask.FromResult<AccountRoleSelectionChoice?>(request.Choose(1)); }));
        var result = await runtime.RunAsync().WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.Equal(0, calls);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Fact]
    public void InteractiveModeRejectsAutomaticRetriesBeforeAnyCallback()
    {
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        var profile = new AccountConnectionProfile(new(System.Net.IPAddress.Loopback, 1), new(System.Net.IPAddress.Loopback, 1), 0, 0, 1, 1, 1);
        var source = new Source((_, _) => throw new InvalidOperationException());
        var selector = new Selector((_, _) => throw new InvalidOperationException());
        Assert.Throws<ArgumentException>(() => new AccountConnectionRuntime(session, generation, profile, source,
            new() { MaximumAttempts = 2 }, roleSelector: selector));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task InteractiveSelectorThrowIsSanitizedAndDrained(bool asynchronous)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
            await Assert.ThrowsAsync<IOException>(() => client.Next());
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        async ValueTask<AccountRoleSelectionChoice?> ThrowLater()
        { await Task.Yield(); throw new InvalidOperationException("private-role-marker"); }
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))),
            roleSelector: new Selector((_, _) => asynchronous ? ThrowLater() : throw new InvalidOperationException("private-role-marker")));
        var result = await runtime.RunAsync().WaitAsync(Guard);
        Assert.True(result.ResourcesReleased);
        Assert.DoesNotContain("private-role-marker", result.ToString());
        Assert.Equal(AccountConnectionFailure.EventHandlerFailed, Assert.Single(result.Status.History).Failure);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Fact]
    public async Task IntegratedAccountRuntimeInvokesInteractiveSelectorBeforeAnyResources()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var root = Path.Combine(Path.GetTempPath(), "interactive-role-" + Guid.NewGuid().ToString("N"));
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
            await Assert.ThrowsAsync<IOException>(() => client.Next());
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "interactive").Generation;
        int calls = 0;
        await using var runtime = AccountRuntime.Create(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))), root,
            roleSelector: new Selector((request, _) =>
            {
                calls++; Assert.Equal(generation, request.Generation); Assert.Single(request.Roles);
                return ValueTask.FromResult<AccountRoleSelectionChoice?>(null);
            }));
        var result = await runtime.RunAsync().WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.Equal(1, calls);
        Assert.Empty(result.ResourceHistory); Assert.False(Directory.Exists(root));
        Assert.False(runtime.Snapshot.CanSendCommands); Assert.False(runtime.Snapshot.HasCurrentResources);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

}
