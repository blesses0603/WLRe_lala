using Lala.Core.Sessions.Receive;
using Lala.Core.State;

namespace Lala.Core.Sessions;

public sealed partial class AccountSession
{
    private ReceiveAttempt? receive;
    private Task? receiveCleanup;

    /// <summary>
    /// Internal receive-only integration. Accepts an already-created transport; does not dial,
    /// authenticate or admit resources. On success ownership transfers to the returned attempt,
    /// which the caller must run and await/dispose. On rejection ownership stays with the caller.
    /// Only a fresh Preparing generation can attach. It is immediately and permanently Held.
    /// Replacement cannot attach until old cleanup succeeds, even across Begin/Disconnect.
    /// No callback is exposed: consumers must validate generation and attempt when reading.
    /// </summary>
    internal ReceiveAttempt? AttachHeldReceive(long generation, IReceiveTransport transport, int rxXor,
        Func<double> clock, Func<ServiceStateSnapshot, double, ServiceObservationInputs> observe,
        int readSize = 4096, int bufferedChunks = 4)
    {
        lock (gate)
        {
            if (current.Generation != generation || current.Phase != SessionPhase.Preparing ||
                receive is not null || receiveCleanup is { IsCompletedSuccessfully: false }) return null;
            // Validate construction before changing the session or accepting ownership.
            var next = new ReceiveAttempt(transport, rxXor, clock, observe,
                readSize: readSize, bufferedChunks: bufferedChunks);
            receive = next;
            current = current with { Phase = SessionPhase.Held, ResourceVersion = null };
            return next;
        }
    }

    /// <summary>A coherent pull publication, never proof of login or permission to send.</summary>
    internal ReceivePublication? ReadHeldReceive(long generation, Guid attempt)
    {
        lock (gate)
        {
            if (generation != current.Generation || current.Phase != SessionPhase.Held ||
                receive is null) return null;
            var publication = receive.Latest;
            return publication.Attempt == attempt ? publication : null;
        }
    }

    private void RetireReceiveLocked()
    {
        if (receive is null) return;
        // Dispose retires synchronously; cancellation, transport and observers run outside
        // its lock. Completion is retained so failed or pending cleanup blocks replacement.
        receiveCleanup = receive.DisposeAsync().AsTask();
        receive = null;
        _ = receiveCleanup.ContinueWith(static task => { _ = task.Exception; },
            CancellationToken.None, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }
}
