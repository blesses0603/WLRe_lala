namespace Lala.Core.Resources;

/// <summary>A successful full source-derived read may avoid rewriting a cache.
/// Cancellation, source changes and cleanup failures are never repair requests.</summary>
internal static class VerifiedCacheReuse
{
    internal static async Task<T?> TryReadAsync<T>(string path,Func<Task<T>> read,CancellationToken token) where T:class
    {
        token.ThrowIfCancellationRequested();
        if(!File.Exists(path))return null;
        try{return await read().ConfigureAwait(false);}
        catch(Exception error) when((error is UnityTextAssetException or SpritePixelException or InvalidDataException)&&
            !error.Data.Contains(ResourceInventoryDatabase.CleanupKey)&&!error.Data.Contains(ResourceCleanup.FailureMarker))
        {token.ThrowIfCancellationRequested();return null;}
    }
}
