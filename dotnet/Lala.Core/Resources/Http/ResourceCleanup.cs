namespace Lala.Core.Resources;

/// <summary>Only used around scopes we control. Arbitrary caller using scopes cannot preserve
/// their own pending exceptions automatically when Dispose reports an incomplete cleanup.</summary>
internal static class ResourceCleanup
{
    internal const string FailureMarker = "resource_cleanup_failure";
    internal static void Report(bool failed, Exception? primary = null)
    {
        if (!failed) return;
        if (primary is null) throw new ResourceTransportException(ResourceTransportFailure.Cleanup);
        primary.Data[FailureMarker] = "Cleanup";
    }
    internal static void DisposePreservingFailure(IDisposable resource, Exception? primary)
    {
        try { resource.Dispose(); }
        catch (Exception) { Report(true, primary); }
    }
}
