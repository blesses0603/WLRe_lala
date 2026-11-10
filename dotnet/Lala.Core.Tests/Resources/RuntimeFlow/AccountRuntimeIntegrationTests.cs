using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Core.Tests.Sessions;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    // Original synthetic packets and ephemeral loopback listeners only. The resource side
    // reuses the retained owned Unity fixtures and real SQLite bootstrap/readback helpers.
    private static readonly TimeSpan AccountGuard = TimeSpan.FromSeconds(30);
    private static TaskCompletionSource AccountSignal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static Packet AccountRoles => new(63, 1, new PacketWriter().U8(1).U8(0).U8(1).U8(1)
        .U32(1).U32(1).U32(1).U32(1).Raw(new byte[8]).U32(0).U8(0).U8(0).U32(0).U32(0)
        .U8(0).U8(0).U16(1).Raw(new byte[8]).U8(0).Raw(new byte[34]).Build());
    private static Packet AccountWorld => new(3, 1, new PacketWriter().U32(17).U8(0).U16(101).U16(20).U16(30)
        .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
    private sealed class AccountPeer : IAsyncDisposable
    {
        private readonly TcpListener listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource stop = new(AccountGuard);
        private Task? running;
        private Socket? accepted;
        internal AccountPeer() => listener.Start();
        internal IPEndPoint Endpoint => (IPEndPoint)listener.LocalEndpoint;
        internal bool HasPending => listener.Pending();
        internal Task Run(params Func<AccountPeerClient, Task>[] scripts) => running = Work(scripts);
        private async Task Work(IEnumerable<Func<AccountPeerClient, Task>> scripts)
        {
            foreach (var script in scripts)
            {
                accepted = await listener.AcceptSocketAsync(stop.Token);
                using (accepted) await script(new(accepted, stop.Token));
                accepted = null;
            }
        }
        public async ValueTask DisposeAsync()
        {
            stop.Cancel(); accepted?.Dispose(); listener.Stop();
            if (running is not null)
                try { await running.WaitAsync(AccountGuard); }
                catch (Exception error) when (error is SocketException or IOException or OperationCanceledException or ObjectDisposedException) { }
            stop.Dispose();
        }
    }
    private sealed class AccountPeerClient(Socket socket, CancellationToken token)
    {
        private readonly FrameDecoder decoder = new();
        private readonly Queue<Packet> pending = new();
        private async Task<Packet> Next()
        {
            while (pending.Count == 0)
            {
                var bytes = new byte[4096]; int count = await socket.ReceiveAsync(bytes, SocketFlags.None, token);
                if (count == 0) throw new IOException("Synthetic peer closed.");
                foreach (var packet in decoder.Feed(bytes.AsSpan(0, count))) pending.Enqueue(packet);
            }
            return pending.Dequeue();
        }
        internal async Task Expect(int main, int sub, byte? first = null)
        {
            var packet = await Next(); Assert.Equal(main, packet.Main); Assert.Equal(sub, packet.Sub);
            if (first is not null) Assert.Equal(first.Value, packet.Payload.Span[0]);
        }
        internal Task WaitFor(Task signal) => signal.WaitAsync(token);
        internal async Task Send(params Packet[] packets)
        {
            byte[] bytes = packets.SelectMany(p => WireCodec.Encode(p)).ToArray();
            int offset = 0;
            while (offset < bytes.Length)
            {
                int count = await socket.SendAsync(bytes.AsMemory(offset), SocketFlags.None, token);
                if (count == 0) throw new IOException("Synthetic send closed.");
                offset += count;
            }
        }
        internal Task ExpectClosedAfterRetirement() => RetiredPeerClosure.AssertAsync(pending, decoder,
            () => socket.ReceiveAsync(new Memory<byte>(new byte[1]), SocketFlags.None, token));
        internal async Task CloseSendAndExpectEof()
        {
            socket.Shutdown(SocketShutdown.Send);
            Assert.Empty(pending); decoder.Finish();
            // Any packet beyond the explicit login/transport script fails this assertion.
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
    }
    private sealed class AccountCredentials : IAccountCredentialSource
    {
        internal readonly ConcurrentQueue<AccountCredentialRequest> Requests = new();
        internal readonly ConcurrentQueue<AccountLoginCredentials> Values = new();
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); Requests.Enqueue(request);
            var value = new AccountLoginCredentials("synthetic", "fake_password"); Values.Enqueue(value);
            return ValueTask.FromResult<AccountLoginCredentials?>(value);
        }
    }
    private static AccountConnectionProfile AccountProfile(AccountPeer verification, AccountPeer formal) =>
        new(verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1, 1, 2);
    private static async Task AccountVerify(AccountPeerClient client)
    {
        await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [0, 0]));
        await client.CloseSendAndExpectEof();
    }
    private static async Task AccountFinishLogin(AccountPeerClient client)
    {
        await client.Send(new Packet(63, 7, [0, 2]), AccountRoles);
        await client.Expect(63, 2, 1); await client.Send(AccountWorld, new Packet(1, 11));
        await client.Expect(12, 1); await client.Expect(3, 2);
    }
    private static async Task AccountEnterWorld(AccountPeerClient client)
    {
        await client.Expect(63, 7, 2); await AccountFinishLogin(client);
    }
    private static async Task AccountWaitFor(Func<bool> condition)
    {
        using var deadline = new CancellationTokenSource(AccountGuard);
        while (!condition()) await Task.Delay(1, deadline.Token);
    }
    private static void AccountHeld(AccountRuntime runtime, AccountSession session)
    {
        Assert.True(runtime.Snapshot.ResourceHeld); Assert.False(runtime.Snapshot.CanSendCommands);
        Assert.True(runtime.Snapshot.Connection.ResourceHeld); Assert.False(runtime.Snapshot.Connection.CanSendCommands);
        Assert.Equal(SessionPhase.Held, session.Snapshot.Phase);
        Assert.False(session.ConfirmResources(session.Snapshot.Generation, "v", "v", true));
    }

    [Fact]
    public async Task Integrated_account_waits_for_login_then_bootstraps_real_inventory_without_admission()
    {
        using var fixture = new Fixture(); var source = new Source(); var credentials = new AccountCredentials();
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var loginRequested = AccountSignal(); var allowLogin = AccountSignal(); var finish = AccountSignal();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); loginRequested.SetResult();
            await client.WaitFor(allowLogin.Task); await AccountFinishLogin(client);
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var modes = new ConcurrentQueue<SqliteOpenMode>(); var connections = new ConcurrentQueue<ScriptedReadConnection>();
        var session = new AccountSession(); long generation = session.Begin("synthetic", "loopback").Generation;
        var resources = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
            {
                WrapConnection = connection =>
                {
                    modes.Enqueue(new SqliteConnectionStringBuilder(connection.ConnectionString).Mode);
                    var tracked = new ScriptedReadConnection(connection); connections.Enqueue(tracked); return tracked;
                }
            }));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), credentials, resources);
        Assert.Equal(AccountConnectionPhase.Created, runtime.Snapshot.Connection.Phase);
        Assert.Empty(credentials.Requests); Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
        var run = runtime.RunAsync(); Assert.Same(run, runtime.RunAsync());
        try
        {
            await loginRequested.Task.WaitAsync(AccountGuard);
            Assert.Equal(AccountConnectionPhase.Connecting, runtime.Snapshot.Connection.Phase);
            Assert.Equal(0, source.Observations); Assert.Empty(runtime.Snapshot.ResourceHistory);
            Assert.False(Directory.Exists(fixture.Root));
            allowLogin.SetResult();
            await AccountWaitFor(() => runtime.Snapshot.ResourceHistory.Length == 1);
            var preparation = Assert.Single(runtime.Snapshot.ResourceHistory);
            Assert.Equal(generation, preparation.Generation); Assert.Equal(1, preparation.AttemptNumber);
            Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, preparation.Preparation.Status);
            Assert.Equal(AccountResourceStorageOutcome.Committed, preparation.Preparation.StorageOutcome);
            Assert.True(preparation.Preparation.ReadbackMatched); Assert.True(preparation.Preparation.SourcesRechecked);
            Assert.False(preparation.Preparation.CanLogin); Assert.False(preparation.Preparation.CanSendPackets);
            Assert.Equal(new[] { SqliteOpenMode.ReadWriteCreate, SqliteOpenMode.ReadOnly }, modes.ToArray());
            Assert.All(connections, connection => Assert.True(connection.WasDisposed));
            Assert.Single(connections.First().Commands, sql => sql == "COMMIT");
            Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
            Assert.Equal(1L, fixture.Sql("SELECT count(*) FROM versions"));
            Assert.False(runtime.Snapshot.HasCurrentResources); Assert.Null(runtime.Publication!.Catalogs);
            Assert.False(resources.TryReadCatalogs(out _)); AccountHeld(runtime, session);
            Assert.True(Assert.Single(credentials.Values).IsDisposed);
            runtime.Stop(); Assert.Null(runtime.Publication);
            var result = await run.WaitAsync(AccountGuard);
            Assert.True(result.ResourcesReleased); Assert.True(result.Connection.ResourcesReleased);
            Assert.Equal(AccountConnectionEndReason.Stopped, result.Connection.Status.EndReason);
            Assert.Equal(preparation, Assert.Single(result.ResourceHistory)); // Historical NotAdmitted receipt survives retirement.
            Assert.Equal(1, source.Disposals);
        }
        finally { allowLogin.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Integrated_account_rejected_login_never_starts_resource_io()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var peer = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [1, 0]));
            await client.CloseSendAndExpectEof();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var result = await runtime.RunAsync().WaitAsync(AccountGuard); await peer.WaitAsync(AccountGuard);
        Assert.Equal(AccountConnectionEndReason.ConnectionEnded, result.Connection.Status.EndReason);
        Assert.False(Assert.Single(result.Connection.Status.History).LoginProtocolCompleted);
        Assert.Empty(result.ResourceHistory); Assert.Equal(0, source.Observations); Assert.Equal(1, source.Disposals);
        Assert.False(formal.HasPending); Assert.False(Directory.Exists(fixture.Root)); Assert.True(result.ResourcesReleased);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Integrated_account_stop_or_replacement_drains_noncooperative_resource_callbacks(bool replace)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        var credentials = new AccountCredentials();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var observing = AccountSignal(); var releaseObservation = AccountSignal();
        var cancellationEntered = AccountSignal(); var cleanupEntered = AccountSignal(); var finish = AccountSignal();
        using var releaseCancellation = new ManualResetEventSlim();
        source.BeforeObserve = async _ => { observing.TrySetResult(); await releaseObservation.Task.WaitAsync(AccountGuard); };
        source.OnToken = token => token.Register(() =>
        {
            cancellationEntered.TrySetResult();
            if (!releaseCancellation.Wait(AccountGuard)) throw new TimeoutException("Synthetic cancellation release timed out.");
        });
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(
            fixture.Root, source, cleanupEntered: () => cleanupEntered.TrySetResult()));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), credentials, resources);
        var run = runtime.RunAsync(); Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(AccountGuard);
            if (replace) session.Begin("replacement", "other"); else runtime.Stop();
            Assert.Null(runtime.Publication); Assert.False(runtime.Snapshot.HasCurrentResources);
            await cancellationEntered.Task.WaitAsync(AccountGuard);
            Assert.False(run.IsCompleted); Assert.Equal(0, source.Disposals);
            releaseObservation.SetResult(); await cleanupEntered.Task.WaitAsync(AccountGuard);
            await AccountWaitFor(() => runtime.Snapshot.Connection.Phase == AccountConnectionPhase.Ended);
            disposal = runtime.DisposeAsync().AsTask();
            Assert.Same(disposal, runtime.DisposeAsync().AsTask());
            Assert.False(run.IsCompleted); Assert.False(disposal.IsCompleted);
            Assert.False(resources.HasCurrentResources); Assert.False(resources.TryReadCatalogs(out _));
            Assert.Equal(0, source.Disposals); Assert.False(Directory.Exists(fixture.Root));
        }
        finally { releaseObservation.TrySetResult(); releaseCancellation.Set(); finish.TrySetResult(); }
        var result = await run.WaitAsync(AccountGuard);
        await (disposal ?? runtime.DisposeAsync().AsTask()).WaitAsync(AccountGuard);
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
        Assert.Equal(replace ? AccountConnectionEndReason.ConnectionEnded : AccountConnectionEndReason.Stopped,
            result.Connection.Status.EndReason);
        Assert.True(Assert.Single(result.Connection.Status.History).LoginProtocolCompleted);
        Assert.True(Assert.Single(credentials.Values).IsDisposed);
        Assert.Single(credentials.Requests);
        var preparation = Assert.Single(result.ResourceHistory).Preparation;
        Assert.False(preparation.WasBound); Assert.Equal(AccountResourcePreparationStatus.Cancelled, preparation.Status);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, preparation.StorageOutcome);
        Assert.False(runtime.Snapshot.HasCurrentResources); Assert.Null(runtime.Publication);
        Assert.Equal(1, source.Disposals); Assert.True(result.ResourcesReleased);
        if (replace) { Assert.Equal("replacement", session.Snapshot.AccountId); Assert.Equal(generation + 1, session.Snapshot.Generation); }
    }

    [Theory]
    [InlineData("stop")]
    [InlineData("hold")]
    [InlineData("disconnect")]
    [InlineData("eof")]
    public async Task Integrated_account_queued_bootstrap_is_cancelled_before_resource_admission(string revoke)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var queued = AccountSignal(); var cancelled = AccountSignal(); var releaseAdmission = AccountSignal(); var finish = AccountSignal();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task);
            if (revoke == "eof") await client.CloseSendAndExpectEof();
            else await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources,
            new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMinutes(1), MaximumRetryDelay = TimeSpan.FromMinutes(1) },
            beforePreparationAdmission: async token =>
            {
                using var registration = token.Register(() => cancelled.TrySetResult());
                queued.TrySetResult(); await releaseAdmission.Task.WaitAsync(AccountGuard);
            });
        var run = runtime.RunAsync();
        try
        {
            await queued.Task.WaitAsync(AccountGuard);
            Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
            switch (revoke)
            {
                case "stop": runtime.Stop(); break;
                case "hold": Assert.True(session.Hold(generation)); break;
                case "disconnect": session.Disconnect(); break;
                case "eof": finish.SetResult(); break;
            }
            await cancelled.Task.WaitAsync(AccountGuard);
            if (revoke == "eof")
                await AccountWaitFor(() => runtime.Snapshot.Connection.Phase == AccountConnectionPhase.RetryWaiting);
            Assert.False(run.IsCompleted); Assert.Empty(runtime.Snapshot.ResourceHistory);
            Assert.Equal(0, source.Observations); Assert.False(runtime.Snapshot.HasCurrentResources);
            releaseAdmission.SetResult();
            await AccountWaitFor(() => runtime.Snapshot.ResourceHistory.Length == 1);
            var preparation = Assert.Single(runtime.Snapshot.ResourceHistory).Preparation;
            Assert.Equal(AccountResourcePreparationStatus.Cancelled, preparation.Status);
            Assert.Equal(AccountResourceStorageOutcome.NotAttempted, preparation.StorageOutcome);
            Assert.False(preparation.WasBound); Assert.False(preparation.ReadbackMatched); Assert.False(preparation.SourcesRechecked);
            Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
            runtime.Stop(); var result = await run.WaitAsync(AccountGuard);
            Assert.True(result.ResourcesReleased); Assert.Equal(1, source.Disposals);
            Assert.Equal(preparation, Assert.Single(result.ResourceHistory).Preparation);
        }
        finally { releaseAdmission.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Integrated_account_reconnect_uses_readonly_refresh_and_keeps_historical_receipts()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var reconnect = AccountSignal(); var finish = AccountSignal();
        var first = verification.Run(AccountVerify, AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(reconnect.Task); await client.CloseSendAndExpectEof();
        }, async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var modes = new ConcurrentQueue<SqliteOpenMode>(); var connections = new ConcurrentQueue<ScriptedReadConnection>();
        var credentials = new AccountCredentials();
        var resources = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
            {
                WrapConnection = connection =>
                {
                    modes.Enqueue(new SqliteConnectionStringBuilder(connection.ConnectionString).Mode);
                    var tracked = new ScriptedReadConnection(connection); connections.Enqueue(tracked); return tracked;
                }
            }));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), credentials, resources,
            new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMilliseconds(100), MaximumRetryDelay = TimeSpan.FromMilliseconds(100) });
        var run = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.Snapshot.ResourceHistory.Length == 1);
            byte[] original = fixture.Bytes(); var firstPublication = runtime.Publication!;
            reconnect.SetResult();
            await AccountWaitFor(() => runtime.Snapshot.ResourceHistory.Length == 2);
            Assert.NotEqual(firstPublication.Receive.Attempt, runtime.Publication!.Receive.Attempt);
            var history = runtime.Snapshot.ResourceHistory;
            Assert.Equal(new[] { generation, generation + 1 }, history.Select(item => item.Generation));
            Assert.Equal(new[] { 1, 2 }, history.Select(item => item.AttemptNumber));
            Assert.All(history, item =>
            {
                Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, item.Preparation.Status);
                Assert.True(item.Preparation.ReadbackMatched); Assert.True(item.Preparation.SourcesRechecked);
                Assert.False(item.Preparation.WasBound);
            });
            Assert.Equal(AccountResourceStorageOutcome.Committed, history[0].Preparation.StorageOutcome);
            Assert.Equal(AccountResourceStorageOutcome.NotAttempted, history[1].Preparation.StorageOutcome);
            Assert.Equal(new[] { SqliteOpenMode.ReadWriteCreate, SqliteOpenMode.ReadOnly, SqliteOpenMode.ReadOnly }, modes.ToArray());
            Assert.All(connections, connection => Assert.True(connection.WasDisposed));
            Assert.All(connections.Skip(1), connection => Assert.DoesNotContain(connection.Commands,
                sql => sql.StartsWith("INSERT", StringComparison.Ordinal) || sql.StartsWith("CREATE", StringComparison.Ordinal) || sql.StartsWith("UPDATE", StringComparison.Ordinal)));
            Assert.Equal(original, fixture.Bytes()); Assert.Equal(1L, fixture.Sql("SELECT count(*) FROM versions"));
            Assert.Equal(new[] { generation, generation + 1 }, credentials.Requests.Select(request => request.Generation));
            Assert.Equal(new[] { 1, 2 }, credentials.Requests.Select(request => request.AttemptNumber));
            Assert.All(credentials.Values, value => Assert.True(value.IsDisposed));
            AccountHeld(runtime, session); Assert.False(runtime.Snapshot.HasCurrentResources);
            runtime.Stop(); var result = await run.WaitAsync(AccountGuard);
            Assert.Equal(history, result.ResourceHistory); Assert.True(result.ResourcesReleased);
            Assert.Equal(2, result.Connection.Status.History.Length);
            Assert.All(result.Connection.Status.History, attempt => Assert.True(attempt.LoginProtocolCompleted));
        }
        finally { reconnect.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Integrated_account_reconnect_drains_old_resource_work_before_readonly_refresh()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var readbackEntered = AccountSignal(); var releaseReadback = AccountSignal(); var oldCancelled = AccountSignal();
        var reconnect = AccountSignal(); var secondLogin = AccountSignal(); var finish = AccountSignal();
        source.OnToken = token => token.Register(() => oldCancelled.TrySetResult());
        var first = verification.Run(AccountVerify, AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(reconnect.Task); await client.CloseSendAndExpectEof();
        }, async client =>
        {
            await AccountEnterWorld(client); secondLogin.SetResult();
            // Stop retires this connection before finish is released; only the first peer initiates EOF.
            await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var modes = new ConcurrentQueue<SqliteOpenMode>();
        var resources = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
            {
                BeforeReadback = async () =>
                {
                    readbackEntered.TrySetResult();
                    // Deliberately ignore cancellation until the test permits this old callback to retire.
                    await releaseReadback.Task.WaitAsync(AccountGuard);
                },
                WrapConnection = connection =>
                {
                    modes.Enqueue(new SqliteConnectionStringBuilder(connection.ConnectionString).Mode);
                    return connection;
                }
            }));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources,
            new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMilliseconds(100), MaximumRetryDelay = TimeSpan.FromMilliseconds(100) });
        var run = runtime.RunAsync();
        try
        {
            await readbackEntered.Task.WaitAsync(AccountGuard);
            byte[] committed = fixture.Bytes(); int observations = source.Observations;
            Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
            reconnect.SetResult(); await oldCancelled.Task.WaitAsync(AccountGuard);
            await secondLogin.Task.WaitAsync(AccountGuard);
            await AccountWaitFor(() => runtime.Snapshot.Connection is
                { AttemptNumber: 2, Phase: AccountConnectionPhase.ReceivingHeld });
            Assert.Empty(runtime.Snapshot.ResourceHistory);
            Assert.Equal(observations, source.Observations); // New resource acquisition cannot overtake old cleanup.
            Assert.Equal(new[] { SqliteOpenMode.ReadWriteCreate }, modes.ToArray());
            Assert.False(runtime.Snapshot.HasCurrentResources); Assert.Null(runtime.Publication!.Catalogs);
            Assert.False(resources.TryReadCatalogs(out _)); Assert.Equal(0, source.Disposals);
            releaseReadback.SetResult();
            await AccountWaitFor(() => runtime.Snapshot.ResourceHistory.Length == 2);
            var history = runtime.Snapshot.ResourceHistory;
            Assert.Equal(generation, history[0].Generation);
            Assert.Equal(AccountResourcePreparationStatus.Cancelled, history[0].Preparation.Status);
            Assert.Equal(AccountResourceStorageOutcome.Committed, history[0].Preparation.StorageOutcome);
            Assert.False(history[0].Preparation.WasBound); Assert.False(history[0].Preparation.ReadbackMatched);
            Assert.Equal(generation + 1, history[1].Generation);
            Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, history[1].Preparation.Status);
            Assert.Equal(AccountResourceStorageOutcome.NotAttempted, history[1].Preparation.StorageOutcome);
            Assert.True(history[1].Preparation.ReadbackMatched); Assert.True(history[1].Preparation.SourcesRechecked);
            Assert.Equal(new[] { SqliteOpenMode.ReadWriteCreate, SqliteOpenMode.ReadOnly }, modes.ToArray());
            Assert.Equal(committed, fixture.Bytes()); AccountHeld(runtime, session);
            runtime.Stop(); var result = await run.WaitAsync(AccountGuard);
            Assert.True(result.ResourcesReleased); Assert.Equal(history, result.ResourceHistory);
        }
        finally { releaseReadback.TrySetResult(); reconnect.TrySetResult(); runtime.Stop(); finish.TrySetResult(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Integrated_account_whitebox_trust_bit_projects_current_catalogs_into_real_receive_then_revokes(bool includeInstances)
    {
        using var fixture = new Fixture(); var source = includeInstances ? WithInstanceCatalog() : new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var sendBound = AccountSignal(); var sendRevoked = AccountSignal(); var finish = AccountSignal();
        Packet? schedules = null;
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client);
            await client.WaitFor(sendBound.Task); await client.Send(schedules!);
            await client.WaitFor(sendRevoked.Task); await client.Send(schedules!);
            // The test signals finish only after local Stop has drained resources.
            await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        // WHITE-BOX WIRING ONLY: simulate the private admission bit, never real TLS,
        // production provenance, resource acceptance, or command authorization. The ordinary
        // synthetic-source integration tests above must continue to report NotAdmitted.
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var run = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.Snapshot.HasCurrentResources);
            var bound = runtime.Publication!; Assert.NotNull(bound.Catalogs);
            ushort rosterScene=bound.Receive.State.Player!.Scene;
            bool rosterAvailable=runtime.TryGetSceneNpcRoster(rosterScene,out var npcRoster);
            Assert.Equal(bound.Catalogs.Stages.ContainsKey(rosterScene),rosterAvailable);
            if(npcRoster is not null){Assert.True(npcRoster.TryReadRows(out var rows));Assert.All(rows,row=>Assert.False(row.CanInteract));Assert.False(npcRoster.CanSendPackets);}
            Assert.False(runtime.TryGetSceneNpcRoster((ushort)(rosterScene+1),out _));
            Assert.True(Assert.Single(runtime.Snapshot.ResourceHistory).Preparation.WasBound);
            var scheduleRows = bound.Catalogs.Recipes.Catalog;
            Assert.NotEmpty(scheduleRows);
            var writer = new PacketWriter();
            for (int i = 0; i < scheduleRows.Length; i++)
            {
                var row = scheduleRows[i].Recipe;
                writer.U8(checked((byte)(i + 1))).U16(row.RecipeId ?? row.ItemId).U32(2500).U8(2).U32(60);
            }
            schedules = new Packet(64, 1, writer.U8(0).Build());
            long revision = bound.Receive.Revision; sendBound.SetResult();
            await AccountWaitFor(() => runtime.Publication!.Receive.Revision > revision);
            var observed = runtime.Publication!; var inputs = observed.Receive.State.Observation!.Inputs;
            Assert.NotNull(inputs.WorldCatalog); Assert.NotNull(inputs.ItemStackRules);
            Assert.True(inputs.WorldCatalog.StageIds.SetEquals(bound.Catalogs.Stages.Keys));
            Assert.Equal(bound.Catalogs.Items.Count(pair => pair.Value.ReviewedDetails is not null), inputs.ItemStackRules.Count);
            Assert.All(bound.Catalogs.Items.Where(pair => pair.Value.ReviewedDetails is not null), pair =>
                Assert.Equal(pair.Value.ReviewedDetails!.Stackable, inputs.ItemStackRules[pair.Key]));
            Assert.Null(inputs.KnowledgeCatalog); Assert.Null(inputs.NpcSkills); Assert.True(inputs.ResourceHeld);
            Assert.True(inputs.ReconcileNpcSkills);
            Assert.NotNull(inputs.CraftingSchedules);
            Assert.True(inputs.TrackUnsupportedCraftingSchedules);
            Assert.Equal(scheduleRows.Length, observed.Receive.State.Crafting.Crafting.Queue.Count);
            for (int i = 0; i < scheduleRows.Length; i++)
            {
                var row = observed.Receive.State.Crafting.Crafting.Queue[(byte)(i + 1)];
                Assert.Equal(scheduleRows[i].Recipe.ItemId, row.ItemId);
                Assert.Equal(scheduleRows[i].Recipe.RecipeId, row.RecipeId);
            }
            if (includeInstances)
            {
                Assert.NotNull(bound.Catalogs.OptionalInstances);
                Assert.NotEmpty(inputs.DeclaredMainCatalogMapIds);
                Assert.True(inputs.DeclaredMainCatalogMapIds.SetEquals(bound.Catalogs.OptionalInstances.DeclaredMainMapIds));
            }
            else Assert.Empty(inputs.DeclaredMainCatalogMapIds);
            Assert.True(observed.ResourceHeld); Assert.False(observed.CanSendCommands); Assert.False(bound.Catalogs.RuntimeAdmitted);
            Assert.Equal(nameof(AccountRuntimePublication), observed.ToString()); AccountHeld(runtime, session);
            resources.Invalidate();
            Assert.False(runtime.Snapshot.HasCurrentResources); Assert.Null(runtime.Publication!.Catalogs);
            if(npcRoster is not null)Assert.False(npcRoster.TryReadRows(out _));
            Assert.False(runtime.TryGetSceneNpcRoster(rosterScene,out _));
            revision = runtime.Publication.Receive.Revision; sendRevoked.SetResult();
            await AccountWaitFor(() => runtime.Publication!.Receive.Revision > revision);
            var revoked = runtime.Publication!.Receive.State.Observation!.Inputs;
            Assert.Null(revoked.WorldCatalog); Assert.Null(revoked.ItemStackRules); Assert.True(revoked.ResourceHeld);
            Assert.Empty(revoked.DeclaredMainCatalogMapIds);
            Assert.Null(revoked.NpcSkills); Assert.True(revoked.ReconcileNpcSkills);
            Assert.Null(revoked.CraftingSchedules);
            Assert.True(revoked.TrackUnsupportedCraftingSchedules);
            Assert.Equal("unsupported_decoder", runtime.Publication!.Receive.State.Observation!.EventType);
            var revokedCrafting = runtime.Publication.Receive.State.Crafting.Crafting;
            Assert.Same(observed.Receive.State.Crafting.Crafting.Queue, revokedCrafting.Queue);
            Assert.False(revokedCrafting.Ready); Assert.True(revokedCrafting.Uncertain);
            Assert.False(revokedCrafting.Running); Assert.Null(revokedCrafting.StartedAt);
            Assert.True(observed.Receive.State.Crafting.Crafting.Ready);
            Assert.NotNull(inputs.CraftingSchedules);
            Assert.NotNull(observed.Catalogs); Assert.NotNull(inputs.WorldCatalog); // Retained values are historical only.
            runtime.Stop(); Assert.Null(runtime.Publication);
            var result = await run.WaitAsync(AccountGuard); Assert.True(result.ResourcesReleased);
            Assert.True(Assert.Single(result.ResourceHistory).Preparation.WasBound);
            Assert.False(resources.HasCurrentResources); Assert.Equal(1, source.Disposals);
        }
        finally { sendBound.TrySetResult(); sendRevoked.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }
}
