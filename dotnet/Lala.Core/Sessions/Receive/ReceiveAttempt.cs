using System.Threading.Channels;
using Lala.Core.Protocol;
using Lala.Core.Social.Ark;
using Lala.Core.State;

namespace Lala.Core.Sessions.Receive;

/// <summary>An already-created byte source. Deliberately has no dial, login or write operation.</summary>
internal interface IReceiveTransport : IAsyncDisposable
{
    ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken);
}

/// <summary>Optional synchronous revocation of send admission. Implementations must only
/// change owned state: no I/O, user callbacks, waits for asynchronous work, or exceptions.
/// Physical cancellation/disposal still runs outside the receive gate.</summary>
internal interface IReceiveTransportRetirement
{
    void Retire();
}

internal enum ReceiveStage { Created, Running, Ending, Ended }
internal enum ReceiveEnd
{
    Completed, Cancelled, Disposed, ReadFailed, InvalidFrame, TruncatedFrame,
    InvalidPayload, ObservationInputFailed, MissingArkRuntime, ReductionFailed, CleanupFailed, EventHandlerFailed
}

/// <summary>Revision counts successful commits only. Status is not the observed game phase.
/// Attempt identity must be checked when consuming a saved publication after replacement.</summary>
internal sealed record ReceivePublication(Guid Attempt, long Revision, ReceiveStage Stage,
    ServiceStateSnapshot Snapshot, ReceiveEnd? End)
{
    public bool ResourceHeld => true;
}

internal sealed record ReceiveResult(ReceivePublication Publication, ReceiveEnd End, bool ResourcesReleased);
internal sealed class ReceiveCleanupException() : Exception("Receive transport cleanup failed.");

/// <summary>
/// Internal, one-shot receive composition, not a usable authenticated account session.
/// The constructor performs no I/O or callbacks. The first RunAsync token owns cancellation;
/// repeated calls return the same completion. Disposing before RunAsync never starts a reader.
/// An actual dedicated thread owns the decoder and coordinator for the entire attempt.
/// Chunk buffering is bounded; observer delivery coalesces to one pending successful commit.
/// Observers run separately, and their exceptions cannot stop reception. An already-admitted
/// callback can finish after retirement; no queued callback is admitted after retirement.
/// The optional pre-commit hook is lossless and serialized on the writer; it runs outside
/// the state lock and must finish before commit. Retirement discards its late result.
/// Completion waits for admitted hooks and observer callbacks too. Latest also exposes immutable lifecycle status;
/// commit callbacks are not a lossless event log or a terminal-status notification channel.
/// Cancellation/disposal retires identity synchronously, before cancellation callbacks or
/// transport disposal run. Completion waits for actual read, writer-thread, observer and
/// transport termination. A noncooperative participant keeps completion pending.
/// </summary>
internal sealed class ReceiveAttempt : IAsyncDisposable
{
    private sealed record Chunk(byte[] Bytes, int Count, bool Eof = false);
    private readonly object gate = new();
    private readonly IReceiveTransport transport;
    private readonly int rxXor;
    private readonly Func<double> clock;
    private readonly Func<ServiceStateSnapshot, double, ServiceObservationInputs> observe;
    private readonly Action<ReceivePublication>? observer;
    private readonly Func<ServerEvent, CancellationToken, ValueTask>? beforeCommit;
    private readonly int readSize;
    private readonly Channel<Chunk> chunks;
    private readonly Channel<ReceivePublication> publications = Channel.CreateBounded<ReceivePublication>(
        new BoundedChannelOptions(1) { FullMode = BoundedChannelFullMode.DropOldest, SingleReader = true, SingleWriter = true });
    private readonly CancellationTokenSource stop = new();
    private ReceivePublication latest;
    private Task<ReceiveResult>? completion;
    private Task? disposalCompletion;
    private Task? transportDisposal;
    private Task? cancellation;
    private bool runRequested;
    private bool retired;
    private ReceiveEnd? end;

    public ReceiveAttempt(IReceiveTransport transport, int rxXor, Func<double> clock,
        Func<ServiceStateSnapshot, double, ServiceObservationInputs> observe,
        Action<ReceivePublication>? observer = null, ServiceStateSnapshot? initial = null,
        int readSize = 4096, int bufferedChunks = 4,
        Func<ServerEvent, CancellationToken, ValueTask>? beforeCommit = null)
    {
        ArgumentNullException.ThrowIfNull(transport);
        ArgumentNullException.ThrowIfNull(clock);
        ArgumentNullException.ThrowIfNull(observe);
        WireCodec.ValidateKey(rxXor);
        if (readSize is < 1 or > 65536) throw new ArgumentOutOfRangeException(nameof(readSize));
        if (bufferedChunks is < 1 or > 256) throw new ArgumentOutOfRangeException(nameof(bufferedChunks));
        this.transport = transport; this.rxXor = rxXor; this.clock = clock;
        this.observe = observe; this.observer = observer; this.readSize = readSize;
        this.beforeCommit = beforeCommit;
        chunks = Channel.CreateBounded<Chunk>(new BoundedChannelOptions(bufferedChunks)
            { FullMode = BoundedChannelFullMode.Wait, SingleReader = true, SingleWriter = true });
        latest = new(Guid.NewGuid(), 0, ReceiveStage.Created, initial ?? new(), null);
    }

    public ReceivePublication Latest { get { lock (gate) return latest; } }
    public bool IsCurrent(Guid attempt)
    {
        lock (gate) return latest.Attempt == attempt && !retired && latest.Stage != ReceiveStage.Ended;
    }

    public Task<ReceiveResult> RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            if (completion is not null) return completion;
            runRequested = true;
            latest = latest with { Stage = ReceiveStage.Running };
            return completion = Task.Run(() => ExecuteAsync(cancellationToken));
        }
    }

    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            if (latest.Stage != ReceiveStage.Ended) RetireLocked(ReceiveEnd.Disposed);
            else retired = true;
            completion ??= Task.Run(() => ExecuteAsync(CancellationToken.None));
            disposalCompletion ??= VerifyCleanupAsync(completion);
            return new(disposalCompletion);
        }
    }

    private static async Task VerifyCleanupAsync(Task<ReceiveResult> task)
    {
        if (!(await task.ConfigureAwait(false)).ResourcesReleased) throw new ReceiveCleanupException();
    }

    private void Retire(ReceiveEnd reason) { lock (gate) RetireLocked(reason); }
    private void RetireLocked(ReceiveEnd reason)
    {
        if (latest.Stage == ReceiveStage.Ended) return;
        retired = true;
        (transport as IReceiveTransportRetirement)?.Retire();
        end ??= reason;
        latest = latest with { Stage = ReceiveStage.Ending, End = end };
        // Task.Run keeps transport/cancellation callbacks outside gate, including synchronous ones.
        StartCancellationLocked();
        StartTransportDisposalLocked();
    }

    private Task StartCancellationLocked() => cancellation ??= Task.Run(async () =>
        {
            try { await stop.CancelAsync().ConfigureAwait(false); }
            catch (Exception) { /* Cancellation callback faults cannot substitute for cleanup. */ }
        });

    private Task StartTransportDisposalLocked() => transportDisposal ??=
        Task.Run(async () => await transport.DisposeAsync().ConfigureAwait(false));

    private async Task<ReceiveResult> ExecuteAsync(CancellationToken cancellationToken)
    {
        using var registration = cancellationToken.UnsafeRegister(static value =>
            ((ReceiveAttempt)value!).Retire(ReceiveEnd.Cancelled), this);
        bool start;
        lock (gate) start = runRequested && !retired;
        Task deliveries = Task.CompletedTask;
        if (start)
        {
            var writerDone = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var writer = new Thread(() => WriteLoop(writerDone)) { IsBackground = true, Name = "Lala receive state writer" };
            deliveries = Task.Run(DeliverAsync);
            writer.Start();
            await ReadAsync().ConfigureAwait(false);
            await writerDone.Task.ConfigureAwait(false);
            writer.Join(); // A completion signal in a finally block alone does not prove thread termination.
        }
        Task cleanup;
        Task cancel;
        lock (gate)
        {
            latest = latest with { Stage = ReceiveStage.Ending, End = end };
            cleanup = StartTransportDisposalLocked();
            // Always establish this task before cleanup awaits. Retirement can race EOF
            // cleanup, and must never create an unawaited cancellation callback worker.
            cancel = StartCancellationLocked();
        }
        bool released = true;
        try { await cleanup.ConfigureAwait(false); }
        catch (Exception) { released = false; }
        await cancel.ConfigureAwait(false);
        await deliveries.ConfigureAwait(false);
        stop.Dispose();
        lock (gate)
        {
            retired = true;
            end = released ? end ?? ReceiveEnd.Completed : ReceiveEnd.CleanupFailed;
            latest = latest with { Stage = ReceiveStage.Ended, End = end };
            return new(latest, end.Value, released);
        }
    }

    private async Task ReadAsync()
    {
        try
        {
            while (true)
            {
                lock (gate) if (retired) return;
                var bytes = new byte[readSize];
                var count = await transport.ReadAsync(bytes, stop.Token).ConfigureAwait(false);
                lock (gate) if (retired) return; // A late, noncooperative read is discarded.
                if (count < 0 || count > bytes.Length) { Retire(ReceiveEnd.ReadFailed); return; }
                await chunks.Writer.WriteAsync(new(bytes, count, count == 0), stop.Token).ConfigureAwait(false);
                if (count == 0) return;
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        catch (Exception) { Retire(ReceiveEnd.ReadFailed); }
        finally { chunks.Writer.TryComplete(); }
    }

    private void WriteLoop(TaskCompletionSource done)
    {
        try
        {
            var decoder = new FrameDecoder(rxXor);
            var state = new ServiceStateCoordinator(Latest.Snapshot);
            while (chunks.Reader.WaitToReadAsync(stop.Token).AsTask().GetAwaiter().GetResult())
            {
                while (chunks.Reader.TryRead(out var chunk))
                {
                    lock (gate) if (retired) return;
                    if (chunk.Eof)
                    {
                        try { decoder.Finish(); }
                        catch (ProtocolException) { Retire(ReceiveEnd.TruncatedFrame); return; }
                        lock (gate)
                        {
                            end ??= ReceiveEnd.Completed;
                            latest = latest with { Stage = ReceiveStage.Ending, End = end };
                        }
                        return;
                    }
                    // Feed through individual frame completions. Feed can throw for a later
                    // malformed frame in the same input; byte stepping preserves prior commits.
                    for (var i = 0; i < chunk.Count; i++)
                    {
                        lock (gate) if (retired) return;
                        IReadOnlyList<Packet> packets;
                        try { packets = decoder.Feed(chunk.Bytes.AsSpan(i, 1)); }
                        catch (ProtocolException) { Retire(ReceiveEnd.InvalidFrame); return; }
                        foreach (var packet in packets) if (!Apply(state, packet)) return;
                    }
                }
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        catch (Exception) { Retire(ReceiveEnd.ReductionFailed); }
        finally { publications.Writer.TryComplete(); done.TrySetResult(); }
    }

    private bool Apply(ServiceStateCoordinator state, Packet packet)
    {
        var basis = state.Snapshot();
        ServiceObservationInputs inputs;
        try
        {
            var now = clock();
            if (!double.IsFinite(now)) throw new InvalidOperationException();
            inputs = observe(basis, now) with { ObservedAt = now, ResourceHeld = true };
            if (inputs.DailyCatalog is null || inputs.DeclaredMainCatalogMapIds is null)
                throw new InvalidOperationException();
        }
        catch (Exception) { Retire(ReceiveEnd.ObservationInputFailed); return false; }
        ServerEvent decoded;
        lock (gate)
        {
            if (retired) return false;
            try { decoded = ServerProtocol.Decode(packet, basis.Player?.RoleId, inputs.CraftingSchedules); }
            catch (Exception) { RetireLocked(ReceiveEnd.InvalidPayload); return false; }
            if (inputs.ArkRuntime is null && decoded is ArkQuestionEvent or ArkAnswerResultEvent &&
                basis.Ark.Role is not (null or 0) && basis.Ark.Role == basis.Player?.RoleId &&
                basis.Ark.Pending is { Kind: "question" })
            {
                RetireLocked(ReceiveEnd.MissingArkRuntime);
                return false;
            }
            if (beforeCommit is null) return CommitLocked(state, decoded, basis, inputs);
            // Admission is serialized with retirement, but user code must never hold gate.
            // This dedicated writer waits for the admitted hook, preserving event order and
            // ensuring completion/disposal includes even a noncooperative asynchronous hook.
        }
        try { beforeCommit(decoded, stop.Token).AsTask().GetAwaiter().GetResult(); }
        catch (Exception) { Retire(ReceiveEnd.EventHandlerFailed); return false; }
        lock (gate)
        {
            if (retired) return false; // A late hook may finish, but can never commit.
            return CommitLocked(state, decoded, basis, inputs);
        }
    }

    private bool CommitLocked(ServiceStateCoordinator state, ServerEvent decoded,
        ServiceStateSnapshot basis, ServiceObservationInputs inputs)
    {
        ServiceStateSnapshot next;
        try { next = state.Apply(decoded, new(basis, inputs)); }
        catch (Exception) { RetireLocked(ReceiveEnd.ReductionFailed); return false; }
        latest = latest with { Revision = checked(latest.Revision + 1), Snapshot = next };
        publications.Writer.TryWrite(latest);
        return true;
    }

    private async Task DeliverAsync()
    {
        await foreach (var publication in publications.Reader.ReadAllAsync().ConfigureAwait(false))
        {
            lock (gate) if (retired) continue;
            // Admission is serialized with retirement. An admitted callback is allowed to
            // finish; cleanup awaits this worker so it can never outlive successful disposal.
            try { observer?.Invoke(publication); }
            catch (Exception) { /* Observer errors do not affect committed state or reception. */ }
        }
    }
}
