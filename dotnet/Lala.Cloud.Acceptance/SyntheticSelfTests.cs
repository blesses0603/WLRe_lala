using System.Runtime.InteropServices;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Sessions;

namespace Lala.Cloud.Acceptance;

internal static partial class SyntheticSelfTests
{
    private static readonly TimeSpan Guard = TimeSpan.FromSeconds(15);
    private static AcceptanceOptions Quick => new()
    {
        OverallTimeout = TimeSpan.FromSeconds(5),
        ObservationWindow = TimeSpan.FromSeconds(1),
        PollInterval = TimeSpan.FromMilliseconds(2),
        LoginTimeout = TimeSpan.FromSeconds(4),
        ConnectTimeout = TimeSpan.FromSeconds(2),
        ReadTimeout = TimeSpan.FromSeconds(5),
        WriteTimeout = TimeSpan.FromSeconds(2)
    };

    internal static void Check(bool condition, AcceptanceResult? result = null, [CallerLineNumber] int assertionLine = 0)
    {
        if (!condition) throw new SyntheticTestFailure(assertionLine, result);
    }

    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static async Task WaitFor(Func<bool> condition, CancellationToken token)
    {
        while (!condition()) await Task.Delay(1, token).ConfigureAwait(false);
    }

    private static AccountLoginCredentials Credentials()
    {
        char[] account = ['s', 'y', 'n', 't', 'h', 'e', 't', 'i', 'c'];
        char[] password = ['f', 'a', 'k', 'e', '_', 's', 'e', 'c', 'r', 'e', 't'];
        try { return new(account, password); }
        finally
        {
            CryptographicOperations.ZeroMemory(MemoryMarshal.AsBytes(account.AsSpan()));
            CryptographicOperations.ZeroMemory(MemoryMarshal.AsBytes(password.AsSpan()));
        }
    }

    private sealed class Source(Func<AccountCredentialRequest, CancellationToken, ValueTask<AccountLoginCredentials?>> acquire)
        : IAccountCredentialSource, IDisposable
    {
        private int calls;
        internal int Calls => Volatile.Read(ref calls);
        internal bool Disposed { get; private set; }
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken token)
        {
            Interlocked.Increment(ref calls);
            Check(request.Generation == 1 && request.AttemptNumber == 1);
            return acquire(request, token);
        }
        public void Dispose() => Disposed = true;
        public override string ToString() => throw new SyntheticTestFailure();
    }

    private static AccountConnectionProfile Profile(SyntheticPeer verification, SyntheticPeer formal) =>
        new(verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1, 1, 2);

    private static void Released(AcceptanceResult result, Source source, AccountLoginCredentials? credentials = null)
    {
        Check(result.Cleanup == CleanupDisposition.Released);
        Check(result.AttemptCount <= 1 && source.Calls <= 1 && !source.Disposed);
        Check(credentials is null || credentials.IsDisposed);
    }

    internal static async Task<int> RunAsync()
    {
        (Scenario Name, Func<Task> Run)[] cases =
        [
            (Scenario.LateHeartbeat, () => Completed(heartbeat: true, initialFirst: false)),
            (Scenario.LateHeartbeatReversedWorldOrder, () => Completed(heartbeat: true, initialFirst: true)),
            (Scenario.CompletedSilent, () => Completed(heartbeat: false, initialFirst: false)),
            (Scenario.EarlyPostLoginEof, () => InterruptedObservation(protocolError: false)),
            (Scenario.PostLoginProtocolFailure, () => InterruptedObservation(protocolError: true)),
            (Scenario.RejectedLogin, Rejected),
            (Scenario.IncompleteLogin, Incomplete),
            (Scenario.OverallDeadline, () => Interrupted(deadline: true)),
            (Scenario.CallerCancellation, () => Interrupted(deadline: false)),
            (Scenario.LateCredentialAfterDeadline, NoncooperativeSource),
            (Scenario.PreCancelled, PreCancelled),
            (Scenario.ProviderErrorRedaction, () => SourceFailure(throws: true)),
            (Scenario.CredentialDeclined, () => SourceFailure(throws: false)),
            (Scenario.FreshSingleAttempts, FreshAttempts),
            (Scenario.CleanupFailureClassification, Classification),
            (Scenario.OptionBounds, OptionBounds),
            (Scenario.IntegratedPreCancelled, () => IntegratedBeforeLogin(0)),
            (Scenario.IntegratedCredentialDeclined, () => IntegratedBeforeLogin(1)),
            (Scenario.IntegratedProviderError, () => IntegratedBeforeLogin(2)),
            (Scenario.IntegratedRejectedLogin, () => IntegratedBeforeLogin(3)),
            (Scenario.IntegratedIncompleteLogin, () => IntegratedBeforeLogin(4)),
            (Scenario.IntegratedLateCredentials, () => IntegratedBeforeLogin(5)),
            (Scenario.IntegratedRootValidation, IntegratedRootValidation),
            (Scenario.PreparedCompleted, PreparedCompleted),
            (Scenario.PreparedDeclined, () => PreparedUnused(0)),
            (Scenario.PreparedStoppedBeforeRun, () => PreparedUnused(1)),
            (Scenario.PreparedDisposedBeforeRun, () => PreparedUnused(2)),
            (Scenario.PreparedExpiredBeforeRun, () => PreparedUnused(3)),
            (Scenario.PreparedProviderFailure, () => PreparedUnused(4)),
            (Scenario.PreparedPreCancelled, () => PreparedUnused(5)),
            (Scenario.PreparedLateInputStop, () => PreparedLateInput(false)),
            (Scenario.PreparedLateInputExpiry, () => PreparedLateInput(true)),
            (Scenario.PreparedStopBetweenLegs, () => PreparedStopBetweenLegs(false)),
            (Scenario.PreparedExpiryBetweenLegs, () => PreparedStopBetweenLegs(true)),
            (Scenario.PreparedReentrantStop, PreparedReentrantStop),
            (Scenario.PreparedConcurrentRetirement, PreparedConcurrentRetirement)
        ];
        int passed = 0, failed = 0;
        foreach (var test in cases)
        {
            try
            {
                await test.Run().ConfigureAwait(false);
                passed++;
                Console.WriteLine($"SyntheticCase={test.Name};Result=Passed");
            }
            catch (SyntheticTestFailure failure)
            {
                failed++;
                Console.Error.WriteLine($"SyntheticCase={test.Name};Result=Failed;AssertionLine={failure.AssertionLine}");
                if (failure.Result is { } result)
                    Console.Error.WriteLine($"Outcome={result.Outcome};Stop={result.StopReason};End={result.ConnectionEnd};Failure={result.ConnectionFailure};RevisionAdvance={result.RevisionAdvanceCount}");
            }
            catch (Exception)
            {
                failed++;
                // Do not log exception text, source strings, endpoints, or payloads.
                Console.Error.WriteLine($"SyntheticCase={test.Name};Result=Failed");
            }
        }
        Console.WriteLine($"SyntheticSelfTest;Passed={passed};Failed={failed}");
        return failed == 0 ? 0 : 1;
    }

    private static async Task Completed(bool heartbeat, bool initialFirst)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        using var source = new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials));
        var runner = new CloudAcceptanceRunner(Profile(verification, formal), source, Quick);
        Check(source.Calls == 0 && runner.Snapshot.Phase == AcceptancePhase.Created);
        var first = verification.Run(SyntheticClient.Verify);
        var second = formal.Run(async client =>
        {
            await client.EnterWorld(initialFirst).ConfigureAwait(false);
            await WaitFor(() => runner.Snapshot.Receive == ReceiveEvidence.BaselineObserved, guard.Token).ConfigureAwait(false);
            if (heartbeat)
            {
                // A public baseline barrier, not an assumed scheduling delay, makes this late.
                await client.Send(1, 23).ConfigureAwait(false);
                await client.Expect(63, 5, payloadLength: 0).ConfigureAwait(false);
            }
            await client.ExpectEof().ConfigureAwait(false);
        });
        var operation = runner.RunAsync(guard.Token);
        try
        {
            Check(ReferenceEquals(operation, runner.RunAsync(new CancellationToken(canceled: true))));
            var result = await operation.ConfigureAwait(false);
            await Task.WhenAll(first, second).ConfigureAwait(false);
            Released(result, source, credentials);
            Check(result.AttemptCount == 1 && source.Calls == 1);
            Check(result.Outcome == (heartbeat ? AcceptanceOutcome.ProtocolCompleteWithReceiveProgress : AcceptanceOutcome.ProtocolCompleteWithoutReceiveProgress), result);
            Check(result.StopReason == AcceptanceStopReason.ObservationWindowElapsed);
            Check(result.Login == LoginProtocolEvidence.Completed);
            Check(result.Resources == ResourceEvidence.Disabled && runner.Snapshot.Resources == ResourceEvidence.Disabled);
            Check(result.BaselineRevision == 4 && result.RevisionAdvanceCount == (heartbeat ? 1 : 0));
            Check(result.Receive == (heartbeat ? ReceiveEvidence.RevisionAdvanced : ReceiveEvidence.BaselineObserved));
            Check(!verification.HasPending && !formal.HasPending);
            await guard.CancelAsync().ConfigureAwait(false);
            Check(runner.Snapshot.StopReason == AcceptanceStopReason.ObservationWindowElapsed);
        }
        finally
        {
            await guard.CancelAsync().ConfigureAwait(false);
            await operation.ConfigureAwait(false);
        }
    }

    private static async Task Rejected()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        using var source = new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials));
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0).ConfigureAwait(false);
            await client.Send(63, 7, [1, 0]).ConfigureAwait(false);
            await client.ExpectEof(closeSend: true).ConfigureAwait(false);
        });
        var result = await new CloudAcceptanceRunner(Profile(verification, formal), source, Quick).RunAsync(guard.Token).ConfigureAwait(false);
        await server.ConfigureAwait(false);
        Released(result, source, credentials);
        Check(result.Outcome == AcceptanceOutcome.LoginProtocolFailed && result.Login == LoginProtocolEvidence.NotObserved);
        Check(result.AttemptCount == 1 && result.Receive == ReceiveEvidence.NoBaseline);
        Check(!formal.HasPending && !verification.HasPending);
    }

    private static async Task InterruptedObservation(bool protocolError)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        using var source = new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials));
        var runner = new CloudAcceptanceRunner(Profile(verification, formal), source, Quick);
        var first = verification.Run(SyntheticClient.Verify);
        var second = formal.Run(async client =>
        {
            await client.EnterWorld().ConfigureAwait(false);
            await WaitFor(() => runner.Snapshot.Receive == ReceiveEvidence.BaselineObserved, guard.Token).ConfigureAwait(false);
            if (protocolError) await client.Send(63, 7, [0, 2]).ConfigureAwait(false);
            await client.ExpectEof(closeSend: !protocolError).ConfigureAwait(false);
        });
        var operation = runner.RunAsync(guard.Token);
        try
        {
            var result = await operation.ConfigureAwait(false);
            await Task.WhenAll(first, second).ConfigureAwait(false);
            Released(result, source, credentials);
            Check(result.Outcome == AcceptanceOutcome.ObservationInterrupted, result);
            Check(result.Login == LoginProtocolEvidence.Completed && result.Receive == ReceiveEvidence.BaselineObserved, result);
            Check(result.StopReason == AcceptanceStopReason.ConnectionEnded, result);
            Check(result.ConnectionFailure == (protocolError ? AccountConnectionFailure.LoginProtocolFailed : AccountConnectionFailure.RemoteEof), result);
        }
        finally
        {
            await guard.CancelAsync().ConfigureAwait(false);
            await operation.ConfigureAwait(false);
        }
    }

    private static async Task Incomplete()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        using var source = new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials));
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0).ConfigureAwait(false);
            await client.ExpectEof(closeSend: true).ConfigureAwait(false);
        });
        var result = await new CloudAcceptanceRunner(Profile(verification, formal), source, Quick).RunAsync(guard.Token).ConfigureAwait(false);
        await server.ConfigureAwait(false);
        Released(result, source, credentials);
        Check(result.Outcome == AcceptanceOutcome.IncompleteLogin);
        Check(result.Login == LoginProtocolEvidence.NotObserved && result.Receive == ReceiveEvidence.NoBaseline);
        Check(!formal.HasPending && !verification.HasPending);
    }

    private static async Task Interrupted(bool deadline)
    {
        using var guard = new CancellationTokenSource(Guard);
        using var caller = CancellationTokenSource.CreateLinkedTokenSource(guard.Token);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        using var source = new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials));
        var received = Signal();
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0).ConfigureAwait(false);
            received.TrySetResult();
            await client.ExpectEof().ConfigureAwait(false);
        });
        var runner = new CloudAcceptanceRunner(Profile(verification, formal), source,
            deadline ? Quick with { OverallTimeout = TimeSpan.FromMilliseconds(600), ObservationWindow = TimeSpan.FromMilliseconds(100) } : Quick);
        var operation = runner.RunAsync(caller.Token);
        try
        {
            if (!deadline)
            {
                await received.Task.WaitAsync(guard.Token).ConfigureAwait(false);
                await caller.CancelAsync().ConfigureAwait(false);
            }
            var result = await operation.ConfigureAwait(false);
            if (received.Task.IsCompleted) await server.ConfigureAwait(false);
            Released(result, source, credentials);
            Check(result.Outcome == (deadline ? AcceptanceOutcome.DeadlineExpired : AcceptanceOutcome.Cancelled));
            Check(result.StopReason == (deadline ? AcceptanceStopReason.OverallDeadline : AcceptanceStopReason.CallerCancellation));
            Check(result.Login == LoginProtocolEvidence.NotObserved && !formal.HasPending);
        }
        finally
        {
            await caller.CancelAsync().ConfigureAwait(false);
            await operation.ConfigureAwait(false);
        }
    }

    private static async Task NoncooperativeSource()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        var entered = Signal(); var release = Signal();
        using var source = new Source(async (_, _) =>
        {
            entered.TrySetResult();
            await release.Task.ConfigureAwait(false); // Deliberately ignores cancellation.
            return credentials;
        });
        var runner = new CloudAcceptanceRunner(Profile(verification, formal), source,
            Quick with { OverallTimeout = TimeSpan.FromMilliseconds(250), ObservationWindow = TimeSpan.FromMilliseconds(100) });
        var operation = runner.RunAsync(guard.Token);
        try
        {
            await entered.Task.WaitAsync(guard.Token).ConfigureAwait(false);
            await WaitFor(() => runner.Snapshot.StopReason == AcceptanceStopReason.OverallDeadline, guard.Token).ConfigureAwait(false);
            Check(runner.Snapshot.Phase == AcceptancePhase.Stopping && !operation.IsCompleted);
            Check(!verification.HasPending && !formal.HasPending && !credentials.IsDisposed);
            release.TrySetResult();
            var result = await operation.ConfigureAwait(false);
            Released(result, source, credentials);
            Check(result.Outcome == AcceptanceOutcome.DeadlineExpired && source.Calls == 1);
            Check(!verification.HasPending && !formal.HasPending);
        }
        finally
        {
            release.TrySetResult();
            await guard.CancelAsync().ConfigureAwait(false);
            await operation.ConfigureAwait(false);
        }
    }

    private static async Task PreCancelled()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var source = new Source((_, _) => throw new SyntheticTestFailure());
        var runner = new CloudAcceptanceRunner(Profile(verification, formal), source, Quick);
        var result = await runner.RunAsync(new CancellationToken(canceled: true)).ConfigureAwait(false);
        Released(result, source);
        Check(result.Outcome == AcceptanceOutcome.Cancelled && source.Calls == 0 && result.AttemptCount == 0);
        Check(!verification.HasPending && !formal.HasPending);
    }

    private static async Task SourceFailure(bool throws)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var source = new Source((_, _) => throws
            ? throw new InvalidOperationException("synthetic-private-marker-fake_secret")
            : ValueTask.FromResult<AccountLoginCredentials?>(null));
        var runner = new CloudAcceptanceRunner(Profile(verification, formal), source, Quick);
        var result = await runner.RunAsync(guard.Token).ConfigureAwait(false);
        Released(result, source);
        Check(result.Outcome == (throws ? AcceptanceOutcome.CredentialProviderFailed : AcceptanceOutcome.CredentialsUnavailable));
        foreach (var text in new[] { result.ToString(), JsonSerializer.Serialize(result), runner.Snapshot.ToString(), JsonSerializer.Serialize(runner.Snapshot) })
        {
            Check(!text.Contains("synthetic", StringComparison.OrdinalIgnoreCase));
            Check(!text.Contains("fake_secret", StringComparison.Ordinal));
            Check(!text.Contains("127.0.0.1", StringComparison.Ordinal));
            Check(!text.Contains("InvalidOperationException", StringComparison.Ordinal));
        }
        Check(!verification.HasPending && !formal.HasPending && source.Calls == 1);
    }

    private static async Task FreshAttempts()
    {
        using var guard = new CancellationTokenSource(Guard);
        var credentials = new List<AccountLoginCredentials>();
        using var source = new Source((_, _) =>
        {
            var next = Credentials(); credentials.Add(next);
            return ValueTask.FromResult<AccountLoginCredentials?>(next);
        });
        try
        {
            for (int i = 0; i < 2; i++)
            {
                await using var verification = new SyntheticPeer(guard.Token);
                await using var formal = new SyntheticPeer(guard.Token);
                var server = verification.Run(async client =>
                {
                    await client.Expect(63, 7, 0).ConfigureAwait(false);
                    await client.ExpectEof(closeSend: true).ConfigureAwait(false);
                });
                var runner = new CloudAcceptanceRunner(Profile(verification, formal), source, Quick);
                var operation = runner.RunAsync(guard.Token);
                var result = await operation.ConfigureAwait(false);
                await server.ConfigureAwait(false);
                Check(ReferenceEquals(operation, runner.RunAsync()));
                Check(result.AttemptCount == 1 && result.Cleanup == CleanupDisposition.Released);
                Check(source.Calls == i + 1 && !source.Disposed);
                Check(!formal.HasPending && !verification.HasPending);
            }
            Check(credentials.Count == 2 && !ReferenceEquals(credentials[0], credentials[1]));
            Check(credentials.All(value => value.IsDisposed));
        }
        finally { foreach (var value in credentials) value.Dispose(); }
    }

    // Never completes protocol login. The production resource factory is intentionally
    // not replaced: successful login here would initiate official HTTPS acquisition.
    private static async Task IntegratedBeforeLogin(int scenario)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        var entered = Signal(); var release = Signal();
        using var source = new Source(async (_, _) =>
        {
            if (scenario == 2) throw new InvalidOperationException("synthetic-private-marker-fake_secret");
            if (scenario == 5)
            {
                entered.TrySetResult();
                await release.Task.ConfigureAwait(false);
            }
            return scenario == 1 ? null : credentials;
        });
        string root = Path.Combine(Path.GetTempPath(), "acceptance-uncreated-" + Guid.NewGuid().ToString("N"));
        var runner = CloudAcceptanceRunner.CreateWithResources(Profile(verification, formal), source, root,
            scenario == 5 ? Quick with { OverallTimeout = TimeSpan.FromMilliseconds(250), ObservationWindow = TimeSpan.FromMilliseconds(100) } : Quick);
        Check(!Directory.Exists(root) && source.Calls == 0);
        Task? server = scenario is 3 or 4 ? verification.Run(async client =>
        {
            await client.Expect(63, 7, 0).ConfigureAwait(false);
            if (scenario == 3) await client.Send(63, 7, [1, 0]).ConfigureAwait(false);
            await client.ExpectEof(closeSend: true).ConfigureAwait(false);
        }) : null;
        var operation = runner.RunAsync(scenario == 0 ? new CancellationToken(true) : guard.Token);
        try
        {
            if (scenario == 5)
            {
                await entered.Task.WaitAsync(guard.Token).ConfigureAwait(false);
                await WaitFor(() => runner.Snapshot.StopReason == AcceptanceStopReason.OverallDeadline, guard.Token).ConfigureAwait(false);
                Check(!operation.IsCompleted && !verification.HasPending && !Directory.Exists(root));
                release.TrySetResult();
            }
            var result = await operation.ConfigureAwait(false);
            if (server is not null) await server.ConfigureAwait(false);
            Check(ReferenceEquals(operation, runner.RunAsync()));
            Released(result, source, scenario is 3 or 4 or 5 ? credentials : null);
            Check(result.Outcome == (scenario switch
            {
                0 => AcceptanceOutcome.Cancelled,
                1 => AcceptanceOutcome.CredentialsUnavailable,
                2 => AcceptanceOutcome.CredentialProviderFailed,
                3 => AcceptanceOutcome.LoginProtocolFailed,
                4 => AcceptanceOutcome.IncompleteLogin,
                _ => AcceptanceOutcome.DeadlineExpired
            }), result);
            Check(source.Calls == (scenario == 0 ? 0 : 1));
            Check(result.Login == LoginProtocolEvidence.NotObserved && result.Receive == ReceiveEvidence.NoBaseline);
            Check(result.Resources == new ResourceEvidence(ResourceObservation.NotObserved, 0, null, null, false, false));
            Check(runner.Snapshot.Resources == result.Resources && runner.Snapshot.Phase == AcceptancePhase.Completed);
            Check(!Directory.Exists(root) && !verification.HasPending && !formal.HasPending);
            foreach (var text in new[] { result.ToString(), JsonSerializer.Serialize(result), runner.Snapshot.ToString(), JsonSerializer.Serialize(runner.Snapshot) })
            {
                Check(!text.Contains(root, StringComparison.Ordinal));
                Check(!text.Contains("synthetic", StringComparison.OrdinalIgnoreCase));
                Check(!text.Contains("fake_secret", StringComparison.Ordinal));
                Check(!text.Contains("127.0.0.1", StringComparison.Ordinal));
                Check(!text.Contains("InvalidOperationException", StringComparison.Ordinal));
            }
        }
        finally
        {
            release.TrySetResult();
            await guard.CancelAsync().ConfigureAwait(false);
            await operation.ConfigureAwait(false);
        }
    }

    private static async Task IntegratedRootValidation()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var source = new Source((_, _) => throw new SyntheticTestFailure());
        foreach (var root in new[] { "", "relative-root" })
        {
            bool rejected = false;
            try { CloudAcceptanceRunner.CreateWithResources(Profile(verification, formal), source, root, Quick); }
            catch (ArgumentException) { rejected = true; }
            Check(rejected && source.Calls == 0 && !verification.HasPending && !formal.HasPending);
        }
    }

    private static Task Classification()
    {
        var progress = new AcceptanceProgress(AcceptancePhase.Completed, AcceptanceStopReason.CallerCancellation,
            LoginProtocolEvidence.Completed, ReceiveEvidence.RevisionAdvanced, 3, 4, 5);
        Check(CloudAcceptanceRunner.Classify(progress, AccountConnectionEndReason.CleanupFailed,
            AccountConnectionFailure.CleanupFailed, cleanupFailed: true, runnerFailed: false) == AcceptanceOutcome.CleanupFailed);
        Check(CloudAcceptanceRunner.Classify(progress, AccountConnectionEndReason.Stopped,
            null, cleanupFailed: false, runnerFailed: false) == AcceptanceOutcome.Cancelled);
        Check(CloudAcceptanceRunner.Classify(progress with { StopReason = AcceptanceStopReason.OverallDeadline },
            AccountConnectionEndReason.Stopped, null, cleanupFailed: false, runnerFailed: false) == AcceptanceOutcome.DeadlineExpired);
        foreach (var failure in new[] { AccountConnectionFailure.RemoteEof, AccountConnectionFailure.ReadFailed,
            AccountConnectionFailure.WriteFailed, AccountConnectionFailure.WriteUncertain,
            AccountConnectionFailure.InvalidProtocol, AccountConnectionFailure.LoginProtocolFailed,
            AccountConnectionFailure.ObservationFailed, AccountConnectionFailure.ReductionFailed,
            AccountConnectionFailure.EventHandlerFailed })
        {
            Check(CloudAcceptanceRunner.Classify(progress with { StopReason = AcceptanceStopReason.ConnectionEnded },
                AccountConnectionEndReason.ConnectionEnded, failure, cleanupFailed: false, runnerFailed: false) == AcceptanceOutcome.ObservationInterrupted);
            // Even a failure racing our observation timer must not become success.
            Check(CloudAcceptanceRunner.Classify(progress with { StopReason = AcceptanceStopReason.ObservationWindowElapsed },
                AccountConnectionEndReason.Stopped, failure, cleanupFailed: false, runnerFailed: false) == AcceptanceOutcome.ObservationInterrupted);
        }
        return Task.CompletedTask;
    }

    private static Task OptionBounds()
    {
        AcceptanceOptions[] invalid =
        [
            Quick with { OverallTimeout = Timeout.InfiniteTimeSpan },
            Quick with { OverallTimeout = TimeSpan.FromMinutes(6) },
            Quick with { ObservationWindow = TimeSpan.Zero },
            Quick with { ObservationWindow = TimeSpan.FromSeconds(6) },
            Quick with { PollInterval = TimeSpan.Zero },
            Quick with { PollInterval = TimeSpan.FromTicks(1) },
            Quick with { LoginTimeout = TimeSpan.FromMinutes(3) },
            Quick with { ReadTimeout = Timeout.InfiniteTimeSpan }
        ];
        foreach (var option in invalid)
        {
            bool rejected = false;
            try { option.Validate(); }
            catch (ArgumentOutOfRangeException) { rejected = true; }
            Check(rejected);
        }
        return Task.CompletedTask;
    }

    private enum Scenario
    {
        LateHeartbeat, LateHeartbeatReversedWorldOrder, CompletedSilent, EarlyPostLoginEof, PostLoginProtocolFailure, RejectedLogin,
        IncompleteLogin, OverallDeadline, CallerCancellation, LateCredentialAfterDeadline,
        PreCancelled, ProviderErrorRedaction, CredentialDeclined, FreshSingleAttempts,
        CleanupFailureClassification, OptionBounds,
        PreparedCompleted, PreparedDeclined, PreparedStoppedBeforeRun, PreparedDisposedBeforeRun,
        PreparedExpiredBeforeRun, PreparedProviderFailure, PreparedPreCancelled,
        PreparedLateInputStop, PreparedLateInputExpiry, PreparedStopBetweenLegs,
        PreparedExpiryBetweenLegs, PreparedReentrantStop, PreparedConcurrentRetirement,
        IntegratedPreCancelled, IntegratedCredentialDeclined, IntegratedProviderError,
        IntegratedRejectedLogin, IntegratedIncompleteLogin, IntegratedLateCredentials, IntegratedRootValidation
    }
}
