using Lala.Core.Sessions;

namespace Lala.Cloud.Acceptance;

// Private adapters keep one timing, polling, classification and cleanup policy. Neither
// accepts injected resources, claimed integrity, or test sources on the production route.
internal interface IAcceptanceRuntime : IAsyncDisposable
{
    AccountConnectionStatus Snapshot { get; }
    AccountReceivePublication? Publication { get; }
    bool ResourcesReleased { get; }
    Task<AccountConnectionResult> RunAsync();
    void Stop();
    ResourceEvidence ObserveResources(ResourceEvidence previous);
}

internal sealed class ConnectionAcceptanceRuntime(AccountConnectionRuntime runtime) : IAcceptanceRuntime
{
    public AccountConnectionStatus Snapshot => runtime.Snapshot;
    public AccountReceivePublication? Publication => runtime.Publication;
    public bool ResourcesReleased => true; // Connection cleanup is checked independently.
    public Task<AccountConnectionResult> RunAsync() => runtime.RunAsync();
    public void Stop() => runtime.Stop();
    public ValueTask DisposeAsync() => runtime.DisposeAsync();
    public ResourceEvidence ObserveResources(ResourceEvidence previous) => previous;
}

internal sealed class IntegratedAcceptanceRuntime(AccountRuntime runtime) : IAcceptanceRuntime
{
    private bool released;
    public AccountConnectionStatus Snapshot => runtime.Snapshot.Connection;
    public AccountReceivePublication? Publication => runtime.Publication?.Receive;
    public bool ResourcesReleased => released;
    public async Task<AccountConnectionResult> RunAsync()
    {
        var result = await runtime.RunAsync().ConfigureAwait(false);
        released = result.ResourcesReleased;
        return result.Connection;
    }
    public void Stop() => runtime.Stop();
    public ValueTask DisposeAsync() => runtime.DisposeAsync();
    public ResourceEvidence ObserveResources(ResourceEvidence previous)
    {
        var snapshot = runtime.Snapshot;
        var last = snapshot.ResourceHistory.IsEmpty ? null : snapshot.ResourceHistory[^1].Preparation;
        return new(snapshot.HasCurrentResources ? ResourceObservation.CurrentReadinessObserved : previous.Observation,
            snapshot.ResourceHistory.Length, last?.Status, last?.StorageOutcome,
            last?.ReadbackMatched ?? false, last?.SourcesRechecked ?? false);
    }
}
