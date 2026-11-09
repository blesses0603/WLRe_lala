using Lala.Core.Catalogs;
using Lala.Core.Sessions;

namespace Lala.Core.Resources;

/// <summary>
/// Read-only join of one exact account lifecycle snapshot and an owner-issued resource
/// activation. This does not confirm the session's resource gate or grant command authority.
/// Any account snapshot replacement invalidates the binding, even within one generation.
/// </summary>
internal sealed class AccountResourceBinding
{
    private readonly AccountSession _session;
    private readonly SessionSnapshot _snapshot;
    private readonly ResourceRuntimeActivation _activation;
    private AccountResourceBinding(AccountSession session, SessionSnapshot snapshot, ResourceRuntimeActivation activation)
        => (_session, _snapshot, _activation) = (session, snapshot, activation);

    internal long AccountGeneration => _snapshot.Generation;
    internal long ResourceGeneration => _activation.Generation;
    internal ManifestIdentity Identity => _activation.Identity;
    internal bool CanLogin => false;
    internal bool CanSendPackets => false;
    private bool HasSameAccountSnapshot => ReferenceEquals(_session.Snapshot, _snapshot);
    internal bool IsCurrent => HasSameAccountSnapshot && _activation.IsActive && HasSameAccountSnapshot;

    /// <summary>No I/O or account mutation. A failed selection never clears another account's
    /// resource activation. The caller must bind again after a lifecycle transition.</summary>
    internal static bool TryBind(AccountSession session, long expectedGeneration, ResourceRuntimeOwner owner,
        ResourceRuntimePublication? expectedPublication, out AccountResourceBinding? binding)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(owner);
        binding = null;
        var snapshot = session.Snapshot;
        if (snapshot.Generation != expectedGeneration || snapshot.Phase == SessionPhase.Disconnected ||
            !owner.TryActivate(expectedPublication, out var activation)) return false;
        var candidate = new AccountResourceBinding(session, snapshot, activation!);
        if (!candidate.IsCurrent) return false;
        binding = candidate;
        return true;
    }

    /// <summary>Immutable point-in-time data only. Account checks bracket the resource read
    /// without nesting session/resource locks. A later revocation cannot erase returned data;
    /// neither this binding nor a retained catalog reference authorizes external effects.</summary>
    internal bool TryReadItemImage(ushort itemId, out byte[]? png)
    {
        png = null;
        if (!HasSameAccountSnapshot || !_activation.TryReadItemImage(itemId, out var bytes) || !HasSameAccountSnapshot) return false;
        png = bytes; return true;
    }
    internal bool TryReadPortrait(PortraitMaterialKey key, out PortraitCachedImage? image)
    {
        image = null;
        if (!HasSameAccountSnapshot || !_activation.TryReadPortrait(key, out var selected) || !HasSameAccountSnapshot) return false;
        image = selected; return true;
    }
    internal bool TrySelectPortrait(Lala.Core.Protocol.WorldPlayer? player,
        Lala.Core.Inventory.CompanionReceiveSnapshot companions, bool companion,
        out PortraitSelection? selection, out PortraitCachedImage? image)
    {
        selection = null; image = null;
        if (!HasSameAccountSnapshot || !_activation.TrySelectPortrait(player, companions, companion, out var chosen, out var cached) || !HasSameAccountSnapshot) return false;
        selection = chosen; image = cached; return true;
    }
    internal bool TryReadCatalogs(out OfflineRuntimeCandidate? catalogs)
    {
        catalogs = null;
        if (!HasSameAccountSnapshot || !_activation.TryReadCatalogs(out var candidate) || !HasSameAccountSnapshot)
            return false;
        catalogs = candidate;
        return true;
    }
}
