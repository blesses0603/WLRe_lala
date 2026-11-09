using Lala.Core.Sessions.Handshake;
using Lala.Core.State;

namespace Lala.Core.Sessions;

/// <summary>Immutable disclosure for one host-selected login. Identity is an opaque host
/// selection marker, not proof of the credential's account or authenticated permission.</summary>
public sealed class AccountLoginDisclosure
{
    public Guid SelectedIdentity { get; }
    public long Generation { get; }
    public AccountConnectionProfile Profile { get; }
    public TimeSpan Validity { get; }
    public int AttemptNumber => 1;
    public AccountRoleSelectionMode RoleSelectionMode { get; }
    public int? FixedRoleIndex => RoleSelectionMode == AccountRoleSelectionMode.Fixed ? Profile.RoleIndex : null;
    public string Purpose => "One account login through verification and formal TCP recipients.";
    public string Risk => "Account and password are sent to both named recipients. Fixed XOR is reversible " +
        "obfuscation, not TLS or secure encryption; network observers may recover them. No automatic retry.";
    internal AccountLoginDisclosure(Guid identity, long generation, AccountConnectionProfile profile, TimeSpan validity,
        AccountRoleSelectionMode roleSelectionMode)
        => (SelectedIdentity, Generation, Profile, Validity, RoleSelectionMode) = (identity, generation, profile, validity, roleSelectionMode);
    public override string ToString() => "Account login disclosure (identity redacted)";
}

/// <summary>A host input boundary, not a permission provider. The host must independently
/// authenticate action-time permission for the exact disclosure before calling RunAsync,
/// bind its selected identity to the actual input, and clear its original input buffers.</summary>
public interface IAccountLoginInput
{
    /// <summary>Return fresh exclusively owned credentials or null. Ownership transfers on
    /// return. No secrets in exceptions/logs. Honor cancellation. A noncooperative callback
    /// keeps preparation completion/disposal pending until its late result is cleared.</summary>
    ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken cancellationToken);
}

/// <summary>Inert, single-attempt composition of disclosure, host input and the exact runtime
/// profile/session. It does not collect input, authenticate consent, or secure raw TCP.
/// Retire this preparation on any host selection/profile change; replacements require fresh
/// disclosure and host permission. No source/runtime is exported for reuse with another profile.</summary>
public sealed class AccountLoginPreparation : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly AccountSession session;
    private readonly AccountLoginAdmission admission;
    private readonly AccountConnectionRuntime runtime;
    private IAccountLoginInput? input;
    private Task<AccountConnectionResult>? running;
    private Task? disposal;
    private readonly TimeProvider clock;
    internal AccountConnectionRuntime Connection => runtime;
    public AccountLoginDisclosure Disclosure { get; }
    public AccountConnectionStatus Snapshot => runtime.Snapshot;
    public AccountReceivePublication? Publication => runtime.Publication;

    public AccountLoginPreparation(AccountSession session, long generation, Guid selectedIdentity,
        AccountConnectionProfile profile, IAccountLoginInput input,
        AccountConnectionOptions? options = null, TimeSpan? validity = null, IAccountRoleSelector? roleSelector = null, IAccountLoginSendConfirmation? sendConfirmation = null)
        : this(session, generation, selectedIdentity, profile, input, options, validity, TimeProvider.System, roleSelector, sendConfirmation: sendConfirmation) { }

    internal AccountLoginPreparation(AccountSession session, long generation, Guid selectedIdentity,
        AccountConnectionProfile profile, IAccountLoginInput input, AccountConnectionOptions? options,
        TimeSpan? validity, TimeProvider clock, IAccountRoleSelector? roleSelector = null,
        Func<ServiceStateSnapshot, double, ServiceObservationInputs>? observationInputs = null, IAccountLoginSendConfirmation? sendConfirmation = null)
    {
        ArgumentNullException.ThrowIfNull(session); ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(input); ArgumentNullException.ThrowIfNull(clock);
        if (selectedIdentity == Guid.Empty) throw new ArgumentException("A selected identity is required.", nameof(selectedIdentity));
        var duration = validity ?? TimeSpan.FromMinutes(1);
        if (duration <= TimeSpan.Zero || duration > TimeSpan.FromMinutes(1)) throw new ArgumentOutOfRangeException(nameof(validity));
        options ??= new();
        if (options.MaximumAttempts != 1) throw new ArgumentException("Preparation allows exactly one attempt.", nameof(options));
        var snapshot = session.Snapshot;
        if (snapshot.Generation != generation || snapshot.Phase != SessionPhase.Preparing)
            throw new InvalidOperationException("A current preparing session is required.");
        this.session = session; this.input = input; this.clock = clock;
        Disclosure = new(selectedIdentity, generation, profile, duration, roleSelector is null ? AccountRoleSelectionMode.Fixed : AccountRoleSelectionMode.Interactive);
        admission = new(session, snapshot, profile, duration, clock, sendConfirmation);
        runtime = new(session, generation, profile, new InputSource(this), options, observationInputs, admission, roleSelector);
    }

    /// <summary>Call only after the host independently obtains permission for Disclosure.
    /// Repeated calls return the same task, never reacquire. The first token owns cancellation.
    /// Lifetime starts at construction and bounds acquisition and both credential-write
    /// admissions; after formal admission it does not time out a healthy receive-only session.
    /// Completion includes late input cleanup; cancellation is not proof of cleanup.</summary>
    public Task<AccountConnectionResult> RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            if (running is not null) return running;
            admission.SetCancellation(cancellationToken);
            return running = Task.Run(() => RunCoreAsync(cancellationToken));
        }
    }
    public Task<AccountConnectionStatus> WaitForChangeAsync(AccountConnectionStatus expected, CancellationToken cancellationToken = default)
        => runtime.WaitForChangeAsync(expected, cancellationToken);
    public void Stop() { admission.Revoke(); runtime.Stop(); }
    public ValueTask DisposeAsync()
    {
        admission.Revoke();
        lock (gate) return new(disposal ??= DisposeCoreAsync());
    }
    private async Task DisposeCoreAsync()
    {
        try
        {
            await runtime.DisposeAsync().ConfigureAwait(false);
            Task<AccountConnectionResult>? run;
            lock (gate) run = running;
            if (run is not null) await run.ConfigureAwait(false);
        }
        finally { input = null; }
    }
    private async Task<AccountConnectionResult> RunCoreAsync(CancellationToken token)
    {
        using var monitorStop = new CancellationTokenSource();
        var monitor = Task.WhenAll(WatchSessionAsync(monitorStop.Token), WatchExpiryAsync(monitorStop.Token));
        try { return await runtime.RunAsync(token).ConfigureAwait(false); }
        finally
        {
            admission.Revoke();
            monitorStop.Cancel();
            await monitor.ConfigureAwait(false);
            input = null;
        }
    }
    private async Task WatchExpiryAsync(CancellationToken token)
    {
        try
        {
            // Timers can fire slightly early. Always recheck monotonic time and rearm.
            while (admission.UntilExpiry is { } remaining)
            {
                if (admission.Expire()) { runtime.Stop(); return; }
                await Task.Delay(remaining, clock, token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
    }
    private async Task WatchSessionAsync(CancellationToken token)
    {
        try
        {
            while (true)
            {
                var changed = session.SnapshotChanged;
                if (!admission.IsCurrent) { runtime.Stop(); return; }
                await changed.WaitAsync(token).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
    }
    private sealed class InputSource(AccountLoginPreparation owner) : IAccountCredentialSource
    {
        private int acquired;
        public async ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken token)
        {
            AccountLoginCredentials? owned = null;
            try
            {
                if (Interlocked.Exchange(ref acquired, 1) != 0 || request.Generation != owner.Disclosure.Generation || request.AttemptNumber != 1)
                    throw new InvalidOperationException("Login preparation is unavailable.");
                owner.admission.Check(token);
                var source = owner.input ?? throw new InvalidOperationException("Login input is unavailable.");
                // Never invoke host input under any admission/lifecycle lock.
                owned = await source.AcquireAsync(owner.Disclosure, token).ConfigureAwait(false);
                owner.admission.Check(token);
                var result = owned; owned = null;
                return result;
            }
            finally { owned?.Dispose(); owner.input = null; }
        }
    }
    public override string ToString() => "Account login preparation (identity redacted)";
}
