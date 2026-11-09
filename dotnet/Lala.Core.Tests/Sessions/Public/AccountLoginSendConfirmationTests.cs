using System.Net;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    private sealed class SendConfirmation(Func<AccountLoginRecipient, IPEndPoint, CancellationToken, ValueTask<bool>> callback)
        : IAccountLoginSendConfirmation
    {
        public ValueTask<bool> ConfirmAsync(AccountLoginRecipient recipient, IPEndPoint endpoint, CancellationToken token)
            => callback(recipient, endpoint, token);
    }

    [Theory]
    [InlineData(AccountLoginRecipient.Verification, false)]
    [InlineData(AccountLoginRecipient.Formal, false)]
    [InlineData(AccountLoginRecipient.Verification, true)]
    [InlineData(AccountLoginRecipient.Formal, true)]
    public async Task CredentialSendConfirmationDeclineOrFailureSendsNoBytesToDeclinedRecipient(AccountLoginRecipient decline, bool fail)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        var calls = new List<AccountLoginRecipient>();
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        var confirmation = new SendConfirmation((recipient, endpoint, _) =>
        {
            Assert.Equal(recipient == AccountLoginRecipient.Verification ? verification.Endpoint : formal.Endpoint, endpoint);
            calls.Add(recipient);
            // Defensive endpoint copy cannot redirect the pending send.
            endpoint.Port = 1;
            if (recipient == decline && fail) throw new InvalidOperationException("synthetic private failure");
            return ValueTask.FromResult(recipient != decline);
        });
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(credentials)), sendConfirmation: confirmation);
        var first = verification.Run(async client =>
        {
            if (decline == AccountLoginRecipient.Formal)
            {
                await ExpectPreparedLogin(client, 0); await client.Send(new Packet(63, 7, [0, 0]));
                await client.CloseSendAndExpectEof();
            }
            else await client.CloseSendAndExpectEof();
        });
        var second = decline == AccountLoginRecipient.Formal ? formal.Run(client => client.CloseSendAndExpectEof()) : Task.CompletedTask;
        var result = await preparation.RunAsync().WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(decline == AccountLoginRecipient.Verification ? new[] { AccountLoginRecipient.Verification }
            : new[] { AccountLoginRecipient.Verification, AccountLoginRecipient.Formal }, calls);
        Assert.True(credentials.IsDisposed); Assert.True(result.ResourcesReleased);
        Assert.False(result.Status.History[0].LoginProtocolCompleted);
        Assert.DoesNotContain("synthetic private failure", result.ToString());
    }

    [Theory]
    [InlineData("stop")] [InlineData("cancel")] [InlineData("replace")]
    public async Task LateSendApprovalAfterRetirementCannotWriteAndCleanupWaits(string action)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        var entered = Signal(); var release = Signal();
        using var cancellation = new CancellationTokenSource();
        var confirmation = new SendConfirmation(async (_, _, _) => { entered.SetResult(); await release.Task; return true; });
        await using var preparation = new AccountLoginPreparation(session, generation, Guid.NewGuid(), Profile(verification, formal),
            new Input((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password"))), sendConfirmation: confirmation);
        var server = verification.Run(client => client.CloseSendAndExpectEof());
        var run = preparation.RunAsync(cancellation.Token);
        try
        {
            await entered.Task.WaitAsync(Guard);
            if (action == "stop") preparation.Stop();
            else if (action == "cancel") cancellation.Cancel();
            else session.Begin("replacement", "loopback");
            var cleanup = preparation.DisposeAsync().AsTask();
            Assert.False(cleanup.IsCompleted);
            release.SetResult();
            var result = await run.WaitAsync(Guard); await cleanup.WaitAsync(Guard); await server.WaitAsync(Guard);
            Assert.True(result.ResourcesReleased); Assert.False(formal.HasPending);
        }
        finally { release.TrySetResult(); preparation.Stop(); }
    }
}
