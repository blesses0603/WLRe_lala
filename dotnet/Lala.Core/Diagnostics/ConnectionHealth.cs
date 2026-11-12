using System.Diagnostics;

namespace Lala.Core.Diagnostics;

public enum ConnectionEvidenceStatus { Waiting, Receiving, Quiet, Closed }
public enum ConnectionCloseReason { ServerClosed, NetworkError, ClientError, Stopped, Duration }

public sealed record ConnectionEvidence(ConnectionEvidenceStatus Status, double AgeSeconds,
    DateTimeOffset? LastReceivedAtUtc, long Packets, bool Keepalive, ConnectionCloseReason? Reason)
{
    public string Type => "connection_health";
    public string StatusName => Status switch
    {
        ConnectionEvidenceStatus.Waiting => "waiting",
        ConnectionEvidenceStatus.Receiving => "receiving",
        ConnectionEvidenceStatus.Quiet => "quiet",
        ConnectionEvidenceStatus.Closed => "closed",
        _ => throw new InvalidOperationException("Unknown evidence status")
    };
}

/// <summary>
/// Pure, single-owner transport evidence. Quiet is uncertainty, never proof of logout.
/// No sockets, automatic reconnection, account/session mutation, error payloads or credentials.
/// </summary>
public sealed class ConnectionHealth
{
    public const double DefaultQuietAfterSeconds = 120;
    public const double DefaultIntervalSeconds = 1;
    private readonly Action<ConnectionEvidence> emit;
    private readonly Func<double> monotonicSeconds;
    private readonly Func<DateTimeOffset> utcWall;
    private readonly double started;
    private readonly double quietAfter;
    private readonly double interval;
    private double? lastPacket;
    private double? lastEmit;
    private DateTimeOffset? lastReceivedAt;
    public long Packets { get; private set; }
    public bool Keepalive { get; set; }
    public bool Closed { get; private set; }

    public ConnectionHealth(Action<ConnectionEvidence> emit,
        Func<double>? monotonicSeconds = null, Func<DateTimeOffset>? utcWall = null,
        double quietAfterSeconds = DefaultQuietAfterSeconds, double intervalSeconds = DefaultIntervalSeconds)
    {
        ArgumentNullException.ThrowIfNull(emit);
        if (!double.IsFinite(quietAfterSeconds) || quietAfterSeconds < 0)
            throw new ArgumentOutOfRangeException(nameof(quietAfterSeconds));
        if (!double.IsFinite(intervalSeconds) || intervalSeconds < 0)
            throw new ArgumentOutOfRangeException(nameof(intervalSeconds));
        this.emit = emit;
        this.monotonicSeconds = monotonicSeconds ?? (() => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency);
        this.utcWall = utcWall ?? (() => DateTimeOffset.UtcNow);
        quietAfter = quietAfterSeconds; interval = intervalSeconds;
        started = ReadMonotonic();
    }

    public void Received()
    {
        lastPacket = ReadMonotonic();
        lastReceivedAt = utcWall().ToUniversalTime();
        Packets = checked(Packets + 1);
    }

    /// <returns>False when the unchanged interval gate suppresses emission.</returns>
    public bool Publish(bool force = false, ConnectionCloseReason? reason = null)
    {
        double now = ReadMonotonic();
        if (!force && lastEmit.HasValue && now - lastEmit.Value < interval) return false;
        lastEmit = now;
        double age = Math.Max(0, now - (lastPacket ?? started));
        var status = Closed ? ConnectionEvidenceStatus.Closed
            : age >= quietAfter ? ConnectionEvidenceStatus.Quiet
            : lastPacket.HasValue ? ConnectionEvidenceStatus.Receiving : ConnectionEvidenceStatus.Waiting;
        emit(new(status, age, lastReceivedAt, Packets, Keepalive, reason));
        return true;
    }

    /// <summary>Call only for observed transport closure or an explicit owner stop, not silence.</summary>
    public void Close(ConnectionCloseReason reason)
    {
        Closed = true;
        Publish(force: true, reason: reason);
    }

    private double ReadMonotonic()
    {
        double now = monotonicSeconds();
        if (!double.IsFinite(now)) throw new InvalidOperationException("Monotonic clock returned a non-finite value");
        return now;
    }
}
