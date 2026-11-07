using System.Diagnostics;

namespace Lala.Core.State;

/// <summary>Pure synchronous port of network/state_updates.py's StatePublisher for local snapshots.
/// Observations apply immediately; only display callbacks coalesce. Flush observes the interval,
/// not a forced send. Elapsed time is sampled again after the callback. No timers or UI dispatch.
/// Construct and call on the same owner thread as the supplied coordinator. Exceptions propagate,
/// leaving a pending publication and the previous last-success time, as in Python.</summary>
public sealed class LocalStatePublisher
{
    private readonly Thread writer = Thread.CurrentThread;
    private readonly Action<LocalStateSnapshot> callback;
    private readonly Func<double> clock;
    private readonly double interval;
    private double? last;
    private bool pending;

    public LocalStatePublisher(Action<LocalStateSnapshot> callback, double intervalSeconds,
        Func<double>? clock = null)
    {
        ArgumentNullException.ThrowIfNull(callback);
        this.callback = callback;
        interval = intervalSeconds;
        this.clock = clock ?? (() => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency);
    }

    public bool Pending { get { AssertWriter(); return pending; } }
    public double? LastPublishedAt { get { AssertWriter(); return last; } }

    public void Publish(LocalStateCoordinator state, bool force = false)
    {
        AssertWriter();
        ArgumentNullException.ThrowIfNull(state);
        state.AssertWriter();
        pending = true;
        var now = clock();
        if (force || last is null || now - last.Value >= interval)
        {
            callback(state.Snapshot());
            last = clock();
            pending = false;
        }
    }

    public void Flush(LocalStateCoordinator state)
    {
        AssertWriter();
        ArgumentNullException.ThrowIfNull(state);
        state.AssertWriter();
        if (pending) Publish(state);
    }

    private void AssertWriter()
    {
        if (!ReferenceEquals(Thread.CurrentThread, writer))
            throw new InvalidOperationException("Local state publication must run on its owning thread.");
    }
}
