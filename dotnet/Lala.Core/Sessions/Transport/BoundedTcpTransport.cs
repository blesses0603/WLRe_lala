using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using Lala.Core.Sessions.Receive;

namespace Lala.Core.Sessions.Transport;

internal enum TcpTransportStage { Created, Connecting, Connected, Retired, Disposed }
internal enum TcpTransportEnd { Cancelled, TimedOut, ConnectFailed, ReadFailed, WriteFailed, EndOfStream, Disposed, CleanupFailed }
internal enum TcpWriteOutcome { Complete, NotStarted, PartialOrUncertain }
internal sealed class TcpTransportException(TcpTransportEnd reason) : IOException("TCP transport ended: " + reason)
{
    internal TcpTransportEnd Reason { get; } = reason;
}
internal sealed record TcpWriteResult(Guid Connection, TcpWriteOutcome Outcome, int ConfirmedLocalBytes, TcpTransportEnd? End);
internal sealed record TcpTransportView(Guid Connection, TcpTransportStage Stage, TcpTransportEnd? End,
    bool ReadPending, bool WritePending);

internal sealed record TcpTransportLimits
{
    internal int MaximumReadBytes { get; init; } = 65536;
    internal int MaximumWriteBytes { get; init; } = 65539;
    internal int SendChunkBytes { get; init; } = 16384;
    internal int SocketBufferBytes { get; init; } = 16384;
    internal TimeSpan ConnectTimeout { get; init; } = TimeSpan.FromSeconds(5);
    internal TimeSpan ReadTimeout { get; init; } = TimeSpan.FromSeconds(30);
    internal TimeSpan WriteTimeout { get; init; } = TimeSpan.FromSeconds(10);
    internal void Validate()
    {
        if (MaximumReadBytes is < 1 or > 65536 || MaximumWriteBytes is < 1 or > 65539 ||
            SendChunkBytes is < 1 or > 65539 || SocketBufferBytes is < 1024 or > 65536)
            throw new ArgumentOutOfRangeException(nameof(TcpTransportLimits));
        foreach (var timeout in new[] { ConnectTimeout, ReadTimeout, WriteTimeout })
            if (timeout <= TimeSpan.Zero || timeout > TimeSpan.FromMinutes(5))
                throw new ArgumentOutOfRangeException(nameof(TcpTransportLimits));
    }
}

/// <summary>
/// Uninstalled raw TCP owner. No DNS, profiles, login, replay, reconnect, resource admission or
/// Android activation. A successful write means local socket submission, not peer acceptance.
/// Game XOR framing is not encryption: this transport does not secure credentials.
/// One connect, at most one read and one write; extra operations are rejected, never queued.
/// EOF, timeout, cancellation or I/O failure retires the entire connection. Dispose waits for
/// every admitted operation and its owned write-buffer cleanup. Tests dial loopback only.
/// </summary>
internal sealed class BoundedTcpTransport : IReceiveTransport
{
    private readonly object gate = new();
    private readonly Guid identity = Guid.NewGuid();
    private readonly IPEndPoint endpoint;
    private readonly TcpTransportLimits limits;
    private readonly Socket socket;
    private TcpTransportStage stage;
    private TcpTransportEnd? end;
    private bool reading, writing, cleanupFailed;
    private Task? connection, disposal, readOperation, writeOperation;

    internal BoundedTcpTransport(IPEndPoint endpoint, TcpTransportLimits? limits = null)
    {
        ArgumentNullException.ThrowIfNull(endpoint);
        if (endpoint.AddressFamily is not (AddressFamily.InterNetwork or AddressFamily.InterNetworkV6) || endpoint.Port == 0)
            throw new ArgumentException("A concrete TCP endpoint is required.", nameof(endpoint));
        this.limits = limits ?? new(); this.limits.Validate();
        // Snapshot mutable endpoint/address values before any asynchronous operation.
        var address = endpoint.AddressFamily == AddressFamily.InterNetworkV6
            ? new IPAddress(endpoint.Address.GetAddressBytes(), endpoint.Address.ScopeId)
            : new IPAddress(endpoint.Address.GetAddressBytes());
        this.endpoint = new(address, endpoint.Port);
        socket = new Socket(endpoint.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
        try
        {
            socket.SendBufferSize = this.limits.SocketBufferBytes;
            socket.ReceiveBufferSize = this.limits.SocketBufferBytes;
            socket.NoDelay = true;
        }
        catch { socket.Dispose(); throw; }
    }

    internal TcpTransportView Snapshot
    {
        get { lock (gate) return new(identity, stage, end, reading || readOperation is { IsCompleted: false }, writing || writeOperation is { IsCompleted: false }); }
    }

    /// <summary>First call owns connection cancellation; subsequent calls return that same task.</summary>
    internal Task ConnectAsync(CancellationToken cancellationToken = default)
    {
        lock (gate)
        {
            if (connection is not null) return connection;
            if (stage != TcpTransportStage.Created) return Task.FromException(new TcpTransportException(end ?? TcpTransportEnd.Disposed));
            stage = TcpTransportStage.Connecting;
            return connection = ConnectCoreAsync(cancellationToken);
        }
    }

    public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
    {
        if (destination.IsEmpty) throw new ArgumentException("Read destination must not be empty.", nameof(destination));
        lock (gate)
        {
            RequireConnected();
            if (reading || readOperation is { IsCompleted: false }) throw new InvalidOperationException("One read is already pending.");
            reading = true;
            var operation = ReadCoreAsync(destination[..Math.Min(destination.Length, limits.MaximumReadBytes)], cancellationToken);
            readOperation = operation;
            return new(operation);
        }
    }

    /// <summary>Snapshots a bounded input before returning. The owned copy is cleared on every exit.
    /// A partial/uncertain result is terminal; callers must never replay its bytes automatically.</summary>
    internal Task<TcpWriteResult> WriteAsync(ReadOnlyMemory<byte> bytes, CancellationToken cancellationToken = default)
    {
        if (bytes.IsEmpty || bytes.Length > limits.MaximumWriteBytes)
            throw new ArgumentOutOfRangeException(nameof(bytes), "Write exceeds the configured nonempty bound.");
        lock (gate)
        {
            RequireConnected();
            if (writing || writeOperation is { IsCompleted: false }) throw new InvalidOperationException("One write is already pending.");
            byte[] owned = bytes.ToArray();
            writing = true;
            var operation = WriteCoreAsync(owned, cancellationToken);
            writeOperation = operation;
            return operation;
        }
    }

    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            RetireLocked(TcpTransportEnd.Disposed);
            return new(disposal ??= FinishDisposalAsync(new[] { connection, readOperation, writeOperation }.OfType<Task>().ToArray()));
        }
    }

    private async Task ConnectCoreAsync(CancellationToken token)
    {
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
            timeout.CancelAfter(limits.ConnectTimeout);
            try
            {
                timeout.Token.ThrowIfCancellationRequested();
                await socket.ConnectAsync(endpoint, timeout.Token).ConfigureAwait(false);
                timeout.Token.ThrowIfCancellationRequested();
                lock (gate)
                {
                    if (stage != TcpTransportStage.Connecting) throw new TcpTransportException(end ?? TcpTransportEnd.Disposed);
                    stage = TcpTransportStage.Connected;
                }
            }
            catch (Exception)
            {
                throw Retire(Error(token, timeout, TcpTransportEnd.ConnectFailed));
            }
        }
        finally { FinishOperation(); }
    }

    private async Task<int> ReadCoreAsync(Memory<byte> destination, CancellationToken token)
    {
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
            timeout.CancelAfter(limits.ReadTimeout);
            try
            {
                timeout.Token.ThrowIfCancellationRequested();
                int count = await socket.ReceiveAsync(destination, SocketFlags.None, timeout.Token).ConfigureAwait(false);
                timeout.Token.ThrowIfCancellationRequested();
                lock (gate)
                {
                    if (stage != TcpTransportStage.Connected) throw new TcpTransportException(end ?? TcpTransportEnd.Disposed);
                    if (count == 0) RetireLocked(TcpTransportEnd.EndOfStream);
                    return count;
                }
            }
            catch (Exception)
            {
                throw Retire(Error(token, timeout, TcpTransportEnd.ReadFailed));
            }
        }
        finally { FinishOperation(read: true); }
    }

    private async Task<TcpWriteResult> WriteCoreAsync(byte[] owned, CancellationToken token)
    {
        int confirmed = 0;
        bool attempted = false;
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
            timeout.CancelAfter(limits.WriteTimeout);
            try
            {
                while (confirmed < owned.Length)
                {
                    timeout.Token.ThrowIfCancellationRequested();
                    lock (gate) RequireConnected();
                    attempted = true;
                    int count = await socket.SendAsync(owned.AsMemory(confirmed, Math.Min(owned.Length - confirmed, limits.SendChunkBytes)),
                        SocketFlags.None, timeout.Token).ConfigureAwait(false);
                    if (count <= 0) throw new SocketException();
                    confirmed += count;
                }
                timeout.Token.ThrowIfCancellationRequested();
                lock (gate)
                {
                    RequireConnected();
                    return new(identity, TcpWriteOutcome.Complete, confirmed, null);
                }
            }
            catch (Exception)
            {
                var failure = Retire(Error(token, timeout, TcpTransportEnd.WriteFailed));
                return new(identity, attempted ? TcpWriteOutcome.PartialOrUncertain : TcpWriteOutcome.NotStarted,
                    confirmed, failure.Reason);
            }
        }
        finally
        {
            CryptographicOperations.ZeroMemory(owned);
            FinishOperation(write: true);
        }
    }

    private static TcpTransportEnd Error(CancellationToken token, CancellationTokenSource timeout, TcpTransportEnd fallback)
        => token.IsCancellationRequested ? TcpTransportEnd.Cancelled : timeout.IsCancellationRequested ? TcpTransportEnd.TimedOut : fallback;
    private void RequireConnected()
    {
        if (stage != TcpTransportStage.Connected)
            throw new TcpTransportException(end ?? TcpTransportEnd.ConnectFailed);
    }
    private TcpTransportException Retire(TcpTransportEnd reason)
    {
        lock (gate) { RetireLocked(reason); return new(end ?? reason); }
    }
    private void RetireLocked(TcpTransportEnd reason)
    {
        if (stage is TcpTransportStage.Retired or TcpTransportStage.Disposed) return;
        stage = TcpTransportStage.Retired; end = reason;
        // Mark retired before socket close, so late completions cannot admit new work.
        try { socket.Dispose(); } catch { cleanupFailed = true; }
    }
    private void FinishOperation(bool read = false, bool write = false)
    {
        lock (gate)
        {
            if (read) reading = false;
            if (write) writing = false;
        }
    }
    private async Task FinishDisposalAsync(Task[] admitted)
    {
        // Await actual tasks, not a finally-block signal that could precede their completion.
        try { await Task.WhenAll(admitted).ConfigureAwait(false); } catch { /* Operations expose their own sanitized failures. */ }
        lock (gate) stage = TcpTransportStage.Disposed;
        if (cleanupFailed) throw new TcpTransportException(TcpTransportEnd.CleanupFailed);
    }
}
