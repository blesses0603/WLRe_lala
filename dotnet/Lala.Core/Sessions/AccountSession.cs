namespace Lala.Core.Sessions;

public enum SessionPhase { Disconnected, Preparing, Verified, Held }
public sealed record SessionSnapshot(long Generation, string? AccountId, string? Endpoint,
    SessionPhase Phase, string? ResourceVersion);

/// <summary>
/// Single account generation boundary with internal receive-only ownership, not a live login implementation.
/// No credentials are retained. A safety hold is latched until a new session is begun.
/// </summary>
public sealed partial class AccountSession
{
    private readonly object gate = new();
    private SessionSnapshot current = new(0, null, null, SessionPhase.Disconnected, null);
    public SessionSnapshot Snapshot { get { lock (gate) return current; } }
    // Core-only admission callback. Never pass host/user code into the session gate.
    internal T WithLoginSnapshot<T>(Func<SessionSnapshot, T> operation)
    { lock (gate) return operation(current); }
    private TaskCompletionSource snapshotChanged = NewSnapshotSignal();
    internal Task SnapshotChanged { get { lock (gate) return snapshotChanged.Task; } }
    private static TaskCompletionSource NewSnapshotSignal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private void SetSnapshotLocked(SessionSnapshot next)
    {
        var previous = snapshotChanged;
        current = next;
        snapshotChanged = NewSnapshotSignal();
        previous.SetResult();
    }

    public SessionSnapshot Begin(string accountId, string endpoint)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(accountId);
        ArgumentException.ThrowIfNullOrWhiteSpace(endpoint);
        lock (gate)
        {
            RetireReceiveLocked();
            SetSnapshotLocked(new(checked(current.Generation + 1), accountId, endpoint, SessionPhase.Preparing, null));
            return current;
        }
    }

    /// <summary>Initial preparation only. Later version monitoring must call Hold; this never clears a hold.</summary>
    public bool ConfirmResources(long generation, string officialVersion, string databaseVersion, bool integrityVerified)
    {
        lock (gate)
        {
            if (generation != current.Generation || current.Phase != SessionPhase.Preparing) return false;
            if (!integrityVerified || string.IsNullOrWhiteSpace(officialVersion) || officialVersion != databaseVersion)
            {
                SetSnapshotLocked(current with { Phase = SessionPhase.Held });
                return false;
            }
            SetSnapshotLocked(current with { Phase = SessionPhase.Verified, ResourceVersion = officialVersion });
            return true;
        }
    }

    public bool Hold(long generation)
    {
        lock (gate)
        {
            if (generation != current.Generation || current.Phase == SessionPhase.Disconnected) return false;
            RetireReceiveLocked();
            SetSnapshotLocked(current with { Phase = SessionPhase.Held });
            return true;
        }
    }

    public void Disconnect()
    {
        lock (gate)
        {
            RetireReceiveLocked();
            SetSnapshotLocked(new(checked(current.Generation + 1), null, null, SessionPhase.Disconnected, null));
        }
    }

    /// <summary>Resource gate only, not authentication or command validation. Dispatch must also check ownership, arguments and server state.</summary>
    public bool AllowsResourceGate(long generation, string kind, string? action = null, bool? enabled = null)
    {
        lock (gate)
        {
            if (generation != current.Generation) return false;
            return current.Phase == SessionPhase.Verified ||
                current.Phase == SessionPhase.Held && ResourceSafetyPolicy.AllowsDuringHold(kind, action, enabled);
        }
    }
}
