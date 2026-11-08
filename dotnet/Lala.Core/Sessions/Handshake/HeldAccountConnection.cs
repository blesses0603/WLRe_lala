using System.Net;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;

namespace Lala.Core.Sessions.Handshake;

/// <summary>
/// Internal account-bound login plus continuous reception. Admission is synchronous and
/// happens before any socket or credential-provider call. ResourceHeld is unconditional:
/// protocol login completion is not runtime admission or permission for game actions.
/// Run is one-shot; restart requires an explicit new account generation and fresh provider,
/// and attachment stays blocked until previous cleanup succeeds. Nothing retries uncertain
/// writes or stores credentials for reconnect. No Desktop/Android adapter installs this type.
/// </summary>
internal sealed class HeldAccountConnection : IAsyncDisposable
{
    private readonly AccountSession session;
    private readonly long generation;
    private readonly HeldLoginTransport transport;
    private readonly ReceiveAttempt receive;
    private readonly object outcomeGate = new();
    private Task<ReceiveResult>? running;
    private HeldAccountConnection(AccountSession session, long generation,
        HeldLoginTransport transport, ReceiveAttempt receive)
        => (this.session, this.generation, this.transport, this.receive) = (session, generation, transport, receive);

    internal static HeldAccountConnection? TryAttach(AccountSession session, long generation,
        IPEndPoint verification, IPEndPoint formal, int txXor, int rxXor, int roleIndex,
        Func<HandshakeLeg, Packet> loginProvider,
        Func<double> clock, Func<ServiceStateSnapshot, double, ServiceObservationInputs> observe,
        HeldLoginLimits? limits = null, int readSize = 4096, int bufferedChunks = 4)
    {
        ArgumentNullException.ThrowIfNull(session);
        var transport = new HeldLoginTransport(verification, formal, txXor, rxXor, roleIndex, loginProvider, limits);
        ReceiveAttempt? attempt;
        try
        {
            attempt = session.AttachHeldReceive(generation, transport, rxXor, clock, observe,
                readSize, bufferedChunks, transport.BeforeCommitAsync);
        }
        catch
        {
            // Constructor is inert, so disposal has no transport/callback work to wait for.
            transport.DisposeAsync().AsTask().GetAwaiter().GetResult();
            throw;
        }
        if (attempt is null)
        {
            transport.DisposeAsync().AsTask().GetAwaiter().GetResult();
            return null;
        }
        return new(session, generation, transport, attempt);
    }

    internal Guid Attempt => receive.Latest.Attempt;
    internal ReceivePublication? Publication => session.ReadHeldReceive(generation, Attempt);
    internal HandshakeView Handshake => transport.Handshake;
    internal Task<HandshakeView> Login => transport.Login;
    internal IReadOnlyList<Transport.TcpTransportView> Connections => transport.Connections;
    internal bool ResourceHeld => true;
    internal bool CanSendCommands => false;
    internal Task<ReceiveResult> RunAsync(CancellationToken cancellationToken = default)
    {
        lock (outcomeGate) return running ??= receive.RunAsync(cancellationToken);
    }
    internal HeldConnectionOutcome GetOutcome(ReceiveResult result)
    {
        lock (outcomeGate)
        {
            if (running is not { IsCompletedSuccessfully: true } || !ReferenceEquals(running.Result, result))
                throw new InvalidOperationException("Outcome requires this connection's completed receive result.");
            return transport.GetOutcome(result);
        }
    }
    public ValueTask DisposeAsync() => receive.DisposeAsync();
}
