using System.Collections.Concurrent;
using Xunit;
using static Lala.Android.Lifecycle.Tests.LifecycleFixture;

namespace Lala.Android.Lifecycle.Tests;

public sealed class ConnectionCoordinatorTests
{
    [Fact]
    public async Task NetworkReadinessNeverClaimsAuthenticationOrActiveSession()
    {
        await using var fixture = new LifecycleFixture();
        await fixture.Owner.StartAsync(new("one", "server"));
        Assert.Equal(ConnectionPhase.WaitingForNetwork, fixture.Owner.Snapshot.Phase);
        Assert.Equal(0, fixture.Factory.CreationCount);

        await fixture.Owner.SetNetworkAvailableAsync(true);
        var adapter = await fixture.Factory.NextRunningAsync();
        Assert.Equal(ConnectionPhase.Connecting, fixture.Owner.Snapshot.Phase);
        adapter.Active();
        Assert.Equal(ConnectionPhase.Active, fixture.Owner.Snapshot.Phase);
    }

    [Fact]
    public async Task UnavailableFactoryNeverCreatesOrSimulatesAConnection()
    {
        await using var fixture = new LifecycleFixture(available: false);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        await fixture.Owner.StartAsync(new("one", "server"));
        Assert.Equal(ConnectionPhase.Unavailable, fixture.Owner.Snapshot.Phase);
        Assert.Equal(ConnectionEndReason.CoreUnavailable, fixture.Owner.Snapshot.Reason);
        Assert.Equal(0, fixture.Factory.CreationCount);
        await fixture.Owner.SetNetworkAvailableAsync(false);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        Assert.Equal(ConnectionPhase.Unavailable, fixture.Owner.Snapshot.Phase);
        Assert.Equal(0, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task RepeatedConcurrentStartIsIdempotent()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        long generation = fixture.Owner.Snapshot.Generation;
        await Task.WhenAll(Enumerable.Range(0, 32).Select(_ =>
            Task.Run(() => fixture.Owner.StartAsync(adapter.Target))));
        Assert.Equal(1, fixture.Factory.CreationCount);
        Assert.Equal(generation, fixture.Owner.Snapshot.Generation);
        Assert.Equal(0, adapter.DisposeCount);
    }

    [Fact]
    public async Task SwitchingAccountsWaitsForActualReleaseAndRejectsOldCallbacks()
    {
        await using var fixture = new LifecycleFixture();
        var old = await fixture.StartAsync();
        old.HoldRelease = true;
        old.Active();
        long generation = fixture.Owner.Snapshot.Generation;
        Task changing = fixture.Owner.StartAsync(new("account-two", "server"));
        await old.DisposalStarted.Task.WaitAsync(TestTimeout);
        Assert.False(changing.IsCompleted);
        Assert.Equal(1, fixture.Factory.CreationCount);
        Assert.True(fixture.Owner.Snapshot.Generation > generation);
        old.Active();
        Assert.Equal(ConnectionPhase.Stopping, fixture.Owner.Snapshot.Phase);

        old.Release();
        await changing.WaitAsync(TestTimeout);
        var next = await fixture.Factory.NextRunningAsync();
        Assert.Equal("account-two", next.Target.AccountKey);
        Assert.True(old.Released.Task.IsCompletedSuccessfully);
        old.Active();
        Assert.Equal(ConnectionPhase.Connecting, fixture.Owner.Snapshot.Phase);
        next.Active();
        Assert.Equal(ConnectionPhase.Active, fixture.Owner.Snapshot.Phase);
        Assert.Equal(1, fixture.Factory.MaximumLiveOwners);
    }

    [Fact]
    public async Task StopDuringConnectingWaitsForReleaseAndCannotBeResurrected()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HoldRelease = true;
        Task stopping = fixture.Owner.StopAsync();
        await adapter.CancellationSeen.Task.WaitAsync(TestTimeout);
        await adapter.DisposalStarted.Task.WaitAsync(TestTimeout);
        Assert.False(stopping.IsCompleted);
        adapter.Active();
        Assert.Equal(ConnectionPhase.Stopping, fixture.Owner.Snapshot.Phase);
        adapter.Release();
        await stopping.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
        adapter.Active();
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
        Assert.Equal(1, adapter.DisposeCount);
    }

    [Fact]
    public async Task StopSynchronouslyMarksTokenCanceledWithoutRunningBlockingCallbacksInline()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        using var release = new ManualResetEventSlim();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var callback = adapter.Token.Register(() =>
        {
            entered.TrySetResult();
            release.Wait(TestTimeout);
        });
        Task stopping = fixture.Owner.StopAsync();
        Assert.True(adapter.Token.IsCancellationRequested);
        await entered.Task.WaitAsync(TestTimeout);
        (await fixture.Delay.TakeAsync(CleanupTimeout)).Complete();
        await stopping.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.CleanupBlocked, fixture.Owner.Snapshot.Phase);
        release.Set();
        await PhaseAsync(fixture.Owner, ConnectionPhase.Stopped);
    }

    [Fact]
    public async Task NonCooperativeCancellationTimesOutButCannotOverlapReplacement()
    {
        await using var fixture = new LifecycleFixture();
        var old = await fixture.StartAsync();
        old.HonorCancellation = false;
        Task stopping = fixture.Owner.StopAsync();
        await old.CancellationSeen.Task.WaitAsync(TestTimeout);
        (await fixture.Delay.TakeAsync(CleanupTimeout)).Complete();
        await stopping.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.CleanupBlocked, fixture.Owner.Snapshot.Phase);
        Assert.Equal(ConnectionEndReason.CleanupTimedOut, fixture.Owner.Snapshot.Reason);

        await fixture.Owner.StartAsync(new("replacement", "server"));
        old.Active();
        Assert.Equal(ConnectionPhase.CleanupBlocked, fixture.Owner.Snapshot.Phase);
        Assert.Equal(1, fixture.Factory.CreationCount);
        old.Finish(ConnectionEndReason.TransientNetworkFailure);
        var next = await fixture.Factory.NextRunningAsync();
        Assert.Equal("replacement", next.Target.AccountKey);
        Assert.True(old.Released.Task.IsCompletedSuccessfully);
        Assert.Equal(1, fixture.Factory.MaximumLiveOwners);
    }

    [Fact]
    public async Task CleanupTimeoutCancelsQueuedAutomaticReconnectIntent()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HonorCancellation = false;
        Task lost = fixture.Owner.SetNetworkAvailableAsync(false);
        (await fixture.Delay.TakeAsync(CleanupTimeout)).Complete();
        await lost.WaitAsync(TestTimeout);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
        await PhaseAsync(fixture.Owner, ConnectionPhase.Stopped);
        Assert.Equal(1, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task DisposeIsBoundedEvenIfAdapterIgnoresCancellation()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HonorCancellation = false;
        Task disposing = fixture.Owner.DisposeAsync().AsTask();
        (await fixture.Delay.TakeAsync(CleanupTimeout)).Complete();
        await disposing.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.CleanupBlocked, fixture.Owner.Snapshot.Phase);
        await Assert.ThrowsAsync<ObjectDisposedException>(() => fixture.Owner.StartAsync(new("two", "server")));
        adapter.Finish(ConnectionEndReason.UserStopped);
        await adapter.Released.Task.WaitAsync(TestTimeout);
        await fixture.Owner.StopAsync();
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
        Assert.Equal(ConnectionEndReason.Disposed, fixture.Owner.Snapshot.Reason);
    }

    [Fact]
    public async Task FailedDisposeBlocksFurtherOwnersAndNeverExposesExceptionText()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.ThrowOnDispose = true;
        await fixture.Owner.StopAsync().WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.CleanupBlocked, fixture.Owner.Snapshot.Phase);
        Assert.Equal(ConnectionEndReason.AdapterFailure, fixture.Owner.Snapshot.Reason);
        Assert.DoesNotContain("synthetic-secret", fixture.Owner.Snapshot.ToString());
        await fixture.Owner.StartAsync(new("two", "server"));
        Assert.Equal(ConnectionPhase.CleanupBlocked, fixture.Owner.Snapshot.Phase);
        Assert.Equal(1, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task NaturalEndCannotRetryUntilDisposeCompletes()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HoldRelease = true;
        adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
        await adapter.DisposalStarted.Task.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.Stopping, fixture.Owner.Snapshot.Phase);
        Assert.Equal(1, fixture.Factory.CreationCount);
        adapter.Release();
        await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
        (await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1))).Complete();
        await fixture.Factory.NextRunningAsync();
        Assert.Equal(1, fixture.Factory.MaximumLiveOwners);
    }

    [Fact]
    public async Task RetryBudgetIsFiniteAndActiveDoesNotResetIt()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        long generation = fixture.Owner.Snapshot.Generation;
        foreach (int seconds in new[] { 1, 2, 2, 2, 2 })
        {
            adapter.Active();
            adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
            await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
            (await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(seconds))).Complete();
            adapter = await fixture.Factory.NextRunningAsync();
            Assert.Equal(generation, fixture.Owner.Snapshot.Generation);
        }
        adapter.Active();
        adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
        await PhaseAsync(fixture.Owner, ConnectionPhase.Failed);
        Assert.Equal(ConnectionEndReason.RetryLimitReached, fixture.Owner.Snapshot.Reason);
        Assert.Equal(5, fixture.Owner.Snapshot.RetryCount);
        Assert.Equal(6, fixture.Factory.CreationCount);
        await fixture.Owner.SetNetworkAvailableAsync(false);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        Assert.Equal(6, fixture.Factory.CreationCount);

        await fixture.Owner.StartAsync(new("account-one", "server"));
        await fixture.Factory.NextRunningAsync();
        Assert.True(fixture.Owner.Snapshot.Generation > generation);
        Assert.Equal(0, fixture.Owner.Snapshot.RetryCount);
    }

    [Fact]
    public async Task ManualStopRejectsLateRetryTimerEvenWhenDelayIgnoresCancellation()
    {
        await using var fixture = new LifecycleFixture();
        fixture.Delay.HonorCancellation = false;
        var adapter = await fixture.StartAsync();
        adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
        await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
        var retry = await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1));
        await fixture.Owner.StopAsync();
        retry.Complete();
        await fixture.Owner.SetNetworkAvailableAsync(true);
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
        Assert.Equal(1, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task NetworkLossDuringRetryInvalidatesOldTimerAndRestorationDoesNotDuplicateAttempts()
    {
        await using var fixture = new LifecycleFixture();
        fixture.Delay.HonorCancellation = false;
        var adapter = await fixture.StartAsync();
        adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
        await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
        var oldTimer = await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1));
        await fixture.Owner.SetNetworkAvailableAsync(false);
        oldTimer.Complete();
        Assert.Equal(ConnectionPhase.WaitingForNetwork, fixture.Owner.Snapshot.Phase);
        await Task.WhenAll(Enumerable.Range(0, 20).Select(_ => fixture.Owner.SetNetworkAvailableAsync(true)));
        var currentTimer = await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1));
        currentTimer.Complete();
        await fixture.Factory.NextRunningAsync();
        Assert.Equal(2, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task NetworkCanReturnBeforeCleanupWithoutOverlappingSessions()
    {
        await using var fixture = new LifecycleFixture();
        var old = await fixture.StartAsync();
        old.Active();
        old.HoldRelease = true;
        Task lost = fixture.Owner.SetNetworkAvailableAsync(false);
        await old.DisposalStarted.Task.WaitAsync(TestTimeout);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        Assert.Equal(1, fixture.Factory.CreationCount);
        Assert.Equal(ConnectionEndReason.NetworkUnavailable, fixture.Owner.Snapshot.Reason);
        old.Release();
        await lost.WaitAsync(TestTimeout);
        await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
        Assert.Equal(ConnectionEndReason.NetworkUnavailable, fixture.Owner.Snapshot.Reason);
        (await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1))).Complete();
        await fixture.Factory.NextRunningAsync();
        Assert.Equal(1, fixture.Factory.MaximumLiveOwners);
    }

    [Fact]
    public async Task NetworkFlappingUsesTheSameFiniteRetryBudget()
    {
        await using var fixture = new LifecycleFixture(maximumRetries: 1);
        var first = await fixture.StartAsync();
        first.Active();
        await fixture.Owner.SetNetworkAvailableAsync(false).WaitAsync(TestTimeout);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        (await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1))).Complete();
        var second = await fixture.Factory.NextRunningAsync();
        second.Active();
        await fixture.Owner.SetNetworkAvailableAsync(false).WaitAsync(TestTimeout);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        Assert.Equal(ConnectionPhase.Failed, fixture.Owner.Snapshot.Phase);
        Assert.Equal(ConnectionEndReason.RetryLimitReached, fixture.Owner.Snapshot.Reason);
        Assert.Equal(2, fixture.Factory.CreationCount);
    }

    [Theory]
    [InlineData(ConnectionEndReason.AuthenticationRejected, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.ResourceHeld, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.RemoteClosed, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.AdapterFailure, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.CoreUnavailable, ConnectionPhase.Unavailable)]
    [InlineData(ConnectionEndReason.UserStopped, ConnectionPhase.Stopped)]
    public async Task NonTransientResultsNeedExplicitNewStart(ConnectionEndReason reason, ConnectionPhase phase)
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.Finish(reason);
        await PhaseAsync(fixture.Owner, phase);
        Assert.Equal(reason, fixture.Owner.Snapshot.Reason);
        await fixture.Owner.SetNetworkAvailableAsync(false);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        Assert.Equal(1, fixture.Factory.CreationCount);
        Assert.Equal(phase, fixture.Owner.Snapshot.Phase);
    }

    [Theory]
    [InlineData(ConnectionEndReason.AuthenticationRejected, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.ResourceHeld, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.RemoteClosed, ConnectionPhase.Failed)]
    [InlineData(ConnectionEndReason.CoreUnavailable, ConnectionPhase.Unavailable)]
    public async Task KnownTerminalResultWinsOverNetworkLossDuringCleanup(ConnectionEndReason reason, ConnectionPhase phase)
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HoldRelease = true;
        adapter.Finish(reason);
        await adapter.DisposalStarted.Task.WaitAsync(TestTimeout);
        Task lost = fixture.Owner.SetNetworkAvailableAsync(false);
        await fixture.Owner.SetNetworkAvailableAsync(true);
        adapter.Release();
        await lost.WaitAsync(TestTimeout);
        Assert.Equal(phase, fixture.Owner.Snapshot.Phase);
        Assert.Equal(reason, fixture.Owner.Snapshot.Reason);
        Assert.Equal(1, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task SynchronousFactoryFailureIsObservedAndRedacted()
    {
        await using var fixture = new LifecycleFixture();
        fixture.Factory.ThrowOnCreate = true;
        await fixture.Owner.SetNetworkAvailableAsync(true);
        await fixture.Owner.StartAsync(new("one", "server"));
        await PhaseAsync(fixture.Owner, ConnectionPhase.Failed);
        Assert.Equal(ConnectionEndReason.AdapterFailure, fixture.Owner.Snapshot.Reason);
        Assert.DoesNotContain("synthetic-secret", fixture.Owner.Snapshot.ToString());
        Assert.Equal(1, fixture.Factory.CreationCount);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task RunFailureAndUnexpectedCancellationAreTerminalAndStillDisposed(bool canceled)
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.Fail(canceled ? new OperationCanceledException("synthetic-secret") :
            new InvalidOperationException("synthetic-secret"));
        await PhaseAsync(fixture.Owner, ConnectionPhase.Failed);
        Assert.Equal(ConnectionEndReason.AdapterFailure, fixture.Owner.Snapshot.Reason);
        Assert.Equal(1, adapter.DisposeCount);
        Assert.DoesNotContain("synthetic-secret", fixture.Owner.Snapshot.ToString());
    }

    [Fact]
    public async Task AttemptIdentityRejectsLateActiveWithinSameSessionGeneration()
    {
        await using var fixture = new LifecycleFixture();
        var old = await fixture.StartAsync();
        long generation = fixture.Owner.Snapshot.Generation;
        long attempt = fixture.Owner.Snapshot.AttemptId;
        old.Finish(ConnectionEndReason.TransientNetworkFailure);
        await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
        (await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1))).Complete();
        var next = await fixture.Factory.NextRunningAsync();
        old.Active();
        Assert.Equal(generation, fixture.Owner.Snapshot.Generation);
        Assert.True(fixture.Owner.Snapshot.AttemptId > attempt);
        Assert.Equal(ConnectionPhase.Connecting, fixture.Owner.Snapshot.Phase);
        next.Active();
        Assert.Equal(ConnectionPhase.Active, fixture.Owner.Snapshot.Phase);
    }

    [Fact]
    public async Task ConnectTimeoutCancelsAndReleasesBeforeRetrying()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HoldRelease = true;
        (await fixture.Delay.TakeAsync(ConnectTimeout)).Complete();
        await adapter.DisposalStarted.Task.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.Stopping, fixture.Owner.Snapshot.Phase);
        Assert.Equal(ConnectionEndReason.ConnectTimedOut, fixture.Owner.Snapshot.Reason);
        Assert.Equal(1, fixture.Factory.CreationCount);
        adapter.Active();
        Assert.Equal(ConnectionPhase.Stopping, fixture.Owner.Snapshot.Phase);
        adapter.Release();
        await PhaseAsync(fixture.Owner, ConnectionPhase.RetryWaiting);
        Assert.Equal(ConnectionEndReason.ConnectTimedOut, fixture.Owner.Snapshot.Reason);
        (await fixture.Delay.TakeAsync(TimeSpan.FromSeconds(1))).Complete();
        await fixture.Factory.NextRunningAsync();
        Assert.Equal(1, fixture.Factory.MaximumLiveOwners);
    }

    [Fact]
    public async Task IgnoredConnectCancellationEntersCleanupBlockedWithoutRetrying()
    {
        await using var fixture = new LifecycleFixture();
        var adapter = await fixture.StartAsync();
        adapter.HonorCancellation = false;
        (await fixture.Delay.TakeAsync(ConnectTimeout)).Complete();
        await adapter.CancellationSeen.Task.WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.Stopping, fixture.Owner.Snapshot.Phase);
        (await fixture.Delay.TakeAsync(CleanupTimeout)).Complete();
        await PhaseAsync(fixture.Owner, ConnectionPhase.CleanupBlocked);
        adapter.Finish(ConnectionEndReason.TransientNetworkFailure);
        await PhaseAsync(fixture.Owner, ConnectionPhase.Stopped);
        Assert.Equal(1, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task ActiveSessionSurvivesLateConnectWatchdog()
    {
        await using var fixture = new LifecycleFixture();
        fixture.Delay.HonorCancellation = false;
        var adapter = await fixture.StartAsync();
        var timer = await fixture.Delay.TakeAsync(ConnectTimeout);
        adapter.Active();
        timer.Complete();
        Assert.Equal(ConnectionPhase.Active, fixture.Owner.Snapshot.Phase);
        Assert.False(adapter.CancellationSeen.Task.IsCompleted);
    }

    [Fact]
    public async Task OldConnectWatchdogCannotCancelReplacement()
    {
        await using var fixture = new LifecycleFixture();
        fixture.Delay.HonorCancellation = false;
        var old = await fixture.StartAsync();
        var timer = await fixture.Delay.TakeAsync(ConnectTimeout);
        await fixture.Owner.StartAsync(new("two", "server")).WaitAsync(TestTimeout);
        var next = await fixture.Factory.NextRunningAsync();
        timer.Complete();
        Assert.Equal(ConnectionPhase.Connecting, fixture.Owner.Snapshot.Phase);
        Assert.False(next.CancellationSeen.Task.IsCompleted);
        Assert.True(old.Released.Task.IsCompletedSuccessfully);
    }

    [Fact]
    public async Task ThrowingObserverDoesNotBreakOtherObserversOrOwner()
    {
        await using var fixture = new LifecycleFixture();
        using var broken = fixture.Owner.Subscribe(_ => throw new InvalidOperationException("synthetic-secret"));
        var received = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var healthy = fixture.Owner.Subscribe(state =>
        {
            if (state.Phase == ConnectionPhase.Active) received.TrySetResult();
        });
        var adapter = await fixture.StartAsync();
        adapter.Active();
        await received.Task.WaitAsync(TestTimeout);
        await fixture.Owner.StopAsync().WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
    }

    [Fact]
    public async Task UnsubscribeDropsQueuedCallbacksBehindSlowObserver()
    {
        await using var fixture = new LifecycleFixture();
        using var release = new ManualResetEventSlim();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var slow = fixture.Owner.Subscribe(_ =>
        {
            entered.TrySetResult();
            release.Wait(TestTimeout);
        });
        await entered.Task.WaitAsync(TestTimeout);
        int calls = 0;
        var removed = fixture.Owner.Subscribe(_ => Interlocked.Increment(ref calls));
        removed.Dispose();
        await fixture.Owner.StartAsync(new("one", "server"));
        var caughtUp = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using var tail = fixture.Owner.Subscribe(_ => caughtUp.TrySetResult());
        release.Set();
        await caughtUp.Task.WaitAsync(TestTimeout);
        Assert.Equal(0, Volatile.Read(ref calls));
    }

    [Fact]
    public async Task SlowObserverReceivesLatestSnapshotWithoutUnboundedBacklog()
    {
        await using var fixture = new LifecycleFixture();
        using var release = new ManualResetEventSlim();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var caughtUp = new TaskCompletionSource<ConnectionSnapshot>(TaskCreationOptions.RunContinuationsAsynchronously);
        int calls = 0;
        using var subscription = fixture.Owner.Subscribe(state =>
        {
            if (Interlocked.Increment(ref calls) == 1)
            {
                entered.TrySetResult();
                release.Wait(TestTimeout);
            }
            else caughtUp.TrySetResult(state);
        });
        await entered.Task.WaitAsync(TestTimeout);
        for (int index = 0; index < 30; index++)
        {
            await fixture.Owner.StartAsync(new($"selection-{index}", "server"));
            await fixture.Owner.StopAsync();
        }
        ConnectionSnapshot expected = fixture.Owner.Snapshot;
        release.Set();
        Assert.Equal(expected, await caughtUp.Task.WaitAsync(TestTimeout));
        Assert.Equal(2, Volatile.Read(ref calls));
        Assert.Equal(0, fixture.Factory.CreationCount);
    }

    [Fact]
    public async Task ObserverCanRequestStopWithoutDeadlockingCoordinator()
    {
        await using var fixture = new LifecycleFixture();
        var stopping = new TaskCompletionSource<Task>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var subscriber = fixture.Owner.Subscribe(state =>
        {
            if (state.Phase == ConnectionPhase.Active) stopping.TrySetResult(fixture.Owner.StopAsync());
        });
        var adapter = await fixture.StartAsync();
        adapter.Active();
        await (await stopping.Task.WaitAsync(TestTimeout)).WaitAsync(TestTimeout);
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
    }

    [Fact]
    public async Task ConcurrentSelectionChangesNeverCreateTwoUndisposedOwners()
    {
        await using var fixture = new LifecycleFixture();
        await fixture.StartAsync();
        await Task.WhenAll(Enumerable.Range(0, 30).Select(index =>
            Task.Run(() => fixture.Owner.StartAsync(new($"account-{index}", "server"))))).WaitAsync(TestTimeout);
        await fixture.Owner.StopAsync().WaitAsync(TestTimeout);
        Assert.Equal(1, fixture.Factory.MaximumLiveOwners);
        Assert.Equal(ConnectionPhase.Stopped, fixture.Owner.Snapshot.Phase);
    }

    [Fact]
    public void TargetAndSnapshotDiagnosticFormattingExcludeIdentity()
    {
        var target = new ConnectionTarget("synthetic-private-account", "synthetic-private-endpoint");
        Assert.Equal("ConnectionTarget", target.ToString());
        var snapshot = new ConnectionSnapshot(1, 2, ConnectionPhase.Failed, 0, ConnectionEndReason.AuthenticationRejected);
        Assert.DoesNotContain("synthetic-private", snapshot.ToString());
    }
}
