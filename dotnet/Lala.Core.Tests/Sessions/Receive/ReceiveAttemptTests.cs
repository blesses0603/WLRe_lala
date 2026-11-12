using System.Collections;
using System.Collections.Concurrent;
using System.Reflection;
using System.Collections.Immutable;
using System.Numerics;
using System.Threading.Channels;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.Social.Ark;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed partial class ReceiveAttemptTests
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(10);
    private static readonly Packet Ping = new(1, 23);
    private static readonly Packet World = new(3, 1, new PacketWriter().U32(17).U8(0).U16(101).U16(20).U16(30)
        .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
    private static Packet[] Sequence => [new(63, 7, [0, 2]), new(63, 1), World, new(1, 11),
        new(23, 5, new PacketWriter().U8(20).U8(1).U16(42).U8(2).Raw(new byte[61]).Build()),
        new(62, 7, new PacketWriter().U8(1).U8(2).U16(43).U8(1).Raw(new byte[61]).Build()),
        new(62, 57, [1, 1, 1, 0, 1, 0, 42, 0, 3, 0]),
        new(26, 4, [100, 0, 0, 0]), new(8, 1, new PacketWriter().U8(1).U8(1).U32(150).U32(0).Build()), Ping];
    private static byte[] Wire(IEnumerable<Packet> packets, int key = 0xAD) => packets.SelectMany(p => WireCodec.Encode(p, key)).ToArray();
    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static ReceiveAttempt Attempt(IReceiveTransport transport, Action<ReceivePublication>? callback = null,
        Func<ServiceStateSnapshot, double, ServiceObservationInputs>? inputs = null, Func<double>? clock = null,
        ServiceStateSnapshot? initial = null, int readSize = 4096, int bufferedChunks = 4, int xor = 0xAD) =>
        new(transport, xor, clock ?? (() => 123), inputs ?? ((_, now) => new(now)), callback, initial, readSize, bufferedChunks);

    public static IEnumerable<object[]> SplitPoints()
    {
        var length = Wire(Sequence).Length;
        for (var split = 1; split < length; split++) yield return [split];
    }

    [Fact]
    public async Task PublicationSignalCoversCommitsAndLifecycleWithoutMissedPullWakeups()
    {
        var transport = new PushTransport();
        await using var attempt = Attempt(transport);
        var createdSignal = attempt.PublicationChanged;
        Assert.Same(createdSignal, attempt.PublicationChanged); Assert.False(createdSignal.IsCompleted);
        var run = attempt.RunAsync(); await createdSignal.WaitAsync(Timeout);
        Assert.Equal(ReceiveStage.Running, attempt.Latest.Stage);
        for (int i = 1; i <= 16; i++)
        {
            var signal = attempt.PublicationChanged;
            var before = attempt.Latest;
            Assert.False(signal.IsCompleted);
            transport.Push(Wire([Ping]));
            await signal.WaitAsync(Timeout);
            Assert.Equal(i, attempt.Latest.Revision); Assert.Equal(i - 1, before.Revision);
            Assert.NotSame(signal, attempt.PublicationChanged);
        }
        var retiring = attempt.PublicationChanged;
        await attempt.DisposeAsync(); await retiring.WaitAsync(Timeout);
        var result = await run.WaitAsync(Timeout);
        Assert.Equal(ReceiveStage.Ended, result.Publication.Stage); Assert.Equal(16, result.Publication.Revision);
        var endedSignal = attempt.PublicationChanged;
        await attempt.DisposeAsync();
        Assert.Same(endedSignal, attempt.PublicationChanged); Assert.False(endedSignal.IsCompleted);
    }

    [Theory]
    [MemberData(nameof(SplitPoints))]
    public async Task EveryHeaderAndBodySplitMatchesDirectComposition(int split)
    {
        var packets = Sequence;
        var expected = new List<ServiceStateSnapshot>();
        var direct = new ServiceStateCoordinator();
        expected.Add(direct.Snapshot());
        foreach (var packet in packets) expected.Add(direct.Apply(packet, new(direct.Snapshot(), new(123))));
        var wire = Wire(packets);
        var transport = new ScriptedTransport([wire[..split], wire[split..]]);
        var observedBases = new List<ServiceStateSnapshot>();
        await using var attempt = Attempt(transport, inputs: (basis, now) =>
        {
            observedBases.Add(basis);
            return new(now);
        });
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        Assert.True(result.ResourcesReleased);
        Assert.Equal(packets.Length, result.Publication.Revision);
        Assert.Equal(new BigInteger(packets.Length), result.Publication.Snapshot.PacketCount);
        Assert.Equal(packets.Length, observedBases.Count);
        for (var i = 0; i < observedBases.Count; i++) Equivalent(expected[i], observedBases[i]);
        Equivalent(expected[^1], result.Publication.Snapshot);
        Assert.Equal(0, observedBases[0].PacketCount);
        Assert.Equal("authenticated", observedBases[1].Phase); // Observed reducer text, not authentication proof.
        Assert.Equal(1, transport.DisposeCalls);
        Assert.Equal(18, ServiceStateCoordinator.ObserverOrder.Length);
        Assert.All(ServiceStateCoordinator.ObserverOrder, observer => Assert.True(observer.Composed));
        Assert.False(result.Publication.Snapshot.IsCompleteState);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(173)]
    [InlineData(255)]
    public async Task ByteReadsAndDifferentCompletionThreadsStillHaveOneActualWriter(int xor)
    {
        var transport = new ScriptedTransport(Wire(Sequence, xor).Select(value => new byte[] { value }).ToArray(), newThreads: true);
        var writers = new ConcurrentBag<Thread>();
        await using var attempt = Attempt(transport, inputs: (_, now) => { writers.Add(Thread.CurrentThread); return new(now); }, xor: xor);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        var writer = Assert.Single(writers.Distinct());
        Assert.NotEqual(Thread.CurrentThread, writer);
        Assert.True(transport.CompletionThreads.Distinct().Count() > 1);
        Assert.DoesNotContain(writer, transport.CompletionThreads);
        Assert.False(writer.IsAlive); // Run completion includes actual Thread.Join.
    }

    [Fact]
    public async Task ConstructorIsInertAndOneShotCompletionIsStable()
    {
        var transport = new ScriptedTransport([Wire([Ping])]);
        var calls = 0;
        var attempt = Attempt(transport, inputs: (_, now) => { calls++; return new(now); });
        var initial = attempt.Latest;
        Assert.Equal(ReceiveStage.Created, initial.Stage);
        Assert.Equal(0, calls);
        Assert.Equal(0, transport.ReadCalls);
        var task = attempt.RunAsync();
        Assert.Same(task, attempt.RunAsync(new CancellationToken(true)));
        var result = await task.WaitAsync(Timeout);
        Assert.Same(result, await attempt.RunAsync());
        Assert.Equal(ReceiveStage.Ended, result.Publication.Stage);
        Assert.Equal(ReceiveStage.Created, initial.Stage);
        var cleanup = attempt.DisposeAsync().AsTask();
        Assert.Same(cleanup, attempt.DisposeAsync().AsTask());
        await cleanup.WaitAsync(Timeout);
        Assert.Equal(1, calls);
        Assert.Equal(1, transport.DisposeCalls);
    }

    [Fact]
    public async Task DisposeBeforeRunNeverReadsOrInvokesInputs()
    {
        var transport = new ScriptedTransport([Wire([Ping])]);
        var attempt = Attempt(transport, inputs: (_, _) => throw new Exception("must not call"));
        var id = attempt.Latest.Attempt;
        var cleanup = attempt.DisposeAsync().AsTask();
        Assert.False(attempt.IsCurrent(id));
        await cleanup.WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Disposed, (await attempt.RunAsync()).End);
        Assert.Equal(0, transport.ReadCalls);
        Assert.Equal(1, transport.DisposeCalls);
    }

    [Fact]
    public async Task AlreadyCancelledTokenNeverReads()
    {
        var transport = new ScriptedTransport([Wire([Ping])]);
        await using var attempt = Attempt(transport);
        var result = await attempt.RunAsync(new CancellationToken(true)).WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Cancelled, result.End);
        Assert.Equal(0, transport.ReadCalls);
        Assert.Equal(0, result.Publication.Revision);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task MalformedFrameAndWrongXorDoNotErasePriorCommit(bool wrongXor)
    {
        var bad = Wire([Ping], wrongXor ? 0xBC : 0xAD);
        if (!wrongXor) bad[0] ^= 1;
        var transport = new ScriptedTransport([Wire([Ping]).Concat(bad).Concat(Wire([Ping])).ToArray()]);
        await using var attempt = Attempt(transport);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.InvalidFrame, result.End);
        Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(1, result.Publication.Snapshot.PacketCount);
    }

    [Fact]
    public async Task EveryTruncatedEofFailsWithoutCountingIncompletePacket()
    {
        var wire = Wire([World]);
        for (var size = 1; size < wire.Length; size++)
        {
            await using var attempt = Attempt(new ScriptedTransport([Wire([Ping]).Concat(wire[..size]).ToArray()]));
            var result = await attempt.RunAsync().WaitAsync(Timeout);
            Assert.Equal(ReceiveEnd.TruncatedFrame, result.End);
            Assert.Equal(1, result.Publication.Revision);
        }
    }

    [Fact]
    public async Task MalformedPayloadIsAtomicAndHasOnlyFixedFailureCode()
    {
        await using var attempt = Attempt(new ScriptedTransport([Wire([Ping, new(26, 4, [1]), Ping])]));
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.InvalidPayload, result.End);
        Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(1, result.Publication.Snapshot.PacketCount);
        Assert.Null(result.Publication.Snapshot.Local.Session.Gold.Amount);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task ProviderAndClockFailuresAreSanitizedAndDoNotCommit(bool clockFails)
    {
        var calls = 0;
        await using var attempt = Attempt(new ScriptedTransport([Wire([Ping, Ping])]),
            inputs: (_, now) => ++calls == 2 ? throw new Exception("secret provider payload") : new(now),
            clock: clockFails ? () => double.NaN : null);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.ObservationInputFailed, result.End);
        Assert.Equal(clockFails ? 0 : 1, result.Publication.Revision);
        Assert.DoesNotContain("secret", result.ToString());
    }

    [Fact]
    public async Task ProviderFalseAndParsedCatalogNeverReleaseResourcesOrAuthorizeSession()
    {
        await using var attempt = Attempt(new ScriptedTransport([Wire(Sequence)]), inputs: (_, _) => new(-1)
        {
            ResourceHeld = false, WorldCatalog = new([101]), DailyCatalog = new(new([], []), "unverified")
        });
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        var state = result.Publication.Snapshot;
        Assert.True(result.Publication.ResourceHeld);
        Assert.True(state.Observation!.Inputs.ResourceHeld);
        Assert.Equal(123, state.Observation.Inputs.ObservedAt);
        Assert.False(state.DailyTasks.CatalogReady);
        Assert.Null(state.DailyTasks.CatalogToken);
        Assert.False(state.Local.World.Navigation.RuntimeGeometryVerified);
        Assert.False(state.IsCompleteState);
        Assert.Equal(["ReadAsync"], typeof(IReceiveTransport).GetMethods().Select(value => value.Name).ToArray());
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task ArkContextFailurePreservesImportedPendingReceipt(bool invalidRuntime)
    {
        var direct = new ServiceStateCoordinator();
        var world = direct.Apply(World, new(direct.Snapshot(), new(123)));
        var pending = new ArkPendingObservation("question", 17, new(true, "synthetic"), world.DailyTasks.Generation)
            { Event = new(1, 123, 3, 1, false) };
        var initial = new ServiceStateSnapshot(local: world.Local, dailyTasks: world.DailyTasks,
            ark: new() { Role = 17, Pending = pending });
        var question = new Packet(191, 11, new PacketWriter().U32(101).U8(6).U32(8).U32(5)
            .U32(201).U32(202).U32(203).U32(204).Build());
        await using var attempt = Attempt(new ScriptedTransport([Wire([question])]), initial: initial,
            inputs: (_, now) => new(now) { ArkRuntime = invalidRuntime ? new(true, pending.Token, null!) : null });
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(invalidRuntime ? ReceiveEnd.ReductionFailed : ReceiveEnd.MissingArkRuntime, result.End);
        Assert.Same(initial, result.Publication.Snapshot);
        Assert.Same(pending, result.Publication.Snapshot.Ark.Pending);
        Assert.False(result.Publication.Snapshot.Ark.Uncertain);
        Assert.Equal(0, result.Publication.Revision);
    }

    [Fact]
    public async Task CancellationDoesNotTreatAnIncompleteFrameAsTruncatedEof()
    {
        var transport = new PushTransport();
        using var token = new CancellationTokenSource();
        var observed = Signal();
        await using var attempt = Attempt(transport, inputs: (_, now) => { observed.TrySetResult(); return new(now); });
        var run = attempt.RunAsync(token.Token);
        transport.Push(Wire([Ping]).Concat(Wire([World])[..3]).ToArray());
        await observed.Task.WaitAsync(Timeout);
        token.Cancel();
        var result = await run.WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Cancelled, result.End);
        Assert.InRange(result.Publication.Revision, 0, 1);
    }

    [Fact]
    public async Task RetirementDuringProviderPreventsApplyAndQueuedPublications()
    {
        var entered = Signal();
        using var release = new ManualResetEventSlim();
        var callbacks = 0;
        var attempt = Attempt(new ScriptedTransport([Wire([Ping, Ping, Ping])]), _ => Interlocked.Increment(ref callbacks),
            (_, now) => { entered.TrySetResult(); Assert.True(release.Wait(Timeout)); return new(now); });
        var run = attempt.RunAsync();
        await entered.Task.WaitAsync(Timeout);
        var id = attempt.Latest.Attempt;
        var cleanup = attempt.DisposeAsync().AsTask();
        Assert.False(attempt.IsCurrent(id));
        Assert.Equal(ReceiveStage.Ending, attempt.Latest.Stage);
        Assert.False(cleanup.IsCompleted);
        release.Set();
        await cleanup.WaitAsync(Timeout);
        Assert.Equal(0, (await run).Publication.Revision);
        Assert.Equal(0, callbacks);
    }

    [Fact]
    public async Task ReaderBackpressureIsBoundedWhileProviderIsBlocked()
    {
        var entered = Signal();
        using var release = new ManualResetEventSlim();
        var transport = new ScriptedTransport(Enumerable.Range(0, 100).Select(_ => Wire([Ping])).ToArray());
        var attempt = Attempt(transport, inputs: (_, now) =>
        {
            entered.TrySetResult(); Assert.True(release.Wait(Timeout)); return new(now);
        }, bufferedChunks: 1);
        var run = attempt.RunAsync();
        await entered.Task.WaitAsync(Timeout);
        Assert.True(SpinWait.SpinUntil(() => transport.ReadCalls == 3, Timeout));
        await Task.Delay(20);
        Assert.Equal(3, transport.ReadCalls); // One in the writer, one queued, one reader-owned.
        var cleanup = attempt.DisposeAsync().AsTask();
        release.Set();
        await cleanup.WaitAsync(Timeout);
        Assert.Equal(0, (await run).Publication.Revision);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task SlowObserverDoesNotBlockReaderAndDeliveryIsCoalesced(bool retire)
    {
        var transport = new PushTransport();
        var entered = Signal(); var committed = Signal();
        using var release = new ManualResetEventSlim();
        var revisions = new ConcurrentQueue<long>();
        var attempt = Attempt(transport, publication =>
        {
            revisions.Enqueue(publication.Revision);
            if (publication.Revision == 1) { entered.TrySetResult(); Assert.True(release.Wait(Timeout)); }
        }, (basis, now) => { if (basis.PacketCount == 99) committed.TrySetResult(); return new(now); });
        var run = attempt.RunAsync();
        transport.Push(Wire([Ping]));
        await entered.Task.WaitAsync(Timeout);
        transport.Push(Wire(Enumerable.Repeat(Ping, 99)));
        transport.Push([]);
        await committed.Task.WaitAsync(Timeout);
        Assert.True(SpinWait.SpinUntil(() => attempt.Latest.Revision == 100, Timeout));
        await transport.DisposeEntered.Task.WaitAsync(Timeout);
        Assert.False(run.IsCompleted);
        var cleanup = retire ? attempt.DisposeAsync().AsTask() : null;
        release.Set();
        var result = await run.WaitAsync(Timeout);
        if (cleanup is not null) await cleanup.WaitAsync(Timeout);
        await attempt.DisposeAsync();
        Assert.Equal(100, result.Publication.Revision);
        Assert.Equal(retire ? [1L] : [1L, 100L], revisions.ToArray());
    }

    [Fact]
    public async Task ObserverExceptionsDoNotRollBackOrFailReception()
    {
        await using var attempt = Attempt(new ScriptedTransport([Wire(Sequence)]), _ => throw new Exception("observer secret"));
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        Assert.Equal(Sequence.Length, result.Publication.Revision);
        Assert.DoesNotContain("secret", result.ToString());
    }

    [Fact]
    public async Task NoncooperativeReadStaysPendingAndLateBytesCannotAffectReplacement()
    {
        var held = new HeldTransport(Wire([World]));
        var old = Attempt(held);
        var oldRun = old.RunAsync();
        await held.Entered.Task.WaitAsync(Timeout);
        var oldId = old.Latest.Attempt;
        var cleanup = old.DisposeAsync().AsTask();
        await held.DisposeEntered.Task.WaitAsync(Timeout);
        Assert.False(old.IsCurrent(oldId));
        Assert.False(cleanup.IsCompleted);
        Assert.False(oldRun.IsCompleted);
        await using var replacement = Attempt(new ScriptedTransport([Wire([Ping])]));
        var newer = await replacement.RunAsync().WaitAsync(Timeout);
        Assert.NotEqual(oldId, newer.Publication.Attempt);
        held.Release.TrySetResult();
        await cleanup.WaitAsync(Timeout);
        Assert.Equal(0, (await oldRun).Publication.Revision);
        Assert.Equal(1, newer.Publication.Revision);
        Assert.Null(newer.Publication.Snapshot.Player);
        Assert.Equal(1, held.DisposeCalls);
    }

    [Fact]
    public async Task CleanupFailureNeverReportsReleasedAndRepeatedDisposeSharesFailure()
    {
        var transport = new ScriptedTransport([], failDispose: true);
        var attempt = Attempt(transport);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.CleanupFailed, result.End);
        Assert.False(result.ResourcesReleased);
        var cleanup = attempt.DisposeAsync().AsTask();
        Assert.Same(cleanup, attempt.DisposeAsync().AsTask());
        var error = await Assert.ThrowsAsync<ReceiveCleanupException>(() => cleanup);
        Assert.Equal("Receive transport cleanup failed.", error.Message);
        Assert.Null(error.InnerException);
        Assert.Same(result, await attempt.RunAsync());
        Assert.Equal(1, transport.DisposeCalls);
    }

    [Fact]
    public async Task HeldDisposalMustFinishBeforeCompletionCanClaimReleased()
    {
        var held = new HeldTransport([], holdDispose: true);
        held.Release.TrySetResult();
        var attempt = Attempt(held);
        var run = attempt.RunAsync();
        await held.DisposeEntered.Task.WaitAsync(Timeout);
        Assert.Equal(ReceiveStage.Ending, attempt.Latest.Stage);
        var cleanup = attempt.DisposeAsync().AsTask();
        Assert.False(run.IsCompleted);
        Assert.False(cleanup.IsCompleted);
        held.DisposeRelease.TrySetResult();
        await cleanup.WaitAsync(Timeout);
        Assert.True((await run).ResourcesReleased);
    }

    [Fact]
    public async Task EofCleanupAwaitsCancellationCallbacksCreatedDuringDisposal()
    {
        var transport = new CallbackTransport();
        var attempt = Attempt(transport);
        transport.ReadStatus = () => attempt.Latest.Stage;
        var run = attempt.RunAsync();
        await transport.DisposeEntered.Task.WaitAsync(Timeout);
        var cleanup = attempt.DisposeAsync().AsTask();
        await transport.CancelEntered.Task.WaitAsync(Timeout);
        transport.DisposeRelease.TrySetResult();
        await Task.Delay(20);
        Assert.False(run.IsCompleted);
        Assert.False(cleanup.IsCompleted);
        Assert.Equal(ReceiveStage.Ending, attempt.Latest.Stage);
        transport.CancelRelease.Set();
        await cleanup.WaitAsync(Timeout);
        Assert.True((await run).ResourcesReleased);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(5000)]
    [InlineData(0)]
    public async Task InvalidTransportReadResultsUseFixedCode(int returned)
    {
        await using var attempt = Attempt(new FaultTransport(returned));
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.ReadFailed, result.End);
        Assert.Equal(0, result.Publication.Revision);
        Assert.True(result.ResourcesReleased);
    }

    [Fact]
    public async Task ConcurrentCancellationAndCommitHaveOneConsistentTerminalSnapshot()
    {
        for (var i = 0; i < 50; i++)
        {
            var entered = Signal();
            using var release = new ManualResetEventSlim();
            using var token = new CancellationTokenSource();
            await using var attempt = Attempt(new ScriptedTransport([Wire([Ping, Ping])]), inputs: (_, now) =>
            { entered.TrySetResult(); Assert.True(release.Wait(Timeout)); return new(now); });
            var run = attempt.RunAsync(token.Token);
            await entered.Task.WaitAsync(Timeout);
            await Task.WhenAll(Task.Run(token.Cancel), Task.Run(release.Set));
            var result = await run.WaitAsync(Timeout);
            Assert.Equal(result.Publication.Revision, (long)result.Publication.Snapshot.PacketCount);
            Assert.InRange(result.Publication.Revision, 0, 2);
            Assert.Same(result, await attempt.RunAsync());
            Assert.False(attempt.IsCurrent(result.Publication.Attempt));
        }
    }

    // StateValue has intentionally throwing getters for the other union cases, so
    // xUnit's generic reflection equivalence cannot inspect the complete snapshot.
    // Compare every public property, selecting the actual StateValue union branch.
    private static void Equivalent(object? expected, object? actual)
    {
        if (ReferenceEquals(expected, actual)) return;
        Assert.NotNull(expected); Assert.NotNull(actual);
        var type = expected.GetType();
        Assert.Equal(type, actual.GetType());
        if (expected is StateValue left && actual is StateValue right)
        {
            Assert.Equal(left.Kind, right.Kind);
            Equivalent(left.Kind switch
            {
                StateValueKind.Scalar => left.ScalarValue,
                StateValueKind.Map => left.MapValue,
                _ => (object)left.SequenceValue
            }, right.Kind switch
            {
                StateValueKind.Scalar => right.ScalarValue,
                StateValueKind.Map => right.MapValue,
                _ => (object)right.SequenceValue
            });
        }
        else if (type.IsPrimitive || type.IsEnum || expected is string or decimal or BigInteger)
            Assert.Equal(expected, actual);
        else if (expected is IEnumerable leftItems && actual is IEnumerable rightItems)
        {
            var a = leftItems.Cast<object?>().ToArray();
            var b = rightItems.Cast<object?>().ToArray();
            Assert.Equal(a.Length, b.Length);
            for (var i = 0; i < a.Length; i++) Equivalent(a[i], b[i]);
        }
        else foreach (var property in type.GetProperties(BindingFlags.Instance | BindingFlags.Public))
            if (property.GetIndexParameters().Length == 0) Equivalent(property.GetValue(expected), property.GetValue(actual));
    }

    private sealed class ScriptedTransport(byte[][] script, bool newThreads = false, bool failDispose = false) : IReceiveTransport
    {
        private int index;
        private int offset;
        private int reads;
        private int disposes;
        private BlockingCollection<Action>[]? completionQueues;
        private Thread[]? completionWorkers;
        private void StartCompletionWorkers()
        {
            if(completionWorkers is not null)return;
            completionQueues=[new(),new()];
            completionWorkers=completionQueues.Select(queue=>new Thread(()=>
            {foreach(var complete in queue.GetConsumingEnumerable())complete();}){IsBackground=true}).ToArray();
            foreach(var worker in completionWorkers)worker.Start();
        }
        public int ReadCalls => Volatile.Read(ref reads);
        public int DisposeCalls => Volatile.Read(ref disposes);
        public ConcurrentBag<Thread> CompletionThreads { get; } = [];
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref reads);
            cancellationToken.ThrowIfCancellationRequested();
            int Read()
            {
                CompletionThreads.Add(Thread.CurrentThread);
                if (index == script.Length) return 0;
                var bytes = script[index];
                var count = Math.Min(destination.Length, bytes.Length - offset);
                bytes.AsMemory(offset, count).CopyTo(destination);
                offset += count;
                if (offset == bytes.Length) { index++; offset = 0; }
                return count;
            }
            if (!newThreads) return new(Read());
            var result = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            // Alternate two actual completion threads instead of creating one OS
            // thread per byte. Keep byte reads and the independent writer assertion.
            StartCompletionWorkers();
            completionQueues![reads & 1].Add(()=>
            {
                try{cancellationToken.ThrowIfCancellationRequested();result.TrySetResult(Read());}
                catch(OperationCanceledException){result.TrySetCanceled(cancellationToken);}
                catch(Exception error){result.TrySetException(error);}
            });
            return new(result.Task);
        }
        public ValueTask DisposeAsync()
        {
            Interlocked.Increment(ref disposes);
            if(completionWorkers is not null)
            {
                foreach(var queue in completionQueues!)queue.CompleteAdding();
                foreach(var worker in completionWorkers)worker.Join();
                foreach(var queue in completionQueues!)queue.Dispose();
            }
            return failDispose ? ValueTask.FromException(new IOException("private transport message")) : ValueTask.CompletedTask;
        }
    }

    private sealed class PushTransport : IReceiveTransport
    {
        private readonly Channel<byte[]> bytes = Channel.CreateUnbounded<byte[]>();
        public TaskCompletionSource DisposeEntered { get; } = Signal();
        public void Push(byte[] value) => Assert.True(bytes.Writer.TryWrite(value));
        public async ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
        {
            var next = await bytes.Reader.ReadAsync(cancellationToken);
            next.CopyTo(destination);
            return next.Length;
        }
        public ValueTask DisposeAsync() { DisposeEntered.TrySetResult(); return ValueTask.CompletedTask; }
    }

    private sealed class FaultTransport(int returned) : IReceiveTransport
    {
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken) =>
            returned == 0 ? ValueTask.FromException<int>(new IOException("private read failure")) : new(returned);
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class CallbackTransport : IReceiveTransport
    {
        public TaskCompletionSource DisposeEntered { get; } = Signal();
        public TaskCompletionSource DisposeRelease { get; } = Signal();
        public TaskCompletionSource CancelEntered { get; } = Signal();
        public ManualResetEventSlim CancelRelease { get; } = new();
        public Func<ReceiveStage>? ReadStatus { get; set; }
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
        {
            cancellationToken.Register(() =>
            {
                Assert.Equal(ReceiveStage.Ending, ReadStatus!()); // No callback executes under the state lock.
                CancelEntered.TrySetResult();
                Assert.True(CancelRelease.Wait(Timeout));
            });
            return new(0);
        }
        public async ValueTask DisposeAsync()
        {
            Assert.Equal(ReceiveStage.Ending, ReadStatus!());
            DisposeEntered.TrySetResult();
            await DisposeRelease.Task;
        }
    }

    private sealed class HeldTransport(byte[] bytes, bool holdDispose = false) : IReceiveTransport
    {
        public TaskCompletionSource Entered { get; } = Signal();
        public TaskCompletionSource Release { get; } = Signal();
        public TaskCompletionSource DisposeEntered { get; } = Signal();
        public TaskCompletionSource DisposeRelease { get; } = Signal();
        public int DisposeCalls;
        public async ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            await Release.Task; // Intentionally ignores cancellation and disposal.
            bytes.CopyTo(destination);
            return bytes.Length;
        }
        public async ValueTask DisposeAsync()
        {
            Interlocked.Increment(ref DisposeCalls);
            DisposeEntered.TrySetResult();
            if (holdDispose) await DisposeRelease.Task;
        }
    }
}
