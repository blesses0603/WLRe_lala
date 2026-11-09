using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Expedition;
using Lala.Core.Resources;
using Lala.Core.Sessions.Handshake;
using Lala.Core.State;
using Lala.Core.World;

namespace Lala.Core.Sessions;

public sealed class AccountRuntimeCleanupException() : IOException("Account runtime cleanup did not complete successfully.");

public sealed record AccountResourceAttempt(long Generation, int AttemptNumber, AccountResourcePreparationResult Preparation);
public sealed record AccountRuntimeResult(AccountConnectionResult Connection,
    ImmutableArray<AccountResourceAttempt> ResourceHistory, bool ResourcesReleased);
public sealed record AccountRuntimeStatus(AccountConnectionStatus Connection, bool HasCurrentResources,
    ImmutableArray<AccountResourceAttempt> ResourceHistory)
{
    /// <summary>Connection, resource preparation, and owned cleanup have all finished.
    /// Connection.Ended alone does not imply resource history is final.</summary>
    public bool IsCompleted { get; init; }
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
}
/// <summary>Immutable point-in-time receive/catalog join, never authority to act.</summary>
public sealed record AccountRuntimePublication(AccountReceivePublication Receive, OfflineRuntimeCandidate? Catalogs)
{
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
    public override string ToString() => nameof(AccountRuntimePublication);
}

/// <summary>Stable observation token for this runtime's connection and receive/catalog
/// publication, including absence and aggregate completion. Historical and read-only.</summary>
public sealed record AccountRuntimePublicationSnapshot(AccountConnectionStatus Connection,
    AccountRuntimePublication? Publication, bool IsCompleted)
{
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
    public override string ToString() => nameof(AccountRuntimePublicationSnapshot);
}

/// <summary>
/// Owns one connection and resource lifetime. Starts resource preparation only after protocol
/// login; reconnect refreshes read-only instead of replaying a database write. Every attempt
/// stays held, including when both protocol login and resource preparation succeed.
/// Construction is inert; RunAsync may send credentials to the explicit TCP profile, acquire
/// official HTTPS resources and bootstrap the fixed local inventory. No command API exists.
/// </summary>
public sealed class AccountRuntime : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly AccountSession session;
    private readonly AccountConnectionRuntime connection;
    private readonly AccountLoginPreparation? preparedLogin;
    /// <summary>Present only for CreatePrepared. Hosts must obtain independent permission
    /// for both login recipients and resource operations before RunAsync.</summary>
    public AccountRuntimeDisclosure? Disclosure { get; }
    private readonly AccountResourceRuntime resources;
    private readonly CancellationTokenSource stop = new();
    private Task<AccountRuntimeResult>? running;
    private Task? disposal, cancellation;
    private bool retired, completed;
    private AccountRuntimeStatus? observedStatus;
    private TaskCompletionSource statusChanged = NewStatusSignal();
    private AccountRuntimePublicationSnapshot? observedPublication;
    private TaskCompletionSource publicationChanged = NewStatusSignal();
    private readonly Func<CancellationToken, Task>? beforePreparationAdmission;
    private SessionSnapshot? resourceAccount;
    private Guid? resourceAttempt;
    private ServiceObservationInputs? projected;
    private ImmutableArray<AccountResourceAttempt> history = [];

    /// <summary>Legacy raw-source route. It does not provide prepared admission or disclosure.</summary>
    public static AccountRuntime Create(AccountSession session, long generation, AccountConnectionProfile profile,
        IAccountCredentialSource source, string absoluteDataRoot, AccountConnectionOptions? options = null, IAccountRoleSelector? roleSelector = null)
    {
        ArgumentNullException.ThrowIfNull(session);
        // Validate connection arguments before constructing owned resources; both factories are inert.
        return new(session, generation, profile, source, absoluteDataRoot, options, null, null, roleSelector);
    }
    internal static AccountRuntime CreateForOfflineTests(AccountSession session, long generation,
        AccountConnectionProfile profile, IAccountCredentialSource source, AccountResourceRuntime resources,
        AccountConnectionOptions? options = null, Func<CancellationToken, Task>? beforePreparationAdmission = null)
        => new(session, generation, profile, source, null, options, resources, beforePreparationAdmission);

    private AccountRuntime(AccountSession session, long generation, AccountConnectionProfile profile,
        IAccountCredentialSource source, string? root, AccountConnectionOptions? options, AccountResourceRuntime? supplied, Func<CancellationToken, Task>? beforePreparationAdmission, IAccountRoleSelector? roleSelector = null)
    {
        this.session = session;
        this.beforePreparationAdmission = beforePreparationAdmission;
        connection = new(session, generation, profile, source, options, Observe, roleSelector);
        resources = supplied ?? AccountResourceRuntime.Create(session, root!);
    }
    /// <summary>Construct an inert, single-attempt account with prepared credential admission
    /// and the existing resource/receive lifetime. The host must independently authorize both
    /// parts of Disclosure before RunAsync. No credential source or connection is exported.</summary>
    public static AccountRuntime CreatePrepared(AccountSession session, long generation, Guid selectedIdentity,
        AccountConnectionProfile profile, IAccountLoginInput input, string absoluteDataRoot,
        AccountConnectionOptions? options = null, TimeSpan? validity = null, IAccountRoleSelector? roleSelector = null)
        => new(session, generation, selectedIdentity, profile, input, absoluteDataRoot, options, validity,
            roleSelector, TimeProvider.System, null);

    internal static AccountRuntime CreatePreparedForOfflineTests(AccountSession session, long generation,
        Guid selectedIdentity, AccountConnectionProfile profile, IAccountLoginInput input, string absoluteDataRoot,
        AccountResourceRuntime resources, AccountConnectionOptions? options = null, TimeSpan? validity = null,
        IAccountRoleSelector? roleSelector = null, TimeProvider? clock = null)
        => new(session, generation, selectedIdentity, profile, input, absoluteDataRoot, options, validity,
            roleSelector, clock ?? TimeProvider.System, resources);

    private AccountRuntime(AccountSession session, long generation, Guid selectedIdentity,
        AccountConnectionProfile profile, IAccountLoginInput input, string absoluteDataRoot,
        AccountConnectionOptions? options, TimeSpan? validity, IAccountRoleSelector? roleSelector,
        TimeProvider clock, AccountResourceRuntime? supplied)
    {
        // Validate/normalize paths before taking ownership of input or resources. All construction is inert.
        var resourceDisclosure = new AccountResourceDisclosure(absoluteDataRoot);
        this.session = session;
        preparedLogin = new(session, generation, selectedIdentity, profile, input, options, validity,
            clock, roleSelector, Observe);
        connection = preparedLogin.Connection;
        resources = supplied ?? AccountResourceRuntime.Create(session, resourceDisclosure.AbsoluteDataRoot);
        Disclosure = new(preparedLogin.Disclosure, resourceDisclosure);
    }
    /// <summary>Stable assignment identity until visible lifecycle, resource selection,
    /// history, or aggregate completion changes. Retained values are historical only.</summary>
    public AccountRuntimeStatus Snapshot
    {
        get { lock (gate) return RefreshStatusLocked(); }
    }
    private static TaskCompletionSource NewStatusSignal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private AccountRuntimeStatus RefreshStatusLocked()
    {
        var (currentConnection, receive) = connection.ReadPublication();
        bool currentResources = CurrentCatalogsLocked(currentConnection, receive, out var catalogs);
        if (observedStatus is null || !ReferenceEquals(observedStatus.Connection, currentConnection) ||
            observedStatus.HasCurrentResources != currentResources || observedStatus.ResourceHistory != history ||
            observedStatus.IsCompleted != completed)
        {
            var previous = statusChanged;
            observedStatus = new(currentConnection, currentResources, history) { IsCompleted = completed };
            statusChanged = NewStatusSignal();
            previous.SetResult();
        }
        RefreshPublicationLocked(currentConnection, receive, catalogs);
        return observedStatus;
    }
    private void RefreshPublicationLocked(AccountConnectionStatus currentConnection,
        AccountReceivePublication? receive, OfflineRuntimeCandidate? catalogs)
    {
        if (retired) receive = null;
        var value = observedPublication?.Publication;
        if (receive is null) value = null;
        else if (!ReferenceEquals(value?.Receive, receive) || !ReferenceEquals(value?.Catalogs, catalogs))
            value = new(receive, catalogs);
        if (observedPublication is null || !ReferenceEquals(observedPublication.Connection, currentConnection) ||
            !ReferenceEquals(observedPublication.Publication, value) || observedPublication.IsCompleted != completed)
        {
            var previous = publicationChanged;
            observedPublication = new(currentConnection, value, completed);
            publicationChanged = NewStatusSignal();
            previous.SetResult();
        }
    }
    /// <summary>Wait for a change from this runtime's exact Snapshot. Stale, cloned, or
    /// foreign snapshots return the current state immediately. Aggregate completion also
    /// returns immediately, even after disposal. Cancellation affects only this waiter and
    /// is checked before returning. Changes may coalesce; this is not a packet/event stream
    /// and grants no callbacks, resource authority, or permission to send commands.</summary>
    public async Task<AccountRuntimeStatus> WaitForChangeAsync(AccountRuntimeStatus expected,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(expected);
        cancellationToken.ThrowIfCancellationRequested();
        Task changed;
        lock (gate)
        {
            var current = RefreshStatusLocked();
            cancellationToken.ThrowIfCancellationRequested();
            if (!ReferenceEquals(current, expected) || completed) return current;
            changed = statusChanged.Task;
        }
        await changed.WaitAsync(cancellationToken).ConfigureAwait(false);
        var updated = Snapshot;
        cancellationToken.ThrowIfCancellationRequested();
        return updated;
    }
    private async Task ObserveChangesAsync(CancellationToken token)
    {
        try
        {
            while (true)
            {
                token.ThrowIfCancellationRequested();
                // Subscribe before pulling joined state, so changes during the pull cannot
                // be lost. One owned pump, with at most one wait per source, serves all hosts.
                var view = connection.Lifetime;
                var accountChanged = session.SnapshotChanged;
                var bindingChanged = resources.BindingChanged;
                var receiveChanged = connection.PublicationChanged;
                lock (gate) RefreshStatusLocked();
                using var pending = CancellationTokenSource.CreateLinkedTokenSource(token);
                var waits = new List<Task>(4)
                {
                    connection.WaitForLifetimeChangeAsync(view, pending.Token),
                    accountChanged.WaitAsync(pending.Token), bindingChanged.WaitAsync(pending.Token)
                };
                if (receiveChanged is not null) waits.Add(receiveChanged.WaitAsync(pending.Token));
                try { await Task.WhenAny(waits).ConfigureAwait(false); }
                finally
                {
                    // Cancel and observe losers each cycle; resource-only changes must not
                    // accumulate unobserved connection/account waits until retirement.
                    await pending.CancelAsync().ConfigureAwait(false);
                    try { await Task.WhenAll(waits).ConfigureAwait(false); }
                    catch (OperationCanceledException) when (pending.IsCancellationRequested) { }
                }
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
    }
    /// <summary>Current read-only receive/catalog pair. Stable identity until either
    /// component changes; null after stop or when no owned receive attempt is current.</summary>
    public AccountRuntimePublication? Publication => PublicationSnapshot.Publication;
    /// <summary>Non-null observation token, including intervals without a receive attempt.
    /// Stable identity until connection, receive/catalog selection, or completion changes.</summary>
    public AccountRuntimePublicationSnapshot PublicationSnapshot
    {
        get { lock (gate) { RefreshStatusLocked(); return observedPublication!; } }
    }
    /// <summary>Inspect one catalog task and 1–4 explicitly selected role slots. Capture the
    /// exact current publication once; all calculations occur after leaving the runtime gate.
    /// The result is historical, not a current-at-return promise or authority to reserve,
    /// restore, claim, dispatch, activate resources or send commands.</summary>
    public ExpeditionTaskAssessment InspectExpeditionTask(ushort taskId, ImmutableArray<byte> selectedRoleIndices)
    {
        var basis = PublicationSnapshot;
        return ExpeditionTaskInspection.Inspect(basis, taskId, selectedRoleIndices);
    }
    /// <summary>Inspect material requirements from one exact current publication.
    /// Calculation runs outside the runtime gate. Results are historical, never a
    /// current-at-return guarantee, reservation or command-wrapper gate.</summary>
    public CraftingMaterialAssessment InspectCraftingMaterials(ushort itemId, int batchCount)
    {
        var basis = PublicationSnapshot;
        return CraftingMaterialInspection.Inspect(basis, itemId, batchCount);
    }
    /// <summary>Wait for receive commits, receive lifecycle, catalog selection/revocation,
    /// connection changes, or aggregate completion. Pass this runtime's exact snapshot;
    /// stale, cloned, foreign, and completed snapshots return the current value immediately.
    /// Changes coalesce, not a lossless packet/event stream. Cancellation belongs only to
    /// this waiter and is checked before returning. No callbacks or authority are granted.</summary>
    public async Task<AccountRuntimePublicationSnapshot> WaitForPublicationChangeAsync(
        AccountRuntimePublicationSnapshot expected, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(expected);
        cancellationToken.ThrowIfCancellationRequested();
        Task changed;
        lock (gate)
        {
            RefreshStatusLocked();
            cancellationToken.ThrowIfCancellationRequested();
            if (!ReferenceEquals(observedPublication, expected) || completed) return observedPublication!;
            changed = publicationChanged.Task;
        }
        await changed.WaitAsync(cancellationToken).ConfigureAwait(false);
        var updated = PublicationSnapshot;
        cancellationToken.ThrowIfCancellationRequested();
        return updated;
    }
    private bool CurrentCatalogsLocked(out OfflineRuntimeCandidate? catalogs)
    {
        var (currentConnection, receive) = connection.ReadPublication();
        return CurrentCatalogsLocked(currentConnection, receive, out catalogs);
    }
    private bool CurrentCatalogsLocked(AccountConnectionStatus currentConnection,
        AccountReceivePublication? receive, out OfflineRuntimeCandidate? catalogs)
    {
        catalogs = null;
        if (retired || resourceAccount is null || !ReferenceEquals(resourceAccount, session.Snapshot) ||
            currentConnection.Phase != AccountConnectionPhase.ReceivingHeld ||
            receive is not { Phase: AccountReceivePhase.Running } || receive.Attempt != resourceAttempt) return false;
        bool current = resources.TryReadCatalogs(out catalogs) && ReferenceEquals(resourceAccount, session.Snapshot);
        if (!current) catalogs = null;
        return current;
    }
    private ServiceObservationInputs Observe(ServiceStateSnapshot basis, double now)
    {
        lock (gate)
            return CurrentCatalogsLocked(out _) && projected is not null
                ? projected with { ObservedAt = now, ResourceHeld = true }
                : new(now) { ReconcileNpcSkills = true, TrackUnsupportedCraftingSchedules = true };
    }
    /// <summary>Start the single owned lifetime. For CreatePrepared, the host must first
    /// independently authorize both Disclosure.Login and Disclosure.Resources. Repeated
    /// calls return the same task; only the first token owns cancellation. Completion
    /// includes late input/role callbacks and resource cleanup. Dispose-before-Run retires
    /// this lifetime without acquiring credentials or starting resource operations.</summary>
    public Task<AccountRuntimeResult> RunAsync(CancellationToken token = default)
    {
        lock (gate) return running ??= Task.Run(() => RunCoreAsync(token));
    }
    public void Stop()
    {
        lock (gate)
        {
            if (retired) return;
            retired = true; resourceAccount = null; resourceAttempt = null; projected = null;
            if (preparedLogin is not null) preparedLogin.Stop();
            else connection.Stop();
            resources.Invalidate();
            // Cancellation callbacks are never invoked synchronously under the lifetime gate.
            cancellation = stop.CancelAsync();
            RefreshStatusLocked();
        }
    }
    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            Stop();
            return new(disposal ??= DisposeCoreAsync(running ??= Task.Run(() => RunCoreAsync(CancellationToken.None))));
        }
    }
    private static async Task DisposeCoreAsync(Task<AccountRuntimeResult> completion)
    {
        if (!(await completion.ConfigureAwait(false)).ResourcesReleased) throw new AccountRuntimeCleanupException();
    }
    private async Task<AccountRuntimeResult> RunCoreAsync(CancellationToken token)
    {
        using var cancel = token.UnsafeRegister(_ => Stop(), null);
        Task<AccountConnectionResult> receiving = preparedLogin is not null
            ? preparedLogin.RunAsync(stop.Token) : connection.RunAsync(stop.Token);
        Task<AccountResourcePreparationResult>? preparation = null;
        CancellationTokenSource? preparationStop = null;
        long generation = 0; int attemptNumber = 0; Guid? attempt = null;
        SessionSnapshot? account = null;
        bool preparedOnce = false, cleaned = true;
        AccountConnectionResult? result = null;
        using var waiterStop = new CancellationTokenSource();
        using var observerStop = new CancellationTokenSource();
        var observing = ObserveChangesAsync(observerStop.Token);
        Task<ReconnectView>? changed = null;
        ReconnectView? waitingView = null;
        try
        {
            while (!receiving.IsCompleted)
            {
                var view = connection.Lifetime;
                var publication = connection.Publication;
                bool sameAttempt = view.Phase == ReconnectPhase.Receiving && publication is { Phase: AccountReceivePhase.Running } && publication.Attempt == attempt &&
                    ReferenceEquals(account, session.Snapshot);
                if (attempt is not null && !sameAttempt)
                {
                    var cancellation = preparationStop?.CancelAsync() ?? Task.CompletedTask;
                    RevokeResources();
                    if (preparation is not null)
                    {
                        await FinishPreparationAsync(preparation, generation, attemptNumber, account!, attempt.Value).ConfigureAwait(false);
                        preparation = null;
                    }
                    try { await cancellation.ConfigureAwait(false); } catch { cleaned = false; }
                    preparationStop?.Dispose(); preparationStop = null;
                    attempt = null;
                    continue; // Re-read the lifetime after draining possibly noncooperative resource work.
                }
                if (view.Phase == ReconnectPhase.Receiving && publication is { Phase: AccountReceivePhase.Running } && attempt is null)
                {
                    var candidateAccount = session.Snapshot;
                    lock (gate)
                    {
                        // Bracket the independently pulled account/receive values with exact
                        // lifetime identity. A mixed old/new pull must not mark a new attempt started.
                        if (!retired && candidateAccount.Generation == view.Generation &&
                            ReferenceEquals(candidateAccount, session.Snapshot) && ReferenceEquals(view, connection.Lifetime) &&
                            connection.Publication is { Phase: AccountReceivePhase.Running } currentReceive && currentReceive.Attempt == publication.Attempt)
                        {
                            account = candidateAccount; generation = view.Generation; attemptNumber = view.Attempts;
                            attempt = publication.Attempt;
                            bool refresh = preparedOnce;
                            long requestedGeneration = generation;
                            preparationStop = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
                            var preparationToken = preparationStop.Token;
                            var expectedAccount = account;
                            var expectedAttempt = attempt.Value;
                            // Stop/revoke uses this same aggregate gate. Carry the resource
                            // revision into delayed work so retirement cannot admit a new owner attempt.
                            var expectedResourceRevision = resources.Revision;
                            preparation = Task.Run(() => PrepareAsync(refresh, requestedGeneration,
                                expectedAccount, expectedAttempt, expectedResourceRevision, preparationToken));
                            preparedOnce = true;
                        }
                    }
                }
                if (!ReferenceEquals(view, waitingView))
                {
                    // A preparation completion can win while the lifetime is unchanged.
                    // Reuse that pending wait instead of retaining another cancellation registration.
                    waitingView = view;
                    changed = connection.WaitForLifetimeChangeAsync(view, waiterStop.Token);
                }
                if (preparation is null) await Task.WhenAny(receiving, changed!).ConfigureAwait(false);
                else if (await Task.WhenAny(receiving, changed!, preparation).ConfigureAwait(false) == preparation)
                {
                    await FinishPreparationAsync(preparation, generation, attemptNumber, account!, attempt!.Value).ConfigureAwait(false);
                    preparation = null;
                    preparationStop?.Dispose(); preparationStop = null;
                }
            }
            result = await receiving.ConfigureAwait(false);
        }
        finally
        {
            waiterStop.Cancel();
            if (changed is not null)
                try { await changed.ConfigureAwait(false); }
                catch (OperationCanceledException) when (waiterStop.IsCancellationRequested) { }
            Stop();
            var pendingCancellation = preparationStop?.CancelAsync() ?? Task.CompletedTask;
            if (preparation is not null)
                try { await FinishPreparationAsync(preparation, generation, attemptNumber, account!, attempt!.Value).ConfigureAwait(false); }
                catch { cleaned = false; }
            try { await pendingCancellation.ConfigureAwait(false); } catch { cleaned = false; }
            preparationStop?.Dispose();
            try
            {
                if (preparedLogin is not null) await preparedLogin.DisposeAsync().ConfigureAwait(false);
                else await connection.DisposeAsync().ConfigureAwait(false);
            }
            catch { cleaned = false; }
            try { await resources.DisposeAsync().ConfigureAwait(false); } catch { cleaned = false; }
            if (cancellation is not null)
                try { await cancellation.ConfigureAwait(false); } catch { cleaned = false; }
            await observerStop.CancelAsync().ConfigureAwait(false);
            await observing.ConfigureAwait(false);
            stop.Dispose();
            lock (gate) { completed = true; RefreshStatusLocked(); }
        }
        lock (gate) return new(result!, history, cleaned && result!.ResourcesReleased);
    }
    private async Task<AccountResourcePreparationResult> PrepareAsync(bool refresh, long generation,
        SessionSnapshot account, Guid attempt, long expectedResourceRevision, CancellationToken token)
    {
        // Internal test barrier is outside all gates and cannot grant production source trust.
        if (beforePreparationAdmission is not null) await beforePreparationAdmission(token).ConfigureAwait(false);
        if (token.IsCancellationRequested)
            return new(generation, AccountResourcePreparationStatus.Cancelled, AccountResourceStorageOutcome.NotAttempted, false, false);
        if (!ReferenceEquals(account, session.Snapshot) || connection.Snapshot.Phase != AccountConnectionPhase.ReceivingHeld ||
            connection.Publication is not { Phase: AccountReceivePhase.Running } receive || receive.Attempt != attempt)
            return new(generation, AccountResourcePreparationStatus.AccountChanged, AccountResourceStorageOutcome.NotAttempted, false, false);
        return refresh ? await resources.RefreshAsync(account, token, expectedResourceRevision).ConfigureAwait(false)
            : await resources.BootstrapAsync(account, token, expectedResourceRevision).ConfigureAwait(false);
    }
    private void RevokeResources()
    {
        lock (gate)
        {
            resourceAccount = null; resourceAttempt = null; projected = null;
            if (!retired) resources.Invalidate();
            RefreshStatusLocked();
        }
    }
    private async Task FinishPreparationAsync(Task<AccountResourcePreparationResult> work, long generation,
        int number, SessionSnapshot account, Guid attempt)
    {
        AccountResourcePreparationResult result;
        try { result = await work.ConfigureAwait(false); }
        catch { result = new(generation, AccountResourcePreparationStatus.Failed, AccountResourceStorageOutcome.Unknown, false, false); }
        lock (gate)
        {
            history = history.Add(new(generation, number, result));
            if (!retired && result.WasBound && ReferenceEquals(account, session.Snapshot) &&
                connection.Snapshot.Phase == AccountConnectionPhase.ReceivingHeld &&
                connection.Publication is { Phase: AccountReceivePhase.Running } receive && receive.Attempt == attempt && resources.TryReadCatalogs(out var catalogs))
            {
                resourceAccount = account; resourceAttempt = attempt;
                // Only decoded current tables feed read-only observations. Optional skill
                // mappings and item fits remain unknown unless reviewed rows survived resource readback.
                projected = new(0)
                {
                    WorldCatalog = new WorldSceneCatalog(catalogs!.Stages.Keys.ToImmutableHashSet()),
                    DeclaredMainCatalogMapIds = catalogs.OptionalInstances?.DeclaredMainMapIds ?? ImmutableHashSet<ushort>.Empty,
                    ItemStackRules = catalogs.Items.Where(p => p.Value.ReviewedDetails is not null)
                        .ToImmutableDictionary(p => p.Key, p => p.Value.ReviewedDetails!.Stackable),
                    CraftingSchedules = ProjectCraftingSchedules(catalogs.Recipes),
                    TrackUnsupportedCraftingSchedules = true,
                    KnowledgeCatalog = ProjectKnowledgeCatalog(catalogs.Items, catalogs.OptionalSkills),
                    NpcSkills = ProjectNpcSkills(catalogs.ReviewedNpcs),
                    ReconcileNpcSkills = true
                };
            }
            RefreshStatusLocked();
        }
    }

    // Only a current parsed Smith catalog selects the schedule layout. Use every recipe,
    // including distinct recipe IDs producing the same item; Products omits those rows.
    // Missing rows never imply legacy, and packet contents do not select a schema.
    internal static CraftingScheduleContext? ProjectCraftingSchedules(RuntimeRecipeCandidate? recipes)
        => recipes is null || recipes.Catalog.IsDefaultOrEmpty ? null
            : CraftingScheduleContext.FromRuntimeRows(recipes.Catalog.Select(row =>
                new CraftingRecipeIdentity(row.Recipe.RecipeId, row.Recipe.ItemId)));

    // NPC slot IDs come from the required table's independently reviewed layout.
    // Optional skill definitions and Lua constants are not required for observed slot identity.
    internal static ImmutableDictionary<uint, ImmutableArray<uint>>? ProjectNpcSkills(
        IReadOnlyDictionary<uint, CombatResourceNpc>? npcs)
    {
        if (npcs is null) return null;
        var skills = ImmutableDictionary.CreateBuilder<uint, ImmutableArray<uint>>();
        foreach (var (id, row) in npcs)
        {
            if (id == 0 || id > ushort.MaxValue || row is null || row.Skills.IsDefault ||
                row.Skills.Length != 5 || row.Skills.Any(skill => skill > ushort.MaxValue)) return null;
            skills.Add(id, row.Skills);
        }
        return skills.ToImmutable();
    }

    // The required ItemData readback is independent of optional SkillData availability.
    // Only pinned reviewed details carry fit semantics; legacy rows remain unresolved.
    internal static CombatKnowledgeCatalog? ProjectKnowledgeCatalog(
        IReadOnlyDictionary<ushort, ItemDataRow> items, IReadOnlyDictionary<ushort, SkillDataRow>? skills)
    {
        ArgumentNullException.ThrowIfNull(items);
        var skillCatalog = ProjectSkillKeys(skills);
        var fits = ImmutableDictionary.CreateBuilder<ushort, int>();
        foreach (var (id, row) in items)
        {
            if (id == 0 || row is null || id != row.ItemId)
            {
                // Malformed item identity cannot select a slot. Preserve independently
                // valid skill knowledge instead of guessing or retiring the receive loop.
                fits.Clear(); break;
            }
            if (row.ReviewedDetails is { } details) fits.Add(id, details.FitType);
        }
        if (skillCatalog is null && fits.Count == 0) return null;
        return new()
        {
            SkillKeys = skillCatalog?.SkillKeys ?? ImmutableDictionary<ushort, uint>.Empty,
            ItemFitTypes = fits.ToImmutable()
        };
    }

    internal static CombatKnowledgeCatalog? ProjectSkillKeys(IReadOnlyDictionary<ushort, SkillDataRow>? skills)
    {
        if (skills is null) return null;
        var keys = ImmutableDictionary.CreateBuilder<ushort, uint>();
        foreach (var (id, row) in skills)
        {
            // Match combat_catalog: zero is not a mapping; ambiguity must never pick
            // a skill arbitrarily. This projection grants no command authority.
            if (id != row.Id || (row.Key != 0 && !keys.TryAdd(row.Key, id))) return null;
        }
        return new() { SkillKeys = keys.ToImmutable() };
    }
}
