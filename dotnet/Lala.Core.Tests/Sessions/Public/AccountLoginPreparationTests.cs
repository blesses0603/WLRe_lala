using System.Net;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Handshake;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    private sealed class Input(Func<AccountLoginDisclosure, CancellationToken, ValueTask<AccountLoginCredentials?>> acquire) : IAccountLoginInput
    {
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token) => acquire(disclosure, token);
    }
    private sealed class PreparationClock : TimeProvider
    {
        private long timestamp;
        private readonly List<ManualTimer> timers = [];
        public override long TimestampFrequency => TimeSpan.TicksPerSecond;
        public override long GetTimestamp() => Interlocked.Read(ref timestamp);
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        {
            var timer = new ManualTimer(this, callback, state);
            lock (timers) timers.Add(timer);
            timer.Change(dueTime, period); return timer;
        }
        internal void Advance(TimeSpan duration, bool fireTimers = true)
        {
            Interlocked.Add(ref timestamp, duration.Ticks);
            ManualTimer[] copy; lock (timers) copy = timers.ToArray();
            if (fireTimers) foreach (var timer in copy) timer.Fire();
        }
        internal int TimerCount { get { lock (timers) return timers.Count; } }
        internal void FireEarly()
        {
            ManualTimer[] copy; lock (timers) copy = timers.ToArray();
            foreach (var timer in copy) timer.Fire(early: true);
        }
        private sealed class ManualTimer(PreparationClock clock, TimerCallback callback, object? state) : ITimer
        {
            private readonly object gate = new();
            private long? due;
            private bool disposed;
            public bool Change(TimeSpan dueTime, TimeSpan period)
            {
                Assert.Equal(Timeout.InfiniteTimeSpan, period);
                lock (gate)
                {
                    if (disposed) return false;
                    due = dueTime == Timeout.InfiniteTimeSpan ? null : clock.GetTimestamp() + dueTime.Ticks;
                    return true;
                }
            }
            internal void Fire(bool early = false)
            {
                lock (gate)
                {
                    if (disposed || due is null || (!early && clock.GetTimestamp() < due)) return;
                    due = null;
                }
                callback(state);
            }
            public void Dispose() { lock (gate) { disposed = true; due = null; } }
            public ValueTask DisposeAsync() { Dispose(); return ValueTask.CompletedTask; }
        }
    }
    private static async Task ExpectPreparedLogin(Client client, byte leg)
    {
        var packet = await client.Next();
        Assert.Equal(63, packet.Main); Assert.Equal(7, packet.Sub);
        var expected = new byte[] { leg, 0, 1, 2, 9 }.Concat("synthetic"u8.ToArray())
            .Concat(new byte[] { 13 }).Concat("fake_password"u8.ToArray());
        Assert.Equal(expected, packet.Payload.ToArray());
    }

    [Fact]
    public async Task PreparedLoginPinsExactDisclosureAndActualRecipientsForOneHeldAttempt()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var verificationEndpoint = verification.Endpoint; var formalEndpoint = formal.Endpoint;
        var profile = new AccountConnectionProfile(verificationEndpoint, formalEndpoint, 0xAD, 0xAD, 1, 1, 2);
        var session = new AccountSession(); var generation = session.Begin("opaque-selection", "test").Generation;
        var identity = Guid.NewGuid(); var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        int acquired = 0; AccountLoginDisclosure? disclosed = null; var clock = new PreparationClock();
        await using var preparation = new AccountLoginPreparation(session, generation, identity, profile,
            new Input((value, _) => { acquired++; disclosed = value; return ValueTask.FromResult<AccountLoginCredentials?>(credentials); }), null, null, clock);
        verificationEndpoint.Port = 1; formalEndpoint.Port = 1; preparation.Disclosure.Profile.FormalEndpoint.Port = 1;
        Assert.Same(profile, preparation.Disclosure.Profile);
        Assert.Equal(identity, preparation.Disclosure.SelectedIdentity);
        Assert.Equal(generation, preparation.Disclosure.Generation); Assert.Equal(1, preparation.Disclosure.AttemptNumber);
        Assert.Contains("both named recipients", preparation.Disclosure.Risk); Assert.Contains("not TLS", preparation.Disclosure.Risk);
        Assert.Equal(AccountConnectionPhase.Created, preparation.Snapshot.Phase); Assert.Equal(0, acquired);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        var ready = Signal(); var finish = Signal(); var afterExpiry = Signal(); var heartbeat = Signal();
        var first = verification.Run(async client =>
        {
            await ExpectPreparedLogin(client, 0); await client.Send(new Packet(63, 7, [0, 0]));
            await client.CloseSendAndExpectEof();
        });
        var second = formal.Run(async client =>
        {
            await ExpectPreparedLogin(client, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
            await client.Expect(63, 2, 1); await client.Send(World, new Packet(1, 11));
            await client.Expect(12, 1); await client.Expect(3, 2); ready.SetResult();
            await client.WaitFor(afterExpiry.Task); await client.Send(new Packet(1, 23));
            await client.Expect(63, 5); heartbeat.SetResult();
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var run = preparation.RunAsync(); Assert.Same(run, preparation.RunAsync());
        await ready.Task.WaitAsync(Guard);
        await WaitFor(() => preparation.Snapshot.Phase == AccountConnectionPhase.ReceivingHeld);
        Assert.Same(preparation.Disclosure, disclosed); Assert.True(credentials.IsDisposed); Assert.Equal(1, acquired);
        Assert.True(preparation.Snapshot.ResourceHeld); Assert.False(preparation.Snapshot.CanSendCommands);
        clock.Advance(TimeSpan.FromMinutes(1)); afterExpiry.SetResult(); await heartbeat.Task.WaitAsync(Guard);
        Assert.False(run.IsCompleted); Assert.Equal(AccountConnectionPhase.ReceivingHeld, preparation.Snapshot.Phase);
        Assert.NotNull(preparation.Publication); Assert.False(session.ConfirmResources(generation, "v", "v", true));
        preparation.Stop(); var result = await run.WaitAsync(Guard); finish.SetResult();
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.Single(result.Status.History);
        Assert.Same(run, preparation.RunAsync()); Assert.Equal(1, acquired);
        Assert.DoesNotContain(identity.ToString(), preparation.ToString());
        Assert.DoesNotContain(identity.ToString(), preparation.Disclosure.ToString());
    }

    [Theory]
    [InlineData("stop")] [InlineData("cancel")] [InlineData("replace")]
    [InlineData("disconnect")] [InlineData("hold")] [InlineData("expiry")]
    public async Task PreparedPendingInputRetirementKeepsCleanupPendingAndClearsLateCredentials(string action)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation;
        var entered = Signal(); var release = Signal(); var tokenCancelled = Signal();
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        using var cancellation = new CancellationTokenSource();
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input(async (_, token) =>
            {
                using var registration = token.Register(() => tokenCancelled.TrySetResult());
                entered.SetResult(); await release.Task; return credentials; // Deliberately ignores cancellation.
            }), validity: action == "expiry" ? TimeSpan.FromMilliseconds(200) : null);
        try
        {
            var run = preparation.RunAsync(cancellation.Token); await entered.Task.WaitAsync(Guard);
            switch (action)
            {
                case "stop": preparation.Stop(); break;
                case "cancel": cancellation.Cancel(); break;
                case "replace": session.Begin("different", "different"); break;
                case "disconnect": session.Disconnect(); break;
                case "hold": Assert.True(session.Hold(generation)); break;
            }
            await tokenCancelled.Task.WaitAsync(Guard);
            Assert.False(run.IsCompleted); Assert.False(credentials.IsDisposed);
            var cleanup = preparation.DisposeAsync().AsTask(); Assert.False(cleanup.IsCompleted);
            release.SetResult(); var result = await run.WaitAsync(Guard); await cleanup.WaitAsync(Guard);
            Assert.True(result.ResourcesReleased); Assert.True(credentials.IsDisposed);
            Assert.False(verification.HasPending); Assert.False(formal.HasPending); Assert.Empty(result.Status.History);
        }
        finally { release.TrySetResult(); preparation.Stop(); }
    }

    [Theory]
    [InlineData("stop")] [InlineData("cancel")] [InlineData("replace")]
    [InlineData("disconnect")] [InlineData("hold")] [InlineData("expiry")]
    public async Task PreparedRevocationBetweenVerificationAndFormalNeverSendsFormalCredentials(string action)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation;
        var received = Signal(); var release = Signal(); var clock = new PreparationClock();
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        using var cancellation = new CancellationTokenSource();
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials)), null, null, clock);
        var server = verification.Run(async client =>
        {
            await ExpectPreparedLogin(client, 0); received.SetResult(); await client.WaitFor(release.Task);
            if (action == "expiry") await client.Send(new Packet(63, 7, [0, 0]));
            await client.ExpectClosedAfterRetirement();
        });
        var run = preparation.RunAsync(cancellation.Token); await received.Task.WaitAsync(Guard);
        switch (action)
        {
            case "stop": preparation.Stop(); break;
            case "cancel": cancellation.Cancel(); break;
            case "replace": session.Begin("different", "different"); break;
            case "disconnect": session.Disconnect(); break;
            case "hold": Assert.True(session.Hold(generation)); break;
            case "expiry": clock.Advance(TimeSpan.FromMinutes(1), fireTimers: false); break;
        }
        release.SetResult(); var result = await run.WaitAsync(Guard); await server.WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.True(credentials.IsDisposed);
        // Expiry may connect the formal socket before MakeLogin rejects; zero credential bytes may be sent.
        if (formal.HasPending)
        {
            var formalServer = formal.Run(client => Assert.ThrowsAsync<IOException>(() => client.Next()));
            await formalServer.WaitAsync(Guard);
        }
        Assert.Single(result.Status.History); Assert.False(result.Status.History[0].LoginProtocolCompleted);
    }

    [Theory]
    [InlineData(59, true)] [InlineData(60, false)] [InlineData(61, false)]
    public async Task PreparedConstructionLifetimeIsMonotonicAndChecksExactExpiryBeforeInput(int seconds, bool expectedInput)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation;
        var clock = new PreparationClock(); int acquired = 0;
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input((_, _) => { acquired++; return ValueTask.FromResult<AccountLoginCredentials?>(null); }), null, null, clock);
        clock.Advance(TimeSpan.FromSeconds(seconds)); var result = await preparation.RunAsync().WaitAsync(Guard);
        Assert.Equal(expectedInput ? 1 : 0, acquired); Assert.True(result.ResourcesReleased);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task PreparedDeclineOrInputFailureNeverConnectsOrReacquires(bool fail)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation; int acquired = 0;
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal), new Input((_, _) =>
        {
            acquired++;
            if (fail) throw new InvalidOperationException("private synthetic error", new Exception("private synthetic inner"));
            return ValueTask.FromResult<AccountLoginCredentials?>(null);
        }));
        var run = preparation.RunAsync(); var result = await run.WaitAsync(Guard);
        Assert.Same(run, preparation.RunAsync()); Assert.Equal(1, acquired);
        Assert.Equal(fail ? AccountConnectionEndReason.ProviderFailed : AccountConnectionEndReason.CredentialsUnavailable, result.Status.EndReason);
        Assert.DoesNotContain("private synthetic", result.ToString()); Assert.True(result.ResourcesReleased);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
    }

    [Theory]
    [InlineData("cancel")] [InlineData("dispose")] [InlineData("hold")] [InlineData("replace")]
    public async Task PreparedRetirementBeforeRunNeverAcquires(string action)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation; int acquired = 0;
        using var stop = new CancellationTokenSource();
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input((_, _) => { acquired++; return ValueTask.FromResult<AccountLoginCredentials?>(null); }));
        if (action == "cancel") stop.Cancel();
        if (action == "dispose") await preparation.DisposeAsync();
        if (action == "hold") session.Hold(generation);
        if (action == "replace") session.Begin("new", "new");
        var result = await preparation.RunAsync(stop.Token).WaitAsync(Guard);
        Assert.Equal(0, acquired); Assert.True(result.ResourcesReleased);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
    }

    [Fact]
    public void PreparedRejectsRetriesInvalidIdentityStaleGenerationAndUnboundedLifetime()
    {
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation;
        var profile = new AccountConnectionProfile(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 2), 0, 0, 1, 1, 2);
        var input = new Input((_, _) => throw new Exception("never called"));
        Assert.Throws<ArgumentException>(() => new AccountLoginPreparation(session, generation, Guid.Empty, profile, input));
        Assert.Throws<ArgumentException>(() => new AccountLoginPreparation(session, generation, Guid.NewGuid(), profile, input, new() { MaximumAttempts = 2 }));
        Assert.Throws<InvalidOperationException>(() => new AccountLoginPreparation(session, generation + 1, Guid.NewGuid(), profile, input));
        foreach (var lifetime in new[] { TimeSpan.Zero, TimeSpan.FromSeconds(-1), TimeSpan.FromSeconds(61) })
            Assert.Throws<ArgumentOutOfRangeException>(() => new AccountLoginPreparation(session, generation, Guid.NewGuid(), profile, input, validity: lifetime));
    }
    private sealed class BeforeWireProvider(IHandshakeLoginProvider inner, HandshakeLeg atLeg, Action beforeReturn) : IHandshakeLoginProvider
    {
        public LoginPacketLease Create(HandshakeLeg leg)
        {
            var packet = inner.Create(leg);
            if (leg == atLeg) beforeReturn();
            return packet;
        }
        public void Dispose() => inner.Dispose();
    }

    [Theory]
    [InlineData(false, "expiry")] [InlineData(true, "expiry")]
    [InlineData(false, "hold")] [InlineData(true, "hold")]
    [InlineData(false, "cancel")] [InlineData(true, "cancel")]
    public async Task PreparedActualWriteAdmissionRechecksAfterCredentialPacketWasBuilt(bool formalLeg, string action)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var snapshot = session.Begin("opaque", "test");
        var profile = Profile(verification, formal); var clock = new PreparationClock();
        var admission = new AccountLoginAdmission(session, snapshot, profile, TimeSpan.FromMinutes(1), clock);
        using var cancellation = new CancellationTokenSource(); admission.SetCancellation(cancellation.Token);
        var credentials = new AccountLoginCredentials("synthetic", "fake_password"); int built = 0;
        var provider = new BeforeWireProvider(credentials.CreateProvider(1, 2), formalLeg ? HandshakeLeg.Formal : HandshakeLeg.Verification, () =>
        {
            built++;
            if (action == "expiry") clock.Advance(TimeSpan.FromMinutes(1), fireTimers: false);
            if (action == "hold") session.Hold(snapshot.Generation);
            if (action == "cancel") cancellation.Cancel();
        });
        var first = verification.Run(formalLeg ? Verify : client => Assert.ThrowsAsync<IOException>(() => client.Next()));
        Task? second = formalLeg ? formal.Run(client => Assert.ThrowsAsync<IOException>(() => client.Next())) : null;
        await using var connection = HeldAccountConnection.TryAttach(session, snapshot.Generation,
            profile.VerificationEndpoint, profile.FormalEndpoint, profile.TransmitXor, profile.ReceiveXor, profile.RoleIndex,
            null, () => 0, (_, now) => new(now), ownedProvider: provider, loginAdmission: admission);
        Assert.NotNull(connection);
        var result = await connection.RunAsync().WaitAsync(Guard);
        await first.WaitAsync(Guard); if (second is not null) await second.WaitAsync(Guard);
        Assert.Equal(1, built); Assert.True(credentials.IsDisposed); Assert.True(result.ResourcesReleased);
        if (!formalLeg) Assert.False(formal.HasPending);
    }

    [Fact]
    public async Task PreparedEarlyTimerWakeRearmsBeforeCancellingAtExactDeadline()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("opaque", "test").Generation;
        var entered = Signal(); var release = Signal(); var cancelled = Signal(); var clock = new PreparationClock();
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input(async (_, token) =>
            {
                using var registration = token.Register(() => cancelled.TrySetResult());
                entered.SetResult(); await release.Task; return credentials;
            }), null, null, clock);
        try
        {
            var run = preparation.RunAsync(); await entered.Task.WaitAsync(Guard);
            clock.Advance(TimeSpan.FromSeconds(59)); clock.FireEarly();
            await WaitFor(() => clock.TimerCount == 2);
            Assert.False(cancelled.Task.IsCompleted); Assert.False(run.IsCompleted);
            clock.Advance(TimeSpan.FromSeconds(1)); await cancelled.Task.WaitAsync(Guard);
            Assert.False(run.IsCompleted); release.SetResult();
            var result = await run.WaitAsync(Guard);
            Assert.True(result.ResourcesReleased); Assert.True(credentials.IsDisposed);
            Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        }
        finally { release.TrySetResult(); preparation.Stop(); }
    }

}
