using Lala.Core.Sessions;

namespace Lala.Cloud.Acceptance;

internal static partial class SyntheticSelfTests
{
    private sealed class Input(Func<AccountLoginDisclosure, CancellationToken, ValueTask<AccountLoginCredentials?>> acquire)
        : IAccountLoginInput, IDisposable
    {
        internal int Calls;
        internal bool Disposed;
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token)
        {
            Interlocked.Increment(ref Calls);
            return acquire(disclosure, token);
        }
        public void Dispose() => Disposed = true;
        public override string ToString() => throw new SyntheticTestFailure();
    }

    private static async Task PreparedCompleted()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        CloudAcceptanceRunner? runner = null;
        using var input = new Input((disclosure, _) =>
        {
            Check(ReferenceEquals(disclosure, runner!.Disclosure));
            // Cross-thread reads expose lifecycle locks held across a synchronous host callback.
            Check(Task.Run(() => runner.Snapshot).Wait(TimeSpan.FromSeconds(2)));
            return ValueTask.FromResult<AccountLoginCredentials?>(credentials);
        });
        var identity = Guid.NewGuid();
        await using var owned = runner = CloudAcceptanceRunner.CreatePrepared(Profile(verification, formal), identity, input, Quick);
        Check(input.Calls == 0 && !verification.HasPending && !formal.HasPending);
        Check(runner.Disclosure is { Generation: 1, AttemptNumber: 1 } && runner.Disclosure.SelectedIdentity == identity);
        Check(runner.Disclosure!.Profile.VerificationEndpoint.Equals(verification.Endpoint));
        Check(runner.Disclosure!.Profile.FormalEndpoint.Equals(formal.Endpoint));
        var first = verification.Run(SyntheticClient.Verify);
        var second = formal.Run(async client =>
        {
            await client.EnterWorld();
            await WaitFor(() => runner.Snapshot.Receive == ReceiveEvidence.BaselineObserved, guard.Token);
            await client.Send(1, 23);
            await client.Expect(63, 5, payloadLength: 0);
            await client.ExpectEof();
        });
        var operation = runner.RunAsync(guard.Token);
        Check(ReferenceEquals(operation, runner.RunAsync(new CancellationToken(true))));
        var result = await operation.WaitAsync(guard.Token);
        await Task.WhenAll(first, second);
        Check(result.Outcome == AcceptanceOutcome.ProtocolCompleteWithReceiveProgress, result);
        Check(result.Resources == ResourceEvidence.Disabled && credentials.IsDisposed);
        Check(result.Cleanup == CleanupDisposition.Released && input.Calls == 1 && !input.Disposed);
        Check(ReferenceEquals(operation, runner.RunAsync()));
    }

    private static async Task PreparedUnused(int mode)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var input = new Input((_, _) => mode == 4
            ? throw new InvalidOperationException("private synthetic failure")
            : ValueTask.FromResult<AccountLoginCredentials?>(null));
        await using var runner = CloudAcceptanceRunner.CreatePrepared(Profile(verification, formal), Guid.NewGuid(), input, Quick,
            mode == 3 ? TimeSpan.FromMilliseconds(10) : null);
        if (mode == 1) runner.Stop();
        if (mode == 2) await runner.DisposeAsync();
        if (mode == 3) await Task.Delay(40, guard.Token);
        var result = await runner.RunAsync(mode == 5 ? new CancellationToken(true) : guard.Token).WaitAsync(guard.Token);
        Check(result.Cleanup == CleanupDisposition.Released && result.Resources == ResourceEvidence.Disabled);
        Check(!verification.HasPending && !formal.HasPending && !input.Disposed);
        Check(input.Calls == (mode is 0 or 4 ? 1 : 0));
        if (mode == 0) Check(result.Outcome == AcceptanceOutcome.CredentialsUnavailable, result);
        if (mode == 4) Check(result.Outcome == AcceptanceOutcome.CredentialProviderFailed, result);
        Check(!result.ToString().Contains("private synthetic"));
    }

    private static async Task PreparedLateInput(bool expire)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        var acquired = Signal(); var release = Signal(); var cancelled = Signal();
        CloudAcceptanceRunner? runner = null;
        using var input = new Input(async (_, token) =>
        {
            using var registration = token.Register(() =>
            {
                Check(Task.Run(() => runner!.Snapshot).Wait(TimeSpan.FromSeconds(2)));
                cancelled.TrySetResult();
            });
            acquired.TrySetResult();
            await release.Task;
            return credentials;
        });
        await using var owned = runner = CloudAcceptanceRunner.CreatePrepared(Profile(verification, formal), Guid.NewGuid(), input, Quick,
            expire ? TimeSpan.FromSeconds(3) : null);
        var operation = runner.RunAsync(guard.Token);
        try
        {
            await acquired.Task.WaitAsync(guard.Token);
            if (!expire) runner.Stop();
            await cancelled.Task.WaitAsync(guard.Token);
            // Preparation expiry must be the input cancellation source, not the
            // acceptance overall timeout (which publishes its own stop reason).
            if (expire) Check(runner.Snapshot.StopReason == AcceptanceStopReason.None);
            var disposal = runner.DisposeAsync().AsTask();
            Check(!operation.IsCompleted && !disposal.IsCompleted && !credentials.IsDisposed);
            release.TrySetResult();
            var result = await operation.WaitAsync(guard.Token);
            await disposal.WaitAsync(guard.Token);
            Check(credentials.IsDisposed && result.Cleanup == CleanupDisposition.Released);
            Check(input.Calls == 1 && !input.Disposed && !verification.HasPending && !formal.HasPending);
        }
        finally { release.TrySetResult(); }
    }

    private static async Task PreparedStopBetweenLegs(bool expire)
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        using var input = new Input((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials));
        await using var runner = CloudAcceptanceRunner.CreatePrepared(Profile(verification, formal), Guid.NewGuid(), input, Quick,
            expire ? TimeSpan.FromSeconds(3) : null);
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0);
            // Host context replacement must retire this runner, not mutate its pinned profile.
            if (!expire) runner.Stop();
            await client.ExpectEof(closeSend: !expire);
        });
        var result = await runner.RunAsync(guard.Token).WaitAsync(guard.Token);
        await server;
        Check(result.Login == LoginProtocolEvidence.NotObserved && !formal.HasPending);
        if (expire)
        {
            Check(result.StopReason == AcceptanceStopReason.ConnectionEnded, result);
            Check(result.ConnectionFailure != AccountConnectionFailure.LoginDeadline, result);
        }
        Check(credentials.IsDisposed && input.Calls == 1 && result.Cleanup == CleanupDisposition.Released);
    }
    private static async Task PreparedReentrantStop()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        using var credentials = Credentials();
        CloudAcceptanceRunner? runner = null;
        using var input = new Input((_, _) =>
        {
            Check(Task.Run(() => runner!.Stop()).Wait(TimeSpan.FromSeconds(2)));
            return ValueTask.FromResult<AccountLoginCredentials?>(credentials);
        });
        await using var owned = runner = CloudAcceptanceRunner.CreatePrepared(Profile(verification, formal), Guid.NewGuid(), input, Quick);
        var operation = runner.RunAsync(guard.Token);
        var result = await operation.WaitAsync(guard.Token);
        Check(result.Cleanup == CleanupDisposition.Released && credentials.IsDisposed);
        Check(input.Calls == 1 && !verification.HasPending && !formal.HasPending);
    }

    private static async Task PreparedConcurrentRetirement()
    {
        using var guard = new CancellationTokenSource(Guard);
        await using var verification = new SyntheticPeer(guard.Token);
        await using var formal = new SyntheticPeer(guard.Token);
        for (int i = 0; i < 20; i++)
        {
            using var input = new Input((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(null));
            await using var runner = CloudAcceptanceRunner.CreatePrepared(Profile(verification, formal), Guid.NewGuid(), input, Quick);
            var go = Signal();
            var run = Task.Run(async () => { await go.Task; return await runner.RunAsync(guard.Token); });
            var dispose = Task.Run(async () => { await go.Task; await runner.DisposeAsync(); });
            var stop = Task.Run(async () => { await go.Task; runner.Stop(); });
            go.SetResult();
            await Task.WhenAll(run, dispose, stop).WaitAsync(guard.Token);
            Check(ReferenceEquals(runner.RunAsync(), runner.RunAsync()));
            Check((await run).Cleanup == CleanupDisposition.Released && input.Calls <= 1 && !input.Disposed);
            Check(!verification.HasPending && !formal.HasPending);
        }
    }

}
