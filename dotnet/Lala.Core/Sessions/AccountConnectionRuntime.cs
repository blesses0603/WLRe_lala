using System.Diagnostics;
using System.Collections.Immutable;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;

namespace Lala.Core.Sessions;

/// <summary>
/// Public host boundary over the tested account-owned login/receive/reconnect flow.
/// Construction is inert. RunAsync initiates caller-selected raw TCP login; hosts must
/// obtain user authorization and supply their own credential source/profile. No credentials
/// are saved, no official endpoint or successful live validation is implied, and resources
/// remain Held even after protocol login. This class exposes no game-command send operation.
/// </summary>
public sealed class AccountConnectionRuntime : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly HeldAccountReconnect connection;
    private readonly AccountConnectionProfile profile;
    private IAccountCredentialSource? credentialSource;
    private Task<AccountConnectionResult>? running;
    private Task? disposal;

    public AccountConnectionRuntime(AccountSession session, long generation, AccountConnectionProfile profile,
        IAccountCredentialSource credentialSource, AccountConnectionOptions? options = null,
        Func<ServiceStateSnapshot, double, ServiceObservationInputs>? observationInputs = null)
    {
        ArgumentNullException.ThrowIfNull(session); ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(credentialSource);
        this.profile = profile; this.credentialSource = credentialSource;
        options ??= new();
        var login = new HeldLoginLimits
        {
            LoginTimeout = options.LoginTimeout,
            Tcp = new() { ConnectTimeout = options.ConnectTimeout, ReadTimeout = options.ReadTimeout, WriteTimeout = options.WriteTimeout }
        };
        var retry = new ReconnectLimits
        {
            MaximumAttempts = options.MaximumAttempts, InitialDelay = options.InitialRetryDelay,
            MaximumDelay = options.MaximumRetryDelay, MaximumRecoveryTime = options.MaximumRecoveryTime
        };
        connection = new(session, generation, profile.VerificationEndpoint, profile.FormalEndpoint,
            profile.TransmitXor, profile.ReceiveXor, profile.RoleIndex, null,
            () => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency,
            observationInputs ?? ((_, now) => new(now)), login, retry, ownedCredentials: AcquireAsync);
    }

    private ReconnectView? observedView;
    private AccountConnectionStatus? observedStatus;
    public AccountConnectionStatus Snapshot
    {
        get
        {
            lock (gate)
            {
                var view = connection.Snapshot;
                if (!ReferenceEquals(view, observedView))
                {
                    observedView = view;
                    observedStatus = Map(view);
                }
                return observedStatus!;
            }
        }
    }
    /// <summary>Wait for a change from this runtime's exact observed snapshot. Stale or
    /// foreign snapshots return the current state immediately; ended state returns
    /// immediately. Cancellation is checked before returning an observed change.
    /// No callbacks or authority are granted.</summary>
    public async Task<AccountConnectionStatus> WaitForChangeAsync(AccountConnectionStatus expected,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(expected);
        cancellationToken.ThrowIfCancellationRequested();
        ReconnectView view;
        lock (gate)
        {
            var current = Snapshot;
            cancellationToken.ThrowIfCancellationRequested();
            if (!ReferenceEquals(current, expected) || current.Phase == AccountConnectionPhase.Ended)
                return current;
            view = observedView!;
        }
        await connection.WaitForChangeAsync(view, cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        return Snapshot;
    }
    internal ReconnectView Lifetime => connection.Snapshot;
    internal Task<ReconnectView> WaitForLifetimeChangeAsync(ReconnectView expected, CancellationToken token)
        => connection.WaitForChangeAsync(expected, token);
    /// <summary>Current connection only. Returns null after stop, replacement, or between
    /// attempts. Custom observation inputs run on the receive writer, not a UI thread.</summary>
    public AccountReceivePublication? Publication
    {
        get
        {
            var value = connection.Publication;
            return value is null ? null : new(value.Attempt, value.Revision, value.Stage switch
            {
                ReceiveStage.Created => AccountReceivePhase.Created, ReceiveStage.Running => AccountReceivePhase.Running,
                ReceiveStage.Ending => AccountReceivePhase.Ending, _ => AccountReceivePhase.Ended
            }, value.Snapshot);
        }
    }
    /// <summary>One-shot lifetime; the first token owns cancellation. Repeated calls return
    /// the same task. Completion includes transport, receive writer and admitted callbacks.</summary>
    public Task<AccountConnectionResult> RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate) return running ??= RunCoreAsync(cancellationToken);
    }
    public void Stop() => connection.Stop();
    public ValueTask DisposeAsync()
    {
        lock (gate) return new(disposal ??= DisposeCoreAsync());
    }
    private async Task<AccountConnectionResult> RunCoreAsync(CancellationToken token)
    {
        try
        {
            var result = await connection.RunAsync(token).ConfigureAwait(false);
            return new(Map(result.View), result.ResourcesReleased);
        }
        finally { credentialSource = null; }
    }
    private async Task DisposeCoreAsync()
    {
        try { await connection.DisposeAsync().ConfigureAwait(false); }
        catch (ReconnectCleanupException) { throw new AccountConnectionCleanupException(); }
        finally { credentialSource = null; }
    }
    private async ValueTask<IHandshakeLoginProvider?> AcquireAsync(int number, CancellationToken token)
    {
        var source = credentialSource;
        if (source is null) return null;
        AccountLoginCredentials? value = null;
        try
        {
            value = await source.AcquireAsync(new(connection.Snapshot.Generation, number), token).ConfigureAwait(false);
            if (value is null) return null;
            token.ThrowIfCancellationRequested();
            return value.CreateProvider(profile.Platform, profile.Language);
        }
        catch { value?.Dispose(); throw; }
    }

    private static AccountConnectionStatus Map(ReconnectView view) => new(view.Controller, view.Generation, view.Attempts,
        view.Phase switch
        {
            ReconnectPhase.Created => AccountConnectionPhase.Created,
            ReconnectPhase.AcquiringCredentials => AccountConnectionPhase.AcquiringCredentials,
            ReconnectPhase.Connecting => AccountConnectionPhase.Connecting,
            ReconnectPhase.Receiving => AccountConnectionPhase.ReceivingHeld,
            ReconnectPhase.Draining => AccountConnectionPhase.Draining,
            ReconnectPhase.Waiting => AccountConnectionPhase.RetryWaiting,
            ReconnectPhase.Ending => AccountConnectionPhase.Stopping,
            _ => AccountConnectionPhase.Ended
        }, view.End switch
        {
            null => null,
            ReconnectEnd.ConnectionEnded => AccountConnectionEndReason.ConnectionEnded,
            ReconnectEnd.AttemptsExhausted => AccountConnectionEndReason.AttemptsExhausted,
            ReconnectEnd.CredentialsUnavailable => AccountConnectionEndReason.CredentialsUnavailable,
            ReconnectEnd.ProviderFailed => AccountConnectionEndReason.ProviderFailed,
            ReconnectEnd.AdmissionBlocked => AccountConnectionEndReason.AdmissionBlocked,
            ReconnectEnd.Superseded => AccountConnectionEndReason.Superseded,
            ReconnectEnd.Cancelled => AccountConnectionEndReason.Cancelled,
            ReconnectEnd.Stopped => AccountConnectionEndReason.Stopped,
            ReconnectEnd.Disposed => AccountConnectionEndReason.Disposed,
            ReconnectEnd.Deadline => AccountConnectionEndReason.RecoveryDeadline,
            ReconnectEnd.CleanupFailed => AccountConnectionEndReason.CleanupFailed,
            _ => AccountConnectionEndReason.DelayFailed
        }, view.NextDelay, view.History.Select(h => new AccountConnectionAttempt(h.Generation, h.Attempt,
            Map(h.Outcome.Failure), h.Outcome.LoginCompleted, h.Outcome.CanReconnect)).ToImmutableArray());

    private static AccountConnectionFailure Map(HeldConnectionFailure failure) => failure switch
    {
        HeldConnectionFailure.ConnectFailed => AccountConnectionFailure.ConnectFailed,
        HeldConnectionFailure.ConnectTimedOut => AccountConnectionFailure.ConnectTimedOut,
        HeldConnectionFailure.RemoteEof => AccountConnectionFailure.RemoteEof,
        HeldConnectionFailure.ReadFailed => AccountConnectionFailure.ReadFailed,
        HeldConnectionFailure.ReadTimedOut => AccountConnectionFailure.ReadTimedOut,
        HeldConnectionFailure.LoginProtocolFailed => AccountConnectionFailure.LoginProtocolFailed,
        HeldConnectionFailure.ProviderFailed => AccountConnectionFailure.ProviderFailed,
        HeldConnectionFailure.LoginDeadline => AccountConnectionFailure.LoginDeadline,
        HeldConnectionFailure.WriteFailed => AccountConnectionFailure.WriteFailed,
        HeldConnectionFailure.WriteUncertain => AccountConnectionFailure.WriteUncertain,
        HeldConnectionFailure.CancelledOrHeld => AccountConnectionFailure.CancelledOrHeld,
        HeldConnectionFailure.CleanupFailed => AccountConnectionFailure.CleanupFailed,
        HeldConnectionFailure.InvalidProtocol => AccountConnectionFailure.InvalidProtocol,
        HeldConnectionFailure.ObservationFailed => AccountConnectionFailure.ObservationFailed,
        HeldConnectionFailure.ReductionFailed => AccountConnectionFailure.ReductionFailed,
        HeldConnectionFailure.EventHandlerFailed => AccountConnectionFailure.EventHandlerFailed,
        _ => AccountConnectionFailure.IncompleteLoginOrUnknown
    };
}
