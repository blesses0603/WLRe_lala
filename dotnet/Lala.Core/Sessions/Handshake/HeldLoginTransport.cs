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
/// not credential encryption. Legacy callers own packet inputs; owned providers clear their transient credentials.
/// No profile discovery, saved credentials, automatic retries, or production-host defaults.
/// </summary>
internal sealed class HeldLoginTransport : IReceiveTransport, IReceiveTransportRetirement, IReceiveWorldStatus
{
    private readonly object gate = new();
    private readonly IPEndPoint verificationEndpoint, formalEndpoint;
    private readonly int txKey, rxXor, roleIndex;
    private readonly HeldLoginLimits limits;
    private readonly ScriptedHandshake handshake;
    private readonly IAccountRoleSelector? roleSelector;
    private readonly long generation;
    private readonly SemaphoreSlim protocolGate = new(1, 1);
    private Task? selectionOperation;
    private IHandshakeLoginProvider? loginProvider;
    private readonly AccountLoginAdmission? loginAdmission;
    private readonly List<BoundedTcpTransport> transports = [];
    private readonly List<Task> chatWrites = [];
    private readonly CancellationTokenSource stop = new(), deadline = new();
    private readonly TaskCompletionSource<HandshakeView> login = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private BoundedTcpTransport? formal;
    private Task<int>? readOperation;
    private Task? handlerOperation, disposal;
    private bool initialized, retired, inputEnded, loginCompleted, providerCleanupFailed;
    private uint? localRole;
    private ushort? acknowledgedScene;
    private bool outpostReceived, expeditionReceived, expeditionTimeRequested;
    private readonly HashSet<HeldConnectionFailure> failures = [];

    private void Record(HeldConnectionFailure failure) { lock (gate) failures.Add(failure); }
    internal HeldConnectionOutcome GetOutcome(ReceiveResult result)
    {
        lock (gate) return HeldConnectionOutcome.Classify(result, loginCompleted, failures);
    }

    private void RecordDeadline()
    {
        if (deadline.IsCancellationRequested) Record(HeldConnectionFailure.LoginDeadline);
    }

    internal HeldLoginTransport(IPEndPoint verification, IPEndPoint formal, int txXor, int rxXor,
        int roleIndex, Func<HandshakeLeg, Packet>? loginProvider, HeldLoginLimits? limits = null,
        IHandshakeLoginProvider? ownedProvider = null, AccountLoginAdmission? loginAdmission = null, IAccountRoleSelector? roleSelector = null, long generation = 0)
    {
        if (loginProvider is null && ownedProvider is null) throw new ArgumentNullException(nameof(loginProvider));
        if (loginProvider is not null && ownedProvider is not null)
            throw new ArgumentException("Exactly one login provider is required.");
        this.loginAdmission = loginAdmission; this.roleSelector = roleSelector; this.generation = generation;
        verificationEndpoint = CopyEndpoint(verification); formalEndpoint = CopyEndpoint(formal);
        WireCodec.ValidateKey(txXor); WireCodec.ValidateKey(rxXor);
        if (roleIndex is not (1 or 2)) throw new ArgumentOutOfRangeException(nameof(roleIndex));
        this.limits = limits ?? new(); this.limits.Validate();
        this.txKey = txXor; this.rxXor = rxXor; this.roleIndex = roleIndex; this.loginProvider = ownedProvider ?? new DelegateHandshakeLoginProvider(loginProvider!);
        handshake = new(txXor);
    }

    internal HandshakeView Handshake => handshake.Snapshot;
    internal Task<HandshakeView> Login => login.Task;
    public bool WorldAcknowledged { get { lock (gate) return !retired && loginCompleted; } }
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

    internal Task SendChatAsync(Packet packet, Func<bool> current, CancellationToken token)
    {
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            chatWrites.RemoveAll(task => task.IsCompleted);
            if (chatWrites.Count >= 8) throw new InvalidOperationException("聊天傳送佇列已滿，請稍候。");
            var operation = Task.Run(() => SendChatCoreAsync(packet, current, token));
            chatWrites.Add(operation); return operation;
        }
    }
    private async Task SendChatCoreAsync(Packet packet, Func<bool> current, CancellationToken token)
    {
        if (packet.Main != 2 || packet.Sub is not (1 or 2 or 3 or 5 or 6) || packet.Payload.Length > 512)
            throw new ProtocolException("Invalid outgoing chat packet.");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token);
        await protocolGate.WaitAsync(linked.Token).ConfigureAwait(false);
        try
        {
            lock (gate)
                if (retired || inputEnded || !loginCompleted || formal is null) throw new HeldLoginException();
            if (!current()) throw new InvalidOperationException("Account connection changed before chat transmission.");
            await WriteExactAsync(formal!, WireCodec.Encode(packet, txKey), linked.Token).ConfigureAwait(false);
        }
        catch (HeldLoginException) { Retire(); throw; }
        finally { protocolGate.Release(); }
    }
    internal Task SendGameAsync(Func<Packet> prepare, CancellationToken token)
    {
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            chatWrites.RemoveAll(task => task.IsCompleted);
            if (chatWrites.Count >= 8) throw new InvalidOperationException("操作傳送佇列已滿。");
            var operation = Task.Run(() => SendGameCoreAsync(prepare, token));
            chatWrites.Add(operation); return operation;
        }
    }
    private async Task SendGameCoreAsync(Func<Packet> prepare, CancellationToken token)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token);
        await protocolGate.WaitAsync(linked.Token).ConfigureAwait(false);
        try
        {
            lock (gate) if (retired || inputEnded || !loginCompleted || formal is null) throw new HeldLoginException();
            var packet = prepare(); // Recheck account/resources/intent immediately before the owned write.
            if (packet.Main is not (6 or 8 or 10 or 13 or 19 or 20 or 23 or 27 or 31 or 33 or 39 or 50 or 62 or 64 or 65 or 85 or 122 or 124 or 186 or 191) || packet.Payload.Length > 4096)
                throw new ProtocolException("Unsupported outgoing game command.");
            linked.Token.ThrowIfCancellationRequested();
            await WriteExactAsync(formal!, WireCodec.Encode(packet, txKey), linked.Token).ConfigureAwait(false);
        }
        catch (HeldLoginException) { Retire(); throw; }
        finally { protocolGate.Release(); }
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
            int count;
            try { count = await formal!.ReadAsync(destination, linked.Token).ConfigureAwait(false); }
            // TCP retains the first terminal reason, including a racing write timeout.
            // Independent sticky write evidence still vetoes retry after all operations drain.
            catch (TcpTransportException error) when (error.Reason == TcpTransportEnd.TimedOut)
            { Record(HeldConnectionFailure.ReadTimedOut); throw; }
            catch (TcpTransportException error) when (error.Reason == TcpTransportEnd.ReadFailed)
            { Record(HeldConnectionFailure.ReadFailed); throw; }
            catch (TcpTransportException error) when (error.Reason is TcpTransportEnd.Cancelled or TcpTransportEnd.Disposed)
            { Record(HeldConnectionFailure.CancelledOrHeld); throw; }
            catch (Exception) { Record(HeldConnectionFailure.IncompleteLoginOrUnknown); throw; }
            if (count == 0) { lock (gate) inputEnded = true; Record(HeldConnectionFailure.RemoteEof); }
            return count;
        }
        catch (Exception) { RecordDeadline(); EndHandshake(token.IsCancellationRequested || stop.IsCancellationRequested); throw new HeldLoginException(); }
    }

    private async Task InitializeAsync(CancellationToken token)
    {
        try
        {
            var verification = CreateTransport(verificationEndpoint);
            try
            {
                await ConnectAsync(verification, token).ConfigureAwait(false);
                await FlushAsync(verification, MakeLogin(HandshakeLeg.Verification, token), token, credentialWrite: true).ConfigureAwait(false);
                var decoder = new FrameDecoder(rxXor);
                var buffer = new byte[Math.Min(4096, limits.Tcp.MaximumReadBytes)];
                int total = 0, events = 0;
                while (handshake.Snapshot.Phase != HandshakePhase.Verified)
                {
                    int count = await verification.ReadAsync(buffer, token).ConfigureAwait(false);
                    if (count == 0) { Record(HeldConnectionFailure.IncompleteLoginOrUnknown); throw new HeldLoginException(); }
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
            catch (ProtocolException) { Record(HeldConnectionFailure.InvalidProtocol); throw; }
            finally { await verification.DisposeAsync().ConfigureAwait(false); }
            token.ThrowIfCancellationRequested();
            formal = CreateTransport(formalEndpoint);
            await ConnectAsync(formal, token).ConfigureAwait(false);
            await FlushAsync(formal, MakeLogin(HandshakeLeg.Formal, token), token, credentialWrite: true).ConfigureAwait(false);
        }
        finally { ReleaseProvider(); }
    }

    private ScriptedHandshakeWrite MakeLogin(HandshakeLeg leg, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        loginAdmission?.Check(token);
        IHandshakeLoginProvider provider;
        lock (gate)
        {
            if (retired) throw new HeldLoginException();
            provider = loginProvider ?? throw new HeldLoginException();
        }
        LoginPacketLease lease;
        try { lease = provider.Create(leg); }
        catch (Exception) { Record(HeldConnectionFailure.ProviderFailed); throw new HeldLoginException(); }
        using (lease)
        lock (gate)
        {
            token.ThrowIfCancellationRequested();
            if (retired) throw new HeldLoginException();
            var write = handshake.BeginLogin(handshake.Snapshot.Attempt, leg, lease.Packet);
            if (write is null) { Record(HeldConnectionFailure.LoginProtocolFailed); throw new HeldLoginException(); }
            return write;
        }
    }

    private async Task HandleCoreAsync(ServerEvent observation, CancellationToken token)
    {
        try
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token, deadline.Token);
            linked.Token.ThrowIfCancellationRequested();
            var transport = formal ?? throw new HeldLoginException();
            await protocolGate.WaitAsync(linked.Token).ConfigureAwait(false);
            try
            {
                if(observation is ServerExpeditionEvent expedition)
                {
                    outpostReceived |= expedition.Event is OutpostSnapshotEvent;
                    expeditionReceived |= expedition.Event is ExpeditionSnapshotEvent;
                }
                if (handshake.Snapshot.Phase == HandshakePhase.ScriptedComplete)
                {
                    if(observation is ServerLayoutEvent{Event:WorldPlayerEvent replacement})
                    {localRole=replacement.Player.RoleId;acknowledgedScene=replacement.Player.Scene;}
                    if (observation is LoginResultEvent or ServerLayoutEvent { Event: RoleListAvailableEvent })
                    {
                        Record(HeldConnectionFailure.LoginProtocolFailed);
                        throw new HeldLoginException(); // Never silently accept a second login epoch.
                    }
                    if (observation is HeartbeatRequestEvent)
                    {
                        // Exact fixed protocol reply only. No general send API is exposed.
                        byte[] bytes = WireCodec.Encode(new Packet(63, 5), txKey);
                        try { await WriteExactAsync(transport, bytes, linked.Token).ConfigureAwait(false); }
                        finally { System.Security.Cryptography.CryptographicOperations.ZeroMemory(bytes); }
                    }
                    if(observation is PositionSnapshotEvent position && position.RoleId==localRole)
                    {
                        if(acknowledgedScene!=position.Scene)
                            await WriteProtocolAsync(transport,new(12,1),linked.Token).ConfigureAwait(false);
                        await WriteProtocolAsync(transport,new(3,2),linked.Token).ConfigureAwait(false);
                        acknowledgedScene=position.Scene;
                    }
                    await RequestExpeditionTimeAsync(transport,linked.Token).ConfigureAwait(false);
                    return;
                }
                if(observation is ServerLayoutEvent { Event:WorldPlayerEvent world })
                {localRole=world.Player.RoleId;acknowledgedScene=world.Player.Scene;}
                await FlushAsync(transport, handshake.Observe(handshake.Snapshot.Attempt,
                    HandshakeLeg.Formal, observation), linked.Token).ConfigureAwait(false);
                if (handshake.Snapshot.Phase == HandshakePhase.Selection && selectionOperation is null)
                {
                    if (roleSelector is null)
                        await FlushAsync(transport, handshake.SelectRole(handshake.Snapshot.Attempt, roleIndex), linked.Token).ConfigureAwait(false);
                    else
                    {
                        if (observation is not ServerLayoutEvent { Event: RoleListAvailableEvent list } ||
                            list.Roles.IsEmpty || !list.Roles.Any(r => !r.Locked)) throw new HeldLoginException();
                        var request = new AccountRoleSelectionRequest(generation, handshake.Snapshot.Attempt, list.Roles);
                        lock (gate)
                        {
                            if (retired) throw new HeldLoginException();
                            selectionOperation = Task.Run(() => SelectInteractiveAsync(request, token));
                        }
                    }
                }
                if (handshake.Snapshot.Phase == HandshakePhase.ScriptedComplete)
                {
                    deadline.CancelAfter(Timeout.InfiniteTimeSpan);
                    linked.Token.ThrowIfCancellationRequested();
                    lock (gate)
                    {
                        if (retired) throw new HeldLoginException();
                        loginCompleted = true;
                        login.TrySetResult(handshake.Snapshot);
                    }
                    await RequestExpeditionTimeAsync(transport,linked.Token).ConfigureAwait(false);
                }
            }
            finally { protocolGate.Release(); }
        }
        catch (Exception) { Record(HeldConnectionFailure.EventHandlerFailed); RecordDeadline(); EndHandshake(token.IsCancellationRequested || stop.IsCancellationRequested); throw new HeldLoginException(); }
    }

    private async Task WriteProtocolAsync(BoundedTcpTransport transport,Packet packet,CancellationToken token)
    {
        var bytes=WireCodec.Encode(packet,txKey);
        try{await WriteExactAsync(transport,bytes,token).ConfigureAwait(false);}
        finally{System.Security.Cryptography.CryptographicOperations.ZeroMemory(bytes);}
    }
    private async Task RequestExpeditionTimeAsync(BoundedTcpTransport transport,CancellationToken token)
    {
        if(!outpostReceived||!expeditionReceived||expeditionTimeRequested)return;
        await WriteProtocolAsync(transport,new(31,28),token).ConfigureAwait(false);
        expeditionTimeRequested=true;
    }

    private async Task SelectInteractiveAsync(AccountRoleSelectionRequest request, CancellationToken token)
    {
        try
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token, deadline.Token);
            linked.Token.ThrowIfCancellationRequested();
            var choice = await roleSelector!.SelectAsync(request, linked.Token).ConfigureAwait(false);
            linked.Token.ThrowIfCancellationRequested();
            await protocolGate.WaitAsync(linked.Token).ConfigureAwait(false);
            try
            {
                linked.Token.ThrowIfCancellationRequested();
                if (choice is null || !ReferenceEquals(choice.Request, request) || !request.Roles.Any(r => r.Index == choice.Index && !r.Locked))
                    throw new HeldLoginException();
                await FlushAsync(formal!, handshake.SelectRole(request.HandshakeAttempt, choice.Index), linked.Token, roleSelection: true).ConfigureAwait(false);
            }
            finally { protocolGate.Release(); }
        }
        catch (Exception)
        {
            Record(HeldConnectionFailure.EventHandlerFailed); RecordDeadline();
            EndHandshake(token.IsCancellationRequested || stop.IsCancellationRequested);
            // Wake a pending read so receive retirement starts even without another server event.
            try { await stop.CancelAsync().ConfigureAwait(false); } catch (Exception) { }
        }
    }

    private async Task FlushAsync(BoundedTcpTransport transport, ScriptedHandshakeWrite? write, CancellationToken token, bool credentialWrite = false, bool roleSelection = false)
    {
        while (write is not null)
        {
            ScriptedHandshakeWrite? next;
            using (write)
            {
                await WriteExactAsync(transport, write.Bytes, token, credentialWrite ? write.Leg : null, roleSelection).ConfigureAwait(false);
                credentialWrite = false;
                next = handshake.CompleteWrite(write.Attempt, write.Leg, write.Operation,
                    write.Bytes, ScriptedWriteOutcome.Complete);
            }
            write = next;
        }
        if (handshake.Snapshot.Phase is HandshakePhase.Failed or HandshakePhase.Cancelled or HandshakePhase.Held)
        {
            Record(HeldConnectionFailure.LoginProtocolFailed);
            throw new HeldLoginException();
        }
    }

    private async Task WriteExactAsync(BoundedTcpTransport transport, byte[] bytes, CancellationToken token, HandshakeLeg? credentialLeg = null, bool roleSelection = false)
    {
        // Every failure in this operation is sticky, independently of the TCP terminal
        // reason, which may already have been set by a racing read/EOF.
        try
        {
            token.ThrowIfCancellationRequested();
            if (credentialLeg is { } pendingLeg && loginAdmission is not null)
                await loginAdmission.ConfirmAsync(pendingLeg, token).ConfigureAwait(false);
            Task<TcpWriteResult> Admit()
            {
                lock (gate)
                {
                    token.ThrowIfCancellationRequested();
                    if (retired || (roleSelection && inputEnded)) throw new HeldLoginException();
                    return transport.WriteAsync(bytes, token);
                }
            }
            // Guard the actual write admission, not only packet creation/acquisition.
            // Session changes retire synchronously with this session-first lock order.
            var operation = credentialLeg is { } leg && loginAdmission is not null
                ? loginAdmission.Admit(leg, leg == HandshakeLeg.Verification ? verificationEndpoint : formalEndpoint, token, Admit)
                : Admit();
            var receipt = await operation.ConfigureAwait(false);
            if (receipt.Outcome == TcpWriteOutcome.PartialOrUncertain)
                Record(HeldConnectionFailure.WriteUncertain);
            if (receipt.Connection != transport.Snapshot.Connection || receipt.Outcome != TcpWriteOutcome.Complete ||
                receipt.ConfirmedLocalBytes != bytes.Length || receipt.End is not null)
                throw new HeldLoginException();
            token.ThrowIfCancellationRequested();
        }
        catch (Exception) { Record(HeldConnectionFailure.WriteFailed); throw; }
    }

    private async Task ConnectAsync(BoundedTcpTransport transport, CancellationToken token)
    {
        try
        {
            Task operation;
            lock (gate)
            {
                if (retired) throw new HeldLoginException();
                operation = transport.ConnectAsync(token);
            }
            await operation.ConfigureAwait(false);
        }
        catch (TcpTransportException error) when (error.Reason is TcpTransportEnd.ConnectFailed or TcpTransportEnd.TimedOut)
        {
            Record(error.Reason == TcpTransportEnd.TimedOut ? HeldConnectionFailure.ConnectTimedOut : HeldConnectionFailure.ConnectFailed);
            throw;
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
            operations = new Task?[] { readOperation, handlerOperation, selectionOperation }.OfType<Task>().Concat(chatWrites).ToArray();
        }
        foreach (var transport in owned)
            try { await transport.DisposeAsync().ConfigureAwait(false); } catch (Exception) { failed = true; }
        foreach (var operation in operations)
            try { await operation.ConfigureAwait(false); } catch (Exception) { /* Terminal operation faults are expected. */ }
        try { ReleaseProvider(); } catch (Exception) { failed = true; }
        // Initialization may already have detached the provider and observed its failure.
        // Draining operations above ensures that evidence cannot arrive after this check.
        lock (gate) failed |= providerCleanupFailed;
        stop.Dispose(); deadline.Dispose(); handshake.Dispose(); protocolGate.Dispose();
        if (failed) throw new HeldLoginCleanupException();
    }

    private void ReleaseProvider()
    {
        IHandshakeLoginProvider? provider;
        lock (gate) { provider = loginProvider; loginProvider = null; }
        // No provider or user code runs under the transport lifetime gate.
        try { provider?.Dispose(); }
        catch
        {
            lock (gate)
            {
                providerCleanupFailed = true;
                failures.Add(HeldConnectionFailure.CleanupFailed);
            }
            throw;
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
