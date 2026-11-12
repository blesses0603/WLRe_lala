using System.Diagnostics;
using Lala.Core.Sessions;

namespace Lala.Cloud.Acceptance;

/// <summary>
/// Inert, one-shot public-API consumer for an explicitly authorized host. Every new runner
/// owns a fresh session and exactly one connection attempt. It never discovers endpoints,
/// sends gameplay commands or disposes the caller's credential source.
/// The host must supply its own secure credential adapter. Raw TCP/XOR is not encryption.
/// </summary>
public sealed class CloudAcceptanceRunner : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly AcceptanceOptions options;
    private AccountConnectionProfile? profile;
    private IAccountCredentialSource? source;
    private string? dataRoot;
    private Task<AcceptanceResult>? running;
    private Task? disposal;
    private AccountSession? preparedSession;
    private AccountLoginPreparation? preparation;
    private readonly CancellationTokenSource hostStop = new();
    private int stopClaimed;
    /// <summary>Exact prepared disclosure; null for legacy raw-source routes. Not proof of consent.</summary>
    public AccountLoginDisclosure? Disclosure { get; private init; }

    /// <summary>Inert opt-in. The host must independently authenticate permission for
    /// Disclosure before RunAsync, and bind the opaque selection to actual input.
    /// No reusable source, second profile, resource bootstrap, or approval assertion.</summary>
    public static CloudAcceptanceRunner CreatePrepared(AccountConnectionProfile profile,
        Guid selectedIdentity, IAccountLoginInput input, AcceptanceOptions? options = null,
        TimeSpan? validity = null) => new(profile, selectedIdentity, input, options, validity);

    private CloudAcceptanceRunner(AccountConnectionProfile profile, Guid selectedIdentity,
        IAccountLoginInput input, AcceptanceOptions? options, TimeSpan? validity)
    {
        this.options = options ?? new();
        this.options.Validate();
        preparedSession = new();
        var generation = preparedSession.Begin("acceptance", "explicit-profile").Generation;
        preparation = new(preparedSession, generation, selectedIdentity, profile, input,
            ConnectionOptions(), validity);
        Disclosure = preparation.Disclosure;
    }

    private AccountConnectionOptions ConnectionOptions() => new()
    {
        MaximumAttempts = 1, MaximumRecoveryTime = TimeSpan.FromMinutes(30),
        LoginTimeout = options.LoginTimeout, ConnectTimeout = options.ConnectTimeout,
        ReadTimeout = options.ReadTimeout, WriteTimeout = options.WriteTimeout
    };

    /// <summary>Revokes prepared admission even before Run. Input remains caller-owned.</summary>
    public void Stop()
    {
        preparation?.Stop();
        hostStop.Cancel();
    }

    public ValueTask DisposeAsync()
    {
        Stop();
        lock (gate) return new(disposal ??= Task.Run(async () =>
        {
            // Run after Stop performs no input acquisition and owns final cleanup.
            await RunAsync().ConfigureAwait(false);
        }));
    }

    private readonly TaskCompletionSource stopRequested = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private AcceptanceProgress progress = new(AcceptancePhase.Created, AcceptanceStopReason.None,
        LoginProtocolEvidence.NotObserved, ReceiveEvidence.NoBaseline, 0, null, null);

    /// <summary>Legacy raw-source route without preparation disclosure/binding guarantees.</summary>
    public CloudAcceptanceRunner(AccountConnectionProfile profile, IAccountCredentialSource source,
        AcceptanceOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(source);
        this.options = options ?? new();
        this.options.Validate();
        this.profile = profile;
        this.source = source;
    }

    /// <summary>Legacy raw-source opt-in to AccountRuntime, without preparation guarantees. After protocol login, RunAsync may
    /// download official HTTPS resources and create/update the fixed local resource inventory.
    /// The caller must authorize both operations and the connection/account separately.
    /// Construction is inert and is not authorization. No resource success is implied by login.</summary>
    public static CloudAcceptanceRunner CreateWithResources(AccountConnectionProfile profile,
        IAccountCredentialSource source, string absoluteDataRoot, AcceptanceOptions? options = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absoluteDataRoot);
        if (!Path.IsPathFullyQualified(absoluteDataRoot))
            throw new ArgumentException("An absolute data root is required", nameof(absoluteDataRoot));
        var root = Path.GetFullPath(absoluteDataRoot);
        var runner = new CloudAcceptanceRunner(profile, source, options) { dataRoot = root };
        runner.progress = runner.progress with { Resources = new(ResourceObservation.NotObserved, 0, null, null, false, false) };
        return runner;
    }

    public AcceptanceProgress Snapshot { get { lock (gate) return progress; } }

    /// <summary>Repeated calls return the same task; only the first token owns cancellation.
    /// Stop requests revoke further admission promptly, but return waits for RunAsync and
    /// DisposeAsync, including admitted noncooperative callbacks. No cleanup is abandoned.</summary>
    public Task<AcceptanceResult> RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate) return running ??= Task.Run(() => ExecuteAsync(cancellationToken));
    }

    private async Task<AcceptanceResult> ExecuteAsync(CancellationToken cancellationToken)
    {
        var session = preparedSession ?? new AccountSession();
        var generation = preparedSession is null
            ? session.Begin("acceptance", "explicit-profile").Generation : Disclosure!.Generation;
        IAcceptanceRuntime runtime = preparation is not null
            ? new PreparedAcceptanceRuntime(preparation)
            : dataRoot is null
                ? new ConnectionAcceptanceRuntime(new(session, generation, profile!, source!, ConnectionOptions()))
                : new IntegratedAcceptanceRuntime(AccountRuntime.Create(session, generation, profile!, source!, dataRoot, ConnectionOptions()));
        lock (gate) progress = progress with { Phase = AcceptancePhase.WaitingForLogin };

        using var deadline = new CancellationTokenSource();
        using var deadlineRegistration = deadline.Token.Register(() => RequestStop(runtime, AcceptanceStopReason.OverallDeadline));
        using var callerRegistration = cancellationToken.Register(() => RequestStop(runtime, AcceptanceStopReason.CallerCancellation));
        using var hostRegistration = hostStop.Token.Register(() => RequestStop(runtime, AcceptanceStopReason.CallerCancellation));
        deadline.CancelAfter(options.OverallTimeout);
        Task<AccountConnectionResult>? operation = null;
        AccountConnectionResult? connectionResult = null;
        bool runnerFailed = false, cleanupFailed = false;
        Guid? baselineAttempt = null;
        long? observationStarted = null;
        try
        {
            operation = runtime.RunAsync();
            while (!operation.IsCompleted && !stopRequested.Task.IsCompleted)
            {
                var status = runtime.Snapshot;
                var publication = runtime.Publication;
                lock (gate)
                {
                    if (progress.StopReason == AcceptanceStopReason.None)
                    {
                        progress = progress with { PollCount = checked(progress.PollCount + 1),
                            Resources = runtime.ObserveResources(progress.Resources) };
                        if (status.Phase == AccountConnectionPhase.ReceivingHeld)
                        {
                            progress = progress with { Login = LoginProtocolEvidence.Completed };
                            // ReceivingHeld is published by the pre-commit login handler.
                            // Require both final handshake facts to be committed before taking
                            // the baseline, so its own final commit is not receive progress.
                            if (publication is { Phase: AccountReceivePhase.Running } &&
                                publication.State.Player is not null && publication.State.Local.Session.InitialDataComplete)
                            {
                                if (baselineAttempt is null)
                                {
                                    baselineAttempt = publication.Attempt;
                                    observationStarted = Stopwatch.GetTimestamp();
                                    progress = progress with
                                    {
                                        Phase = AcceptancePhase.ObservingHeldReceive,
                                        Receive = ReceiveEvidence.BaselineObserved,
                                        BaselineRevision = publication.Revision,
                                        LatestRevision = publication.Revision
                                    };
                                }
                                else if (publication.Attempt == baselineAttempt &&
                                    progress.LatestRevision is { } latest && publication.Revision > latest)
                                {
                                    progress = progress with
                                    {
                                        Receive = ReceiveEvidence.RevisionAdvanced,
                                        LatestRevision = publication.Revision
                                    };
                                }
                            }
                        }
                    }
                }
                if (observationStarted is { } started && Stopwatch.GetElapsedTime(started) >= options.ObservationWindow)
                    RequestStop(runtime, AcceptanceStopReason.ObservationWindowElapsed);
                if (!stopRequested.Task.IsCompleted && !operation.IsCompleted)
                {
                    using var tickStop = new CancellationTokenSource();
                    var tick = Task.Delay(options.PollInterval, tickStop.Token);
                    await Task.WhenAny(operation, stopRequested.Task, tick).ConfigureAwait(false);
                    await tickStop.CancelAsync().ConfigureAwait(false);
                    try { await tick.ConfigureAwait(false); }
                    catch (OperationCanceledException) when (tickStop.IsCancellationRequested) { }
                }
            }
            if (operation.IsCompleted) RequestStop(runtime, AcceptanceStopReason.ConnectionEnded);
        }
        catch (Exception)
        {
            // Exception objects/messages can contain source data. Never retain or print them.
            runnerFailed = true;
            RequestStop(runtime, AcceptanceStopReason.RunnerFailure);
        }
        finally
        {
            // Neither await has a timeout: timing limits request stop, never detach work.
            runtime.Stop();
            if (operation is not null)
                try { connectionResult = await operation.ConfigureAwait(false); }
                catch (Exception) { runnerFailed = true; }
            try { await runtime.DisposeAsync().ConfigureAwait(false); }
            catch (Exception) { cleanupFailed = true; }
            // Stop callbacks cannot change the final evidence once completion is frozen.
            deadline.CancelAfter(Timeout.InfiniteTimeSpan);
            lock (gate)
            {
                profile = null;
                source = null;
                dataRoot = null;
            }
            session.Disconnect();
        }

        await stopRequested.Task.ConfigureAwait(false);
        var statusAtEnd = connectionResult?.Status ?? runtime.Snapshot;
        var failure = statusAtEnd.History.IsEmpty ? (AccountConnectionFailure?)null : statusAtEnd.History[^1].Failure;
        cleanupFailed |= !runtime.ResourcesReleased || connectionResult is { ResourcesReleased: false } ||
            statusAtEnd.EndReason == AccountConnectionEndReason.CleanupFailed;
        AcceptanceProgress final;
        lock (gate)
        {
            if (statusAtEnd.History.Any(attempt => attempt.LoginProtocolCompleted))
                progress = progress with { Login = LoginProtocolEvidence.Completed };
            progress = progress with { Phase = AcceptancePhase.Completed,
                Resources = runtime.ObserveResources(progress.Resources) };
            final = progress;
        }
        return new(Classify(final, statusAtEnd.EndReason, failure, cleanupFailed, runnerFailed),
            final.StopReason, final.Login, final.Receive,
            cleanupFailed ? CleanupDisposition.Failed : CleanupDisposition.Released,
            statusAtEnd.AttemptNumber, final.PollCount, final.BaselineRevision, final.LatestRevision,
            statusAtEnd.EndReason, failure) { Resources = final.Resources };
    }

    private void RequestStop(IAcceptanceRuntime runtime, AcceptanceStopReason reason)
    {
        // Stop may synchronously invoke host cancellation callbacks. Never hold gate.
        if (Interlocked.CompareExchange(ref stopClaimed, 1, 0) != 0) return;
        runtime.Stop();
        lock (gate)
        {
            if (progress.Phase != AcceptancePhase.Completed)
                progress = progress with { Phase = AcceptancePhase.Stopping, StopReason = reason };
            stopRequested.TrySetResult();
        }
    }

    internal static AcceptanceOutcome Classify(AcceptanceProgress progress,
        AccountConnectionEndReason? end, AccountConnectionFailure? failure, bool cleanupFailed, bool runnerFailed)
    {
        if (cleanupFailed || end == AccountConnectionEndReason.CleanupFailed || failure == AccountConnectionFailure.CleanupFailed)
            return AcceptanceOutcome.CleanupFailed;
        if (runnerFailed) return AcceptanceOutcome.RunnerFailed;
        if (progress.StopReason == AcceptanceStopReason.CallerCancellation) return AcceptanceOutcome.Cancelled;
        if (progress.StopReason == AcceptanceStopReason.OverallDeadline ||
            end == AccountConnectionEndReason.RecoveryDeadline || failure == AccountConnectionFailure.LoginDeadline)
            return AcceptanceOutcome.DeadlineExpired;
        if (end == AccountConnectionEndReason.CredentialsUnavailable) return AcceptanceOutcome.CredentialsUnavailable;
        if (end == AccountConnectionEndReason.ProviderFailed) return AcceptanceOutcome.CredentialProviderFailed;
        if (progress.Login == LoginProtocolEvidence.Completed)
        {
            // Login/read evidence survives a later error, but does not turn an incomplete
            // observation window or failed protocol/write/receive path into acceptance.
            if (progress.StopReason != AcceptanceStopReason.ObservationWindowElapsed ||
                end != AccountConnectionEndReason.Stopped ||
                failure is not (null or AccountConnectionFailure.CancelledOrHeld))
                return AcceptanceOutcome.ObservationInterrupted;
            return progress.Receive == ReceiveEvidence.RevisionAdvanced
                ? AcceptanceOutcome.ProtocolCompleteWithReceiveProgress
                : AcceptanceOutcome.ProtocolCompleteWithoutReceiveProgress;
        }
        return failure switch
        {
            AccountConnectionFailure.LoginProtocolFailed or AccountConnectionFailure.InvalidProtocol => AcceptanceOutcome.LoginProtocolFailed,
            AccountConnectionFailure.ConnectFailed or AccountConnectionFailure.ConnectTimedOut => AcceptanceOutcome.ConnectionFailed,
            _ => AcceptanceOutcome.IncompleteLogin
        };
    }
}
