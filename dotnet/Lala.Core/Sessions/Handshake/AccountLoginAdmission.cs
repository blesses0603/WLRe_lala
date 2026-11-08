using System.Net;

namespace Lala.Core.Sessions.Handshake;

/// <summary>Private composition guard, never a public claim of consent. Lock order is
/// session -> admission -> login transport -> TCP. Actions passed here are Core-owned
/// synchronous transport admission only, never host input or observers.</summary>
internal sealed class AccountLoginAdmission(AccountSession session, SessionSnapshot expected,
    AccountConnectionProfile profile, TimeSpan validity, TimeProvider clock)
{
    private readonly object gate = new();
    private readonly long created = clock.GetTimestamp();
    private SessionSnapshot expected = expected;
    private CancellationToken cancellation;
    private bool revoked;
    private int nextLeg;
    internal void SetCancellation(CancellationToken token) { lock (gate) cancellation = token; }
    internal void Revoke() { lock (gate) revoked = true; }
    internal TimeSpan? UntilExpiry
    {
        get
        {
            lock (gate) return revoked || nextLeg == 2 ? null
                : TimeSpan.FromTicks(Math.Max(0, (validity - clock.GetElapsedTime(created)).Ticks));
        }
    }
    // The final credential write is already admitted; a timer cannot unsend it and must
    // not become an arbitrary timeout on the subsequent receive-only session.
    internal bool Expire()
    {
        lock (gate)
        {
            if (nextLeg == 2 || revoked || clock.GetElapsedTime(created) < validity) return false;
            revoked = true; return true;
        }
    }
    internal bool IsCurrent => session.WithLoginSnapshot(snapshot =>
    {
        lock (gate) return Valid(snapshot);
    });
    private bool Valid(SessionSnapshot snapshot) => !revoked && !cancellation.IsCancellationRequested &&
        ReferenceEquals(snapshot, expected) && (nextLeg == 2 || clock.GetElapsedTime(created) < validity);
    internal void Check(CancellationToken token) => session.WithLoginSnapshot(snapshot =>
    {
        lock (gate)
        {
            token.ThrowIfCancellationRequested();
            if (!Valid(snapshot)) throw new InvalidOperationException("Login preparation is unavailable.");
            return true;
        }
    });
    // Called only during the preparation's own receive attachment under the session lock.
    // Every other snapshot change, including another Hold at the same generation, revokes it.
    internal bool TryAttach(SessionSnapshot previous, SessionSnapshot next)
    {
        lock (gate)
        {
            if (!Valid(previous)) return false;
            expected = next; return true;
        }
    }
    internal T Admit<T>(HandshakeLeg leg, IPEndPoint endpoint, CancellationToken token, Func<T> operation)
        => session.WithLoginSnapshot(snapshot =>
        {
            lock (gate)
            {
                token.ThrowIfCancellationRequested();
                var target = leg == HandshakeLeg.Verification ? profile.VerificationEndpoint : profile.FormalEndpoint;
                if (!Valid(snapshot) || !endpoint.Equals(target) || (int)leg != nextLeg)
                    throw new InvalidOperationException("Login preparation is unavailable.");
                nextLeg++;
                return operation();
            }
        });
}
