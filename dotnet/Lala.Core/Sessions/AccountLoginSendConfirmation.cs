using System.Net;

namespace Lala.Core.Sessions;

public enum AccountLoginRecipient { Verification, Formal }

/// <summary>Optional action-time host confirmation before each credential write. Called
/// outside lifecycle locks. Must honor cancellation, retain no secrets and never log input.
/// Returning true is not network encryption or proof of authenticated permission.</summary>
public interface IAccountLoginSendConfirmation
{
    ValueTask<bool> ConfirmAsync(AccountLoginRecipient recipient, IPEndPoint endpoint,
        CancellationToken cancellationToken);
}
