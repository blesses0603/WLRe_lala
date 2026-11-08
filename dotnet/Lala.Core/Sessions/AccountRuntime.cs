using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
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
    private readonly AccountResourceRuntime resources;
    private readonly CancellationTokenSource stop = new();
    private Task<AccountRuntimeResult>? running;
    private Task? disposal, cancellation;
    private bool retired;
    private readonly Func<CancellationToken, Task>? beforePreparationAdmission;
    private SessionSnapshot? resourceAccount;
    private Guid? resourceAttempt;
    private ServiceObservationInputs? projected;
    private ImmutableArray<AccountResourceAttempt> history = [];

    public static AccountRuntime Create(AccountSession session, long generation, AccountConnectionProfile profile,
        IAccountCredentialSource source, string absoluteDataRoot, AccountConnectionOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(session);
        // Validate connection arguments before constructing owned resources; both factories are inert.
        return new(session, generation, profile, source, absoluteDataRoot, options, null, null);
    }
    internal static AccountRuntime CreateForOfflineTests(AccountSession session, long generation,
        AccountConnectionProfile profile, IAccountCredentialSource source, AccountResourceRuntime resources,
        AccountConnectionOptions? options = null, Func<CancellationToken, Task>? beforePreparationAdmission = null)
        => new(session, generation, profile, source, null, options, resources, beforePreparationAdmission);

    private AccountRuntime(AccountSession session, long generation, AccountConnectionProfile profile,
        IAccountCredentialSource source, string? root, AccountConnectionOptions? options, AccountResourceRuntime? supplied, Func<CancellationToken, Task>? beforePreparationAdmission)
    {
        this.session = session;
        this.beforePreparationAdmission = beforePreparationAdmission;
        connection = new(session, generation, profile, source, options, Observe);
        resources = supplied ?? AccountResourceRuntime.Create(session, root!);
    }
    public AccountRuntimeStatus Snapshot
    {
        get { lock (gate) return new(connection.Snapshot, CurrentCatalogsLocked(out _), history); }
    }
    public AccountRuntimePublication? Publication
    {
        get
        {
            lock (gate)
            {
                if (retired) return null;
                var value = connection.Publication;
                if (value is null) return null;
                CurrentCatalogsLocked(out var catalogs);
                // A reconnect can race the first pull. Never join catalogs to another attempt.
                if (catalogs is not null && resourceAttempt != value.Attempt) catalogs = null;
                return new(value, catalogs);
            }
        }
    }
    private bool CurrentCatalogsLocked(out OfflineRuntimeCandidate? catalogs)
    {
        catalogs = null;
        if (retired || resourceAccount is null || !ReferenceEquals(resourceAccount, session.Snapshot) ||
            connection.Snapshot.Phase != AccountConnectionPhase.ReceivingHeld ||
            connection.Publication is not { Phase: AccountReceivePhase.Running } receive || receive.Attempt != resourceAttempt) return false;
        bool current = resources.TryReadCatalogs(out catalogs) && ReferenceEquals(resourceAccount, session.Snapshot);
        if (!current) catalogs = null;
        return current;
    }
    private ServiceObservationInputs Observe(ServiceStateSnapshot basis, double now)
    {
        lock (gate)
            return CurrentCatalogsLocked(out _) && projected is not null
                ? projected with { ObservedAt = now, ResourceHeld = true }
                : new(now) { ReconcileNpcSkills = true };
    }
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
            connection.Stop();
            resources.Invalidate();
            // Cancellation callbacks are never invoked synchronously under the lifetime gate.
            cancellation = stop.CancelAsync();
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
        Task<AccountConnectionResult> receiving = connection.RunAsync(stop.Token);
        Task<AccountResourcePreparationResult>? preparation = null;
        CancellationTokenSource? preparationStop = null;
        long generation = 0; int attemptNumber = 0; Guid? attempt = null;
        SessionSnapshot? account = null;
        bool preparedOnce = false, cleaned = true;
        AccountConnectionResult? result = null;
        using var waiterStop = new CancellationTokenSource();
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
                            preparation = Task.Run(() => PrepareAsync(refresh, requestedGeneration,
                                expectedAccount, expectedAttempt, preparationToken));
                            preparedOnce = true;
                        }
                    }
                }
                var changed = connection.WaitForLifetimeChangeAsync(view, waiterStop.Token);
                if (preparation is null) await Task.WhenAny(receiving, changed).ConfigureAwait(false);
                else if (await Task.WhenAny(receiving, changed, preparation).ConfigureAwait(false) == preparation)
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
            Stop();
            var pendingCancellation = preparationStop?.CancelAsync() ?? Task.CompletedTask;
            if (preparation is not null)
                try { await FinishPreparationAsync(preparation, generation, attemptNumber, account!, attempt!.Value).ConfigureAwait(false); }
                catch { cleaned = false; }
            try { await pendingCancellation.ConfigureAwait(false); } catch { cleaned = false; }
            preparationStop?.Dispose();
            try { await connection.DisposeAsync().ConfigureAwait(false); } catch { cleaned = false; }
            try { await resources.DisposeAsync().ConfigureAwait(false); } catch { cleaned = false; }
            if (cancellation is not null)
                try { await cancellation.ConfigureAwait(false); } catch { cleaned = false; }
            stop.Dispose();
        }
        lock (gate) return new(result!, history, cleaned && result!.ResourcesReleased);
    }
    private async Task<AccountResourcePreparationResult> PrepareAsync(bool refresh, long generation,
        SessionSnapshot account, Guid attempt, CancellationToken token)
    {
        // Internal test barrier is outside all gates and cannot grant production source trust.
        if (beforePreparationAdmission is not null) await beforePreparationAdmission(token).ConfigureAwait(false);
        if (token.IsCancellationRequested)
            return new(generation, AccountResourcePreparationStatus.Cancelled, AccountResourceStorageOutcome.NotAttempted, false, false);
        if (!ReferenceEquals(account, session.Snapshot) || connection.Snapshot.Phase != AccountConnectionPhase.ReceivingHeld ||
            connection.Publication is not { Phase: AccountReceivePhase.Running } receive || receive.Attempt != attempt)
            return new(generation, AccountResourcePreparationStatus.AccountChanged, AccountResourceStorageOutcome.NotAttempted, false, false);
        return refresh ? await resources.RefreshAsync(generation, token).ConfigureAwait(false)
            : await resources.BootstrapAsync(generation, token).ConfigureAwait(false);
    }
    private void RevokeResources()
    {
        lock (gate)
        {
            resourceAccount = null; resourceAttempt = null; projected = null;
            if (!retired) resources.Invalidate();
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
                    KnowledgeCatalog = ProjectKnowledgeCatalog(catalogs.Items, catalogs.OptionalSkills),
                    NpcSkills = ProjectNpcSkills(catalogs.ReviewedNpcs),
                    ReconcileNpcSkills = true
                };
            }
        }
    }

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
