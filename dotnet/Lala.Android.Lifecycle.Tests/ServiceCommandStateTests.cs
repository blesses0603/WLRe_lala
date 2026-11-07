using Lala.Android.Platform;
using Xunit;

namespace Lala.Android.Lifecycle.Tests;

public sealed class ServiceCommandStateTests
{
    [Fact]
    public void InitialStoppedSnapshotCannotFinishAnAcceptedStart()
    {
        var commands = new ServiceCommandState();
        var start = commands.BeginStart();
        Assert.False(commands.CanFinish(connectionRunning: false));
        Assert.True(commands.CompleteStart(start));
        Assert.True(commands.CanFinish(connectionRunning: false));
        Assert.False(commands.CanFinish(connectionRunning: true));
    }

    [Fact]
    public void OldStartFinallyCannotClearReplacementStart()
    {
        var commands = new ServiceCommandState();
        var first = commands.BeginStart();
        var second = commands.BeginStart();
        Assert.False(commands.CompleteStart(first));
        Assert.False(commands.CanFinish(connectionRunning: false));
        Assert.True(commands.CompleteStart(second));
        Assert.True(commands.CanFinish(connectionRunning: false));
    }

    [Fact]
    public void StopCancelsPendingStartAndRejectsItsLateCompletion()
    {
        var commands = new ServiceCommandState();
        var start = commands.BeginStart();
        var stop = commands.BeginStop();
        Assert.False(commands.StartPending);
        Assert.False(commands.IsCurrent(start));
        Assert.True(commands.IsCurrent(stop));
        Assert.False(commands.CompleteStart(start));
    }

    [Fact]
    public void DelayedStopFromOldEpochDoesNotMatchNewStart()
    {
        var commands = new ServiceCommandState();
        var stop = commands.BeginStop();
        var replacement = commands.BeginStart();
        Assert.False(commands.IsCurrent(stop));
        Assert.True(commands.IsCurrent(replacement));
        Assert.False(commands.CanFinish(connectionRunning: false));
    }

    [Fact]
    public void ReplacementOwnerRejectsOldDeferredCommands()
    {
        var ownership = new ServiceOwnerLease();
        var first = ownership.Acquire();
        var second = ownership.Acquire();
        var oldStopCalls = 0;
        Assert.Null(ownership.Invoke(first, () => { oldStopCalls++; return Task.CompletedTask; }));
        Assert.Equal(0, oldStopCalls);
        Assert.False(ownership.IsCurrent(first));
        Assert.True(ownership.IsCurrent(second));
    }

    [Fact]
    public async Task CleanupTaskDoesNotHoldLeaseOrMutateReplacementOwnerOnCompletion()
    {
        var ownership = new ServiceOwnerLease();
        var first = ownership.Acquire();
        var cleanup = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var stopCalls = 0;
        var pending = ownership.Invoke(first, () => { stopCalls++; return cleanup.Task; });
        var second = ownership.Acquire();
        Assert.True(ownership.IsCurrent(second));
        Assert.False(pending!.IsCompleted);
        cleanup.SetResult();
        await pending.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(1, stopCalls);
        Assert.True(ownership.IsCurrent(second));
        Assert.Null(ownership.Invoke(first, () => { stopCalls++; return Task.CompletedTask; }));
        Assert.Equal(1, stopCalls);
    }

    [Fact]
    public async Task AcquiringNewOwnerCannotRaceBetweenLeaseCheckAndMutation()
    {
        var ownership = new ServiceOwnerLease();
        var first = ownership.Acquire();
        using var releaseMutation = new ManualResetEventSlim();
        var enteredMutation = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var attemptingAcquire = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var mutations = 0;
        var mutation = Task.Run(() => ownership.Invoke(first, () =>
        {
            enteredMutation.SetResult();
            Assert.True(releaseMutation.Wait(TimeSpan.FromSeconds(5)));
            Interlocked.Increment(ref mutations);
            return Task.CompletedTask;
        }));
        await enteredMutation.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var replacement = Task.Run(() => { attemptingAcquire.SetResult(); return ownership.Acquire(); });
        try
        {
            await attemptingAcquire.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(replacement.IsCompleted);
        }
        finally { releaseMutation.Set(); }
        await mutation.WaitAsync(TimeSpan.FromSeconds(5));
        var second = await replacement.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(ownership.IsCurrent(second));
        Assert.Equal(1, mutations);
        Assert.Null(ownership.Invoke(first, () => { Interlocked.Increment(ref mutations); return Task.CompletedTask; }));
        Assert.Equal(1, mutations);
    }
}
