using System.Collections.Concurrent;
using System.Threading.Channels;
using Xunit;

namespace Lala.Android.Lifecycle.Tests;

internal sealed class LifecycleFixture : IAsyncDisposable
{
    public static readonly TimeSpan TestTimeout = TimeSpan.FromSeconds(10);
    public static readonly TimeSpan ConnectTimeout = TimeSpan.FromMinutes(1);
    public static readonly TimeSpan CleanupTimeout = TimeSpan.FromHours(1);
    public FakeFactory Factory { get; } = new();
    public ControlledDelay Delay { get; } = new();
    public ConnectionCoordinator Owner { get; }

    public LifecycleFixture(int maximumRetries = 5, bool available = true)
    {
        Factory.IsAvailable = available;
        Owner = new ConnectionCoordinator(Factory, new ConnectionPolicy
        {
            MaximumRetries = maximumRetries,
            InitialRetryDelay = TimeSpan.FromSeconds(1),
            MaximumRetryDelay = TimeSpan.FromSeconds(2),
            ConnectTimeout = ConnectTimeout,
            CleanupTimeout = CleanupTimeout
        }, Delay);
    }

    public async Task<FakeAdapter> StartAsync(string account = "account-one")
    {
        await Owner.SetNetworkAvailableAsync(true);
        await Owner.StartAsync(new(account, "server"));
        return await Factory.NextRunningAsync();
    }

    public async ValueTask DisposeAsync()
    {
        Task disposing = Owner.DisposeAsync().AsTask();
        Factory.ReleaseAll();
        Delay.CompleteAll();
        await disposing.WaitAsync(TestTimeout);
    }

    public static async Task<ConnectionSnapshot> WaitForAsync(ConnectionCoordinator owner,
        Func<ConnectionSnapshot, bool> predicate)
    {
        var completion = new TaskCompletionSource<ConnectionSnapshot>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var subscription = owner.Subscribe(state =>
        {
            if (predicate(state)) completion.TrySetResult(state);
        });
        return await completion.Task.WaitAsync(TestTimeout);
    }

    public static Task<ConnectionSnapshot> PhaseAsync(ConnectionCoordinator owner, ConnectionPhase phase)
        => WaitForAsync(owner, state => state.Phase == phase);
}

internal sealed class FakeFactory : IConnectionAdapterFactory
{
    private readonly Channel<FakeAdapter> created = Channel.CreateUnbounded<FakeAdapter>();
    private readonly ConcurrentBag<FakeAdapter> adapters = [];
    private int count, liveOwners, maximumLiveOwners;
    public bool IsAvailable { get; set; } = true;
    public bool ThrowOnCreate { get; set; }
    public Action<FakeAdapter>? Configure { get; set; }
    public int CreationCount => Volatile.Read(ref count);
    public int MaximumLiveOwners => Volatile.Read(ref maximumLiveOwners);

    public IConnectionAdapter Create(ConnectionTarget target)
    {
        Interlocked.Increment(ref count);
        if (ThrowOnCreate) throw new InvalidOperationException("synthetic-secret-in-factory-error");
        int live = Interlocked.Increment(ref liveOwners);
        int previous;
        do
        {
            previous = Volatile.Read(ref maximumLiveOwners);
            if (previous >= live) break;
        } while (Interlocked.CompareExchange(ref maximumLiveOwners, live, previous) != previous);
        var adapter = new FakeAdapter(target, () => Interlocked.Decrement(ref liveOwners));
        Configure?.Invoke(adapter);
        adapters.Add(adapter);
        created.Writer.TryWrite(adapter);
        return adapter;
    }

    public async Task<FakeAdapter> NextRunningAsync()
    {
        FakeAdapter adapter = await created.Reader.ReadAsync().AsTask().WaitAsync(LifecycleFixture.TestTimeout);
        await adapter.Started.Task.WaitAsync(LifecycleFixture.TestTimeout);
        return adapter;
    }

    public void ReleaseAll()
    {
        foreach (var adapter in adapters)
        {
            adapter.Finish(ConnectionEndReason.UserStopped);
            adapter.Release();
        }
    }
}

internal sealed class FakeAdapter(ConnectionTarget target, Action released) : IConnectionAdapter
{
    private readonly TaskCompletionSource<ConnectionEndReason> ended = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly TaskCompletionSource release = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private Action? onActive;
    private int disposeCount;
    public ConnectionTarget Target { get; } = target;
    public CancellationToken Token { get; private set; }
    public bool HonorCancellation { get; set; } = true;
    public bool HoldRelease { get; set; }
    public bool ThrowOnDispose { get; set; }
    public TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource CancellationSeen { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource DisposalStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource Released { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public int DisposeCount => Volatile.Read(ref disposeCount);

    public async Task<ConnectionEndReason> RunAsync(Action callback, CancellationToken cancellationToken)
    {
        Token = cancellationToken;
        onActive = callback;
        using var registration = cancellationToken.Register(() =>
        {
            CancellationSeen.TrySetResult();
            if (HonorCancellation) ended.TrySetCanceled(cancellationToken);
        });
        Started.TrySetResult();
        return await ended.Task;
    }

    public void Active() => onActive?.Invoke();
    public void Finish(ConnectionEndReason result) => ended.TrySetResult(result);
    public void Fail(Exception exception) => ended.TrySetException(exception);
    public void Release() => release.TrySetResult();

    public async ValueTask DisposeAsync()
    {
        Interlocked.Increment(ref disposeCount);
        DisposalStarted.TrySetResult();
        if (ThrowOnDispose) throw new InvalidOperationException("synthetic-secret-in-disposal-error");
        if (HoldRelease) await release.Task;
        released();
        Released.TrySetResult();
    }
}

internal sealed class ControlledDelay : IConnectionDelay
{
    private readonly object gate = new();
    private readonly List<PendingDelay> pending = [];
    private readonly SemaphoreSlim added = new(0);
    public bool HonorCancellation { get; set; } = true;

    public async Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken)
    {
        var item = new PendingDelay(duration);
        bool honorCancellation = HonorCancellation;
        using var registration = cancellationToken.Register(() =>
        {
            item.CancellationSeen.TrySetResult();
            if (honorCancellation) item.Completion.TrySetCanceled(cancellationToken);
        });
        lock (gate) pending.Add(item);
        added.Release();
        await item.Completion.Task;
    }

    public async Task<PendingDelay> TakeAsync(TimeSpan duration)
    {
        using var timeout = new CancellationTokenSource(LifecycleFixture.TestTimeout);
        while (true)
        {
            lock (gate)
            {
                var result = pending.FirstOrDefault(item => !item.Claimed &&
                    item.Duration == duration && !item.Completion.Task.IsCompleted);
                if (result is not null)
                {
                    result.Claimed = true;
                    return result;
                }
            }
            await added.WaitAsync(timeout.Token);
        }
    }

    public void CompleteAll()
    {
        lock (gate)
            foreach (var item in pending) item.Complete();
    }
}

internal sealed class PendingDelay(TimeSpan duration)
{
    public TimeSpan Duration { get; } = duration;
    public bool Claimed { get; set; }
    public TaskCompletionSource Completion { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource CancellationSeen { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public void Complete() => Completion.TrySetResult();
}
