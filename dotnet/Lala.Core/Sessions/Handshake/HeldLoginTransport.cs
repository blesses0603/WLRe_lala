using System.Net;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;

namespace Lala.Core.Sessions.Handshake;

internal sealed record HeldLoginLimits
{
    internal TcpTransportLimits Tcp { get; init; } = new();
    internal TimeSpan LoginTimeout { get; init; } = TimeSpan.FromSeconds(30);
    internal int MaximumVerificationBytes { get; init; } = 1024 * 1024;
    internal int MaximumVerificationEvents { get; init; } = 4096;
    internal void Validate()
    {
        ArgumentNullException.ThrowIfNull(Tcp); Tcp.Validate();
        if (LoginTimeout <= TimeSpan.Zero || LoginTimeout > TimeSpan.FromMinutes(2) ||
            MaximumVerificationBytes is < 1 or > 1048576 || MaximumVerificationEvents is < 1 or > 4096)
            throw new ArgumentOutOfRangeException(nameof(HeldLoginLimits));
    }
}
internal sealed class HeldLoginException() : IOException("Held login connection ended.");
internal sealed class HeldLoginCleanupException() : IOException("Held login connection cleanup failed.");

/// <summary>
/// Internal, uninstalled two-leg login transport. Its formal stream is decoded only by
/// ReceiveAttempt, including every byte after the final world ACK: there is no decoder or
/// state handoff. The serialized pre-commit hook sends only login/role/world/heartbeat
/// protocol traffic; resource-dependent game commands are never exposed. Raw TCP/XOR is
/// not credential encryption. Callers own the transient packet provider and its inputs.
/// No profile discovery, saved credentials, automatic retries, or production-host defaults.
/// </summary>
internal sealed class HeldLoginTransport : IReceiveTransport, IReceiveTransportRetirement
{
    private readonly object gate = new();
    private readonly IPEndPoint verificationEndpoint, formalEndpoint;
    private readonly int txKey, rxXor, roleIndex;
    private readonly HeldLoginLimits limits;
    private readonly ScriptedHandshake handshake;
    private Func<HandshakeLeg, Packet>? loginProvider;
    private readonly List<BoundedTcpTransport> transports = [];
    private readonly CancellationTokenSource stop = new(), deadline = new();
    private readonly TaskCompletionSource<HandshakeView> login = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private BoundedTcpTransport? formal;
    private Task<int>? readOperation;
    private Task? handlerOperation, disposal;
    private bool initialized, retired, inputEnded;

    internal HeldLoginTransport(IPEndPoint verification, IPEndPoint formal, int txXor, int rxXor,
        int roleIndex, Func<HandshakeLeg, Packet> loginProvider, HeldLoginLimits? limits = null)
    {
        ArgumentNullException.ThrowIfNull(loginProvider);
        verificationEndpoint = CopyEndpoint(verification); formalEndpoint = CopyEndpoint(formal);
        WireCodec.ValidateKey(txXor); WireCodec.ValidateKey(rxXor);
        if (roleIndex is not (1 or 2)) throw new ArgumentOutOfRangeException(nameof(roleIndex));
        this.limits = limits ?? new(); this.limits.Validate();
        this.txKey = txXor; this.rxXor = rxXor; this.roleIndex = roleIndex; this.loginProvider = loginProvider;
        handshake = new(txXor);
    }

    internal HandshakeView Handshake => handshake.Snapshot;
    internal Task<HandshakeView> Login => login.Task;
    internal IReadOnlyList<TcpTransportView> Connections
    {
        get { lock (gate) return transports.Select(t => t.Snapshot).ToArray(); }
    }

    public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
    {
        if (destination.IsEmpty) throw new ArgumentException("Nonempty destination required.", nameof(destination));
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            if (readOperation is { IsCompleted: false }) throw new InvalidOperationException("One read is already pending.");
            // Never execute a credential provider while holding the lifecycle lock.
            return new(readOperation = Task.Run(() => ReadCoreAsync(destination, cancellationToken)));
        }
    }

    internal ValueTask BeforeCommitAsync(ServerEvent observation, CancellationToken cancellationToken)
    {
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            if (handlerOperation is { IsCompleted: false }) throw new InvalidOperationException("One handler is already pending.");
            return new(handlerOperation = Task.Run(() => HandleCoreAsync(observation, cancellationToken)));
        }
    }

    private async Task<int> ReadCoreAsync(Memory<byte> destination, CancellationToken token)
    {
        try
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token, deadline.Token);
            if (!initialized)
            {
                deadline.CancelAfter(limits.LoginTimeout);
                await InitializeAsync(linked.Token).ConfigureAwait(false);
                initialized = true;
            }
            int count = await formal!.ReadAsync(destination, linked.Token).ConfigureAwait(false);
            if (count == 0) { lock (gate) inputEnded = true; }
            return count;
        }
        catch (Exception) { EndHandshake(token.IsCancellationRequested || stop.IsCancellationRequested); throw new HeldLoginException(); }
    }

    private async Task InitializeAsync(CancellationToken token)
    {
        try
        {
            var verification = CreateTransport(verificationEndpoint);
            try
            {
                await ConnectAsync(verification, token).ConfigureAwait(false);
                await FlushAsync(verification, MakeLogin(HandshakeLeg.Verification, token), token).ConfigureAwait(false);
                var decoder = new FrameDecoder(rxXor);
                var buffer = new byte[Math.Min(4096, limits.Tcp.MaximumReadBytes)];
                int total = 0, events = 0;
                while (handshake.Snapshot.Phase != HandshakePhase.Verified)
                {
                    int count = await verification.ReadAsync(buffer, token).ConfigureAwait(false);
                    if (count == 0) throw new HeldLoginException();
                    total = checked(total + count);
                    if (total > limits.MaximumVerificationBytes) throw new HeldLoginException();
                    bool verified = false;
                    for (int offset = 0; offset < count && !verified; offset++)
                        foreach (var packet in decoder.Feed(buffer.AsSpan(offset, 1)))
                        {
                            if (++events > limits.MaximumVerificationEvents) throw new HeldLoginException();
                            var observation = ServerProtocol.Decode(packet);
                            await FlushAsync(verification, handshake.Observe(handshake.Snapshot.Attempt,
                                HandshakeLeg.Verification, observation), token).ConfigureAwait(false);
                            verified = handshake.Snapshot.Phase == HandshakePhase.Verified;
                        }
                    // Like Python verify_account, success ends this separate verification
                    // connection immediately. No suffix is transferred to the formal stream.
                }
            }
            finally { await verification.DisposeAsync().ConfigureAwait(false); }
            token.ThrowIfCancellationRequested();
            formal = CreateTransport(formalEndpoint);
            await ConnectAsync(formal, token).ConfigureAwait(false);
            await FlushAsync(formal, MakeLogin(HandshakeLeg.Formal, token), token).ConfigureAwait(false);
        }
        finally { loginProvider = null; }
    }

    private ScriptedHandshakeWrite MakeLogin(HandshakeLeg leg, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        Func<HandshakeLeg, Packet> provider;
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            provider = loginProvider ?? throw new HeldLoginException();
        }
        var packet = provider(leg);
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            return handshake.BeginLogin(handshake.Snapshot.Attempt, leg, packet) ?? throw new HeldLoginException();
        }
    }

    private async Task HandleCoreAsync(ServerEvent observation, CancellationToken token)
    {
        try
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token, deadline.Token);
            linked.Token.ThrowIfCancellationRequested();
            var transport = formal ?? throw new HeldLoginException();
            if (handshake.Snapshot.Phase == HandshakePhase.ScriptedComplete)
            {
                if (observation is LoginResultEvent or ServerLayoutEvent { Event: RoleListAvailableEvent })
                    throw new HeldLoginException(); // Never silently accept a second login epoch.
                if (observation is HeartbeatRequestEvent)
                {
                    // Exact fixed protocol reply only. No general send API is exposed.
                    byte[] bytes = WireCodec.Encode(new Packet(63, 5), txKey);
                    try { await WriteExactAsync(transport, bytes, linked.Token).ConfigureAwait(false); }
                    finally { System.Security.Cryptography.CryptographicOperations.ZeroMemory(bytes); }
                }
                return;
            }
            await FlushAsync(transport, handshake.Observe(handshake.Snapshot.Attempt,
                HandshakeLeg.Formal, observation), linked.Token).ConfigureAwait(false);
            if (handshake.Snapshot.Phase == HandshakePhase.Selection)
                await FlushAsync(transport, handshake.SelectRole(handshake.Snapshot.Attempt, roleIndex), linked.Token).ConfigureAwait(false);
            if (handshake.Snapshot.Phase == HandshakePhase.ScriptedComplete)
            {
                deadline.CancelAfter(Timeout.InfiniteTimeSpan);
                linked.Token.ThrowIfCancellationRequested();
                login.TrySetResult(handshake.Snapshot);
            }
        }
        catch (Exception) { EndHandshake(token.IsCancellationRequested || stop.IsCancellationRequested); throw new HeldLoginException(); }
    }

    private async Task FlushAsync(BoundedTcpTransport transport, ScriptedHandshakeWrite? write, CancellationToken token)
    {
        while (write is not null)
        {
            ScriptedHandshakeWrite? next;
            using (write)
            {
                await WriteExactAsync(transport, write.Bytes, token).ConfigureAwait(false);
                next = handshake.CompleteWrite(write.Attempt, write.Leg, write.Operation,
                    write.Bytes, ScriptedWriteOutcome.Complete);
            }
            write = next;
        }
        if (handshake.Snapshot.Phase is HandshakePhase.Failed or HandshakePhase.Cancelled or HandshakePhase.Held)
            throw new HeldLoginException();
    }

    private async Task WriteExactAsync(BoundedTcpTransport transport, byte[] bytes, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        Task<TcpWriteResult> operation;
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            // Admission and synchronous retirement share this lock. Already-admitted writes
            // may have reached the socket and are never replayed; no new write starts later.
            operation = transport.WriteAsync(bytes, token);
        }
        var receipt = await operation.ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        if (receipt.Connection != transport.Snapshot.Connection || receipt.Outcome != TcpWriteOutcome.Complete ||
            receipt.ConfirmedLocalBytes != bytes.Length || receipt.End is not null) throw new HeldLoginException();
    }

    private Task ConnectAsync(BoundedTcpTransport transport, CancellationToken token)
    {
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            return transport.ConnectAsync(token);
        }
    }

    private BoundedTcpTransport CreateTransport(IPEndPoint endpoint)
    {
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            var transport = new BoundedTcpTransport(endpoint, limits.Tcp);
            transports.Add(transport);
            return transport;
        }
    }

    private void EndHandshake(bool cancelled = false)
    {
        if (cancelled) handshake.Cancel(); else handshake.EndInput();
        login.TrySetResult(handshake.Snapshot);
    }
    public void Retire()
    {
        lock (gate)
        {
            retired = true;
            handshake.Cancel();
            login.TrySetResult(handshake.Snapshot);
        }
    }

    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            retired = true;
            if (inputEnded) handshake.EndInput(); else handshake.Cancel();
            login.TrySetResult(handshake.Snapshot);
            if (disposal is null && readOperation is null && handlerOperation is null && transports.Count == 0)
            {
                loginProvider = null; stop.Dispose(); deadline.Dispose(); handshake.Dispose();
                disposal = Task.CompletedTask;
            }
            return new(disposal ??= Task.Run(DisposeCoreAsync));
        }
    }

    private async Task DisposeCoreAsync()
    {
        bool failed = false;
        try { await stop.CancelAsync().ConfigureAwait(false); } catch (Exception) { failed = true; }
        BoundedTcpTransport[] owned;
        Task[] operations;
        lock (gate)
        {
            owned = transports.ToArray();
            operations = new Task?[] { readOperation, handlerOperation }.OfType<Task>().ToArray();
        }
        foreach (var transport in owned)
            try { await transport.DisposeAsync().ConfigureAwait(false); } catch (Exception) { failed = true; }
        foreach (var operation in operations)
            try { await operation.ConfigureAwait(false); } catch (Exception) { /* Terminal operation faults are expected. */ }
        loginProvider = null;
        stop.Dispose(); deadline.Dispose(); handshake.Dispose();
        if (failed) throw new HeldLoginCleanupException();
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
