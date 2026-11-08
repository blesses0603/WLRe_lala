using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions;

public enum AccountRoleSelectionMode { Fixed, Interactive }

/// <summary>Immutable, one-use request for this login epoch's server-provided roles.
/// Does not grant game-command authority. The callback must not reuse earlier choices.</summary>
public sealed class AccountRoleSelectionRequest
{
    public long Generation { get; }
    /// <summary>Login handshake epoch, distinct from a receive publication attempt.</summary>
    public Guid HandshakeAttempt { get; }
    public Guid RequestId { get; } = Guid.NewGuid();
    public ImmutableArray<RoleSnapshot> Roles { get; }
    /// <summary>Create a choice bound to this exact request. Runtime validates availability.</summary>
    public AccountRoleSelectionChoice Choose(int index) => new(this, index);
    public override string ToString() => "Account role selection request (roles redacted)";
    internal AccountRoleSelectionRequest(long generation, Guid attempt, ImmutableArray<RoleSnapshot> roles)
        => (Generation, HandshakeAttempt, Roles) = (generation, attempt, roles);
}

/// <summary>A choice bound to the request that created it, without send authority.</summary>
public sealed class AccountRoleSelectionChoice
{
    internal AccountRoleSelectionRequest Request { get; }
    public int Index { get; }
    internal AccountRoleSelectionChoice(AccountRoleSelectionRequest request, int index) => (Request, Index) = (request, index);
    public override string ToString() => "Account role selection choice";
}

/// <summary>Opt-in host role choice after authentication. Return an unlocked index from
/// this exact request, or null to decline. Honor cancellation. Completion and disposal
/// remain pending until even a noncooperative callback returns; late choices never send.
/// No automatic retries are permitted with an interactive selector. Host choice is not
/// evidence of user consent: obtain permission for this mode before starting login.
/// Callback executes without lifecycle locks.</summary>
public interface IAccountRoleSelector
{
    ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken cancellationToken);
}
