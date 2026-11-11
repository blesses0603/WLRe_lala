using System.Collections.Immutable;
using System.Net;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;

namespace Lala.Core.Sessions.Handshake;

internal enum ReconnectPhase { Created, AcquiringCredentials, Connecting, Receiving, Draining, Waiting, Ending, Ended }
internal enum ReconnectEnd { ConnectionEnded, AttemptsExhausted, CredentialsUnavailable, ProviderFailed,
    AdmissionBlocked, Superseded, Cancelled, Stopped, Disposed, Deadline, CleanupFailed, DelayFailed }
internal sealed record ReconnectLimits
{
    internal int MaximumAttempts { get; init; } = 3;
    internal TimeSpan InitialDelay { get; init; } = TimeSpan.FromSeconds(1);
    internal TimeSpan MaximumDelay { get; init; } = TimeSpan.FromSeconds(10);
    internal TimeSpan MaximumRecoveryTime { get; init; } = TimeSpan.FromMinutes(5);
    internal void Validate()
    {
        if (MaximumAttempts is < 1 or > 10 || InitialDelay < TimeSpan.FromMilliseconds(100) ||
            InitialDelay > TimeSpan.FromMinutes(1) || MaximumDelay < InitialDelay ||
            MaximumDelay > TimeSpan.FromMinutes(1) || MaximumRecoveryTime <= TimeSpan.Zero ||
            MaximumRecoveryTime > TimeSpan.FromMinutes(30)) throw new ArgumentOutOfRangeException(nameof(ReconnectLimits));
    }
}
internal sealed record ReconnectAttemptSummary(long Generation, Guid Attempt, ReceiveEnd End, HeldConnectionOutcome Outcome);
internal sealed record ReconnectView(Guid Controller, long Generation, int Attempts, ReconnectPhase Phase,
    ReconnectEnd? End, TimeSpan? NextDelay, ImmutableArray<ReconnectAttemptSummary> History)
{
    internal bool ResourceHeld => true;
    internal bool CanSendCommands => false;
}
internal sealed record ReconnectResult(ReconnectView View, bool ResourcesReleased);
internal sealed class ReconnectCleanupException() : IOException("Account reconnect cleanup failed.");

/// <summary>
/// Opt-in internal bounded reconnect owner, not a host adapter or resource-admission path.
/// Each attempt requests a transient credential provider anew; this class never caches
/// credential packets or replays a write. Retry requires a safe terminal classification,
/// successful cleanup and an atomic same-generation ownership check. Account replacement,
/// explicit hold, manual stop and uncertain writes cannot be undone by a scheduled retry.
/// A caller-owned credential factory can retain its own inputs; it must honor its token.
/// Noncooperative callbacks keep completion pending and prevent replacement admission.
/// </summary>
internal sealed class HeldAccountReconnect : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly AccountSession session;
    private readonly IPEndPoint verification, formal;
    private readonly int txXor, rxXor, roleIndex, readSize, bufferedChunks;
    private Func<int, CancellationToken, ValueTask<Func<HandshakeLeg, Packet>?>>? credentials;
    private Func<int, CancellationToken, ValueTask<IHandshakeLoginProvider?>>? ownedCredentials;
    private readonly Func<double> clock;
    private readonly Func<ServiceStateSnapshot, double, ServiceObservationInputs> observe;
    private readonly Func<TimeSpan, CancellationToken, Task> delay;
    private readonly HeldLoginLimits loginLimits;
    private readonly AccountLoginAdmission? loginAdmission;
    private readonly IAccountRoleSelector? roleSelector;
    private readonly ReconnectLimits limits;
    private readonly CancellationTokenSource stop = new();
    private ReconnectView view;
    private TaskCompletionSource<ReconnectView> viewChanged = NewViewSignal();
    private HeldAccountConnection? current;
    private Task<ReconnectResult>? completion;
    private Task? disposal, cancellation, retirementCleanup;
    private bool retired, runRequested;

    internal HeldAccountReconnect(AccountSession session, long generation,
        IPEndPoint verification, IPEndPoint formal, int txXor, int rxXor, int roleIndex,
        Func<int, CancellationToken, ValueTask<Func<HandshakeLeg, Packet>?>>? credentials,
        Func<double> clock, Func<ServiceStateSnapshot, double, ServiceObservationInputs> observe,
        HeldLoginLimits? loginLimits = null, ReconnectLimits? limits = null,
        int readSize = 4096, int bufferedChunks = 4,
        Func<TimeSpan, CancellationToken, Task>? delay = null,
        Func<int, CancellationToken, ValueTask<IHandshakeLoginProvider?>>? ownedCredentials = null,
        AccountLoginAdmission? loginAdmission = null, IAccountRoleSelector? roleSelector = null)
    {
        ArgumentNullException.ThrowIfNull(session);
        if ((credentials is null) == (ownedCredentials is null))
            throw new ArgumentException("Exactly one credential source is required.");
        ArgumentNullException.ThrowIfNull(clock); ArgumentNullException.ThrowIfNull(observe);
        if (generation < 1) throw new ArgumentOutOfRangeException(nameof(generation));
        if (roleIndex is not (1 or 2)) throw new ArgumentOutOfRangeException(nameof(roleIndex));
        if (readSize is < 1 or > 65536) throw new ArgumentOutOfRangeException(nameof(readSize));
        if (bufferedChunks is < 1 or > 256) throw new ArgumentOutOfRangeException(nameof(bufferedChunks));
        WireCodec.ValidateKey(txXor); WireCodec.ValidateKey(rxXor);
        this.loginAdmission = loginAdmission; this.roleSelector = roleSelector;
        this.loginLimits = loginLimits ?? new(); this.loginLimits.Validate();
        this.limits = limits ?? new(); this.limits.Validate();
        this.verification = CopyEndpoint(verification); this.formal = CopyEndpoint(formal);
        this.session = session; this.txXor = txXor; this.rxXor = rxXor; this.roleIndex = roleIndex;
        this.credentials = credentials; this.ownedCredentials = ownedCredentials; this.clock = clock; this.observe = observe;
        this.readSize = readSize; this.bufferedChunks = bufferedChunks;
        this.delay = delay ?? ((duration, token) => Task.Delay(duration, token));
        view = new(Guid.NewGuid(), generation, 0, ReconnectPhase.Created, null, null, []);
    }

    internal AccountLoginProgress? LoginProgress { get { lock(gate) return !retired && current is {} active ? AccountLoginProgress.From(active.Handshake) : null; } }
    internal ReconnectView Snapshot { get { lock (gate) return view; } }
    /// <summary>
    /// Observes assignment identity, including same-phase updates. Comparing and subscribing
    /// under the same gate prevents a missed transition between a snapshot read and this wait.
    /// Cancellation belongs only to this waiter; it cannot retire the owner or other waits.
    /// </summary>
    internal Task<ReconnectView> WaitForChangeAsync(ReconnectView expectedView,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(expectedView);
        lock (gate)
            return !ReferenceEquals(view, expectedView)
                ? Task.FromResult(view)
                : viewChanged.Task.WaitAsync(cancellationToken);
    }
    private static TaskCompletionSource<ReconnectView> NewViewSignal() =>
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private void SetViewLocked(ReconnectView next)
    {
        var previous = viewChanged;
        view = next;
        viewChanged = NewViewSignal();
        // Retain only one pending signal, and never invoke observer continuations inline.
        previous.SetResult(next);
    }
    internal ReceivePublication? Publication => ReadPublication().Publication;
    internal (ReconnectView View, ReceivePublication? Publication) ReadPublication()
    {
        // The view and receive attempt cannot be replaced between these reads.
        lock (gate) return (view, retired ? null : current?.Publication);
    }
    internal Task? PublicationChanged { get { lock (gate) return retired ? null : current?.PublicationChanged; } }
    internal Task<ServiceStateSnapshot> ApplyCommandAsync(Guid attempt, Func<ServiceStateSnapshot, ServiceStateSnapshot> transition, CancellationToken token)
    {
        lock (gate)
        {
            if (retired || view.Phase != ReconnectPhase.Receiving || current?.Attempt != attempt)
                throw new InvalidOperationException("No current account connection.");
            return current.ApplyCommandAsync(transition, token);
        }
    }
    internal IDisposable WatchReceipts(Guid attempt,Lala.Core.Gameplay.GameReceiptWatch watch)
    {
        lock(gate)
        {
            if(retired||current is null||current.Attempt!=attempt)throw new InvalidOperationException("Connection is no longer current.");
            return current.WatchReceipts(watch);
        }
    }
    internal bool IsBatchDrained(Guid attempt)
    {lock(gate)return !retired&&current?.Attempt==attempt&&current.BatchDrained;}
    internal Task SendGameAsync(Guid attempt, Func<Packet> prepare, CancellationToken token)
    {
        lock (gate)
        {
            if (retired || view.Phase != ReconnectPhase.Receiving || current?.Attempt != attempt)
                throw new InvalidOperationException("No current account connection.");
            return current.SendGameAsync(prepare, token);
        }
    }
    internal Task SendChatAsync(Guid attempt, Packet packet, Func<bool> isCurrent, CancellationToken token)
    {
        lock (gate)
        {
            if (retired || view.Phase != ReconnectPhase.Receiving || current?.Attempt != attempt)
                throw new InvalidOperationException("No current account connection.");
            return current.SendChatAsync(packet, isCurrent, token);
        }
    }
    internal Task<ReconnectResult> RunAsync(CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            if (completion is not null) return completion;
            runRequested = true;
            return completion = Task.Run(() => ExecuteAsync(cancellationToken));
        }
    }
    internal void Stop() => Retire(ReconnectEnd.Stopped);
    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            RetireLocked(ReconnectEnd.Disposed);
            completion ??= Task.Run(() => ExecuteAsync(CancellationToken.None));
            return new(disposal ??= VerifyCleanupAsync(completion));
        }
    }
    private static async Task VerifyCleanupAsync(Task<ReconnectResult> operation)
    {
        if (!(await operation.ConfigureAwait(false)).ResourcesReleased) throw new ReconnectCleanupException();
    }
    private void Retire(ReconnectEnd reason) { lock (gate) RetireLocked(reason); }
    private void RetireLocked(ReconnectEnd reason)
    {
        if (retired) return;
        retired = true;
        SetViewLocked(view with { Phase = ReconnectPhase.Ending, End = reason, NextDelay = null });
        // This revokes network admission synchronously, before cancellation callbacks run.
        if (current is not null) retirementCleanup = current.DisposeAsync().AsTask();
        StartCancellationLocked();
    }
    private Task StartCancellationLocked() => cancellation ??= Task.Run(async () =>
    {
        try { await stop.CancelAsync().ConfigureAwait(false); }
        catch (Exception) { /* Callback faults do not substitute for owned operation cleanup. */ }
    });

    private async Task<ReconnectResult> ExecuteAsync(CancellationToken token)
    {
        using var external = token.UnsafeRegister(_ => Retire(ReconnectEnd.Cancelled), null);
        using var deadline = new CancellationTokenSource();
        using var expired = deadline.Token.UnsafeRegister(_ => Retire(ReconnectEnd.Deadline), null);
        deadline.CancelAfter(limits.MaximumRecoveryTime);
        bool released = true;
        try
        {
            while (true)
            {
                int number;
                long generation;
                lock (gate)
                {
                    if (!runRequested || retired) break;
                    var account = session.Snapshot;
                    if (account.Generation != view.Generation || account.Phase != SessionPhase.Preparing)
                    { RetireLocked(ReconnectEnd.Superseded); break; }
                    number = checked(view.Attempts + 1); generation = view.Generation;
                    SetViewLocked(view with { Attempts = number, Phase = ReconnectPhase.AcquiringCredentials, NextDelay = null });
                }
                Func<HandshakeLeg, Packet>? provider = null;
                IHandshakeLoginProvider? ownedProvider = null;
                try
                {
                    if (ownedCredentials is not null)
                        ownedProvider = await ownedCredentials(number, stop.Token).ConfigureAwait(false);
                    else provider = await credentials!(number, stop.Token).ConfigureAwait(false);
                }
                catch (Exception) { Retire(ReconnectEnd.ProviderFailed); break; }
                HeldAccountConnection? owner = null;
                try
                {
                    lock (gate)
                    {
                        if (!retired)
                        {
                            if (provider is null && ownedProvider is null) RetireLocked(ReconnectEnd.CredentialsUnavailable);
                            else
                            {
                                owner = HeldAccountConnection.TryAttach(session, generation, verification, formal,
                                    txXor, rxXor, roleIndex, provider, clock, observe, loginLimits, readSize, bufferedChunks, ownedProvider, loginAdmission, roleSelector);
                                provider = null;
                                if (owner is null)
                                    RetireLocked(session.Snapshot.Generation == generation ? ReconnectEnd.AdmissionBlocked : ReconnectEnd.Superseded);
                                else
                                {
                                    ownedProvider = null; // Ownership moved to the connection, including failure cleanup.
                                    current = owner;
                                    SetViewLocked(view with { Phase = ReconnectPhase.Connecting });
                                }
                            }
                        }
                    }
                }
                finally { ownedProvider?.Dispose(); } // Includes a late source response after stop/replacement.
                if (owner is null) break;
                ReceiveResult result;
                HeldConnectionOutcome outcome;
                try
                {
                    var running = owner.RunAsync(stop.Token);
                    await Task.WhenAny(running, owner.Login).ConfigureAwait(false);
                    lock (gate)
                        if (!retired && owner.Login.IsCompletedSuccessfully && owner.Login.Result.Phase == HandshakePhase.ScriptedComplete)
                        {
                            // A recovery budget must never disconnect a healthy session.
                            deadline.CancelAfter(Timeout.InfiniteTimeSpan);
                            if (deadline.IsCancellationRequested) RetireLocked(ReconnectEnd.Deadline);
                            else SetViewLocked(view with { Phase = ReconnectPhase.Receiving });
                        }
                    await Task.WhenAny(running, owner.Retiring).ConfigureAwait(false);
                    lock (gate)
                        if (!retired) SetViewLocked(view with { Phase = ReconnectPhase.Draining });
                    result = await running.ConfigureAwait(false);
                    await owner.DisposeAsync().ConfigureAwait(false);
                    outcome = owner.GetOutcome(result);
                }
                catch (Exception)
                {
                    released = false; Retire(ReconnectEnd.CleanupFailed); break;
                }
                TimeSpan wait;
                lock (gate)
                {
                    current = null;
                    SetViewLocked(view with { History = view.History.Add(new(generation, owner.Attempt, result.End, outcome)) });
                    if (!result.ResourcesReleased) { released = false; RetireLocked(ReconnectEnd.CleanupFailed); break; }
                    if (retired) break;
                    if (!outcome.CanReconnect) { RetireLocked(ReconnectEnd.ConnectionEnded); break; }
                    if (number >= limits.MaximumAttempts) { RetireLocked(ReconnectEnd.AttemptsExhausted); break; }
                    wait = TimeSpan.FromTicks(Math.Min(limits.MaximumDelay.Ticks,
                        checked(limits.InitialDelay.Ticks * (1L << (number - 1)))));
                    if (outcome.LoginCompleted) deadline.CancelAfter(limits.MaximumRecoveryTime);
                    if (deadline.IsCancellationRequested) { RetireLocked(ReconnectEnd.Deadline); break; }
                    SetViewLocked(view with { Phase = ReconnectPhase.Waiting, NextDelay = wait });
                }
                try { await delay(wait, stop.Token).ConfigureAwait(false); }
                catch (Exception) { Retire(ReconnectEnd.DelayFailed); break; }
                lock (gate)
                {
                    if (retired) break;
                    var replacement = session.TryBeginReconnect(generation, owner.Attempt);
                    if (replacement is null) { RetireLocked(ReconnectEnd.Superseded); break; }
                    SetViewLocked(view with { Generation = replacement.Generation, Phase = ReconnectPhase.AcquiringCredentials, NextDelay = null });
                }
            }
        }
        catch (Exception) { Retire(ReconnectEnd.ProviderFailed); }
        finally
        {
            Task cancel;
            Task? cleanup;
            lock (gate)
            {
                if (!retired) RetireLocked(ReconnectEnd.ConnectionEnded);
                cancel = StartCancellationLocked(); cleanup = retirementCleanup;
            }
            await cancel.ConfigureAwait(false);
            if (cleanup is not null)
                try { await cleanup.ConfigureAwait(false); } catch (Exception) { released = false; }
            credentials = null; ownedCredentials = null;
            stop.Dispose();
        }
        lock (gate)
        {
            current = null;
            SetViewLocked(view with { Phase = ReconnectPhase.Ended, NextDelay = null,
                End = released ? view.End : ReconnectEnd.CleanupFailed });
            return new(view, released);
        }
    }

    private static IPEndPoint CopyEndpoint(IPEndPoint endpoint)
    {
        ArgumentNullException.ThrowIfNull(endpoint);
        if (endpoint.Port == 0) throw new ArgumentException("A concrete endpoint is required.", nameof(endpoint));
        var address = endpoint.Address;
        return new(address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6
            ? new IPAddress(address.GetAddressBytes(), address.ScopeId) : new IPAddress(address.GetAddressBytes()), endpoint.Port);
    }
}
