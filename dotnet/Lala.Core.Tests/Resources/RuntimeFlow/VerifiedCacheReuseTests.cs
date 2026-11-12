using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class VerifiedCacheReuseTests:IDisposable
{
    private readonly string path=Path.Combine(Path.GetTempPath(),"lala-reuse-"+Guid.NewGuid()+".cache");
    public void Dispose()=>File.Delete(path);
    [Fact]
    public async Task Missing_or_mismatched_cache_can_be_rebuilt_but_only_successful_full_read_is_reused()
    {
        int reads=0;var expected=new object();
        Assert.Null(await VerifiedCacheReuse.TryReadAsync(path,()=>{reads++;return Task.FromResult(expected);},default));Assert.Equal(0,reads);
        await File.WriteAllTextAsync(path,"owned fixture");
        Assert.Same(expected,await VerifiedCacheReuse.TryReadAsync(path,()=>{reads++;return Task.FromResult(expected);},default));Assert.Equal(1,reads);
        Assert.Null(await VerifiedCacheReuse.TryReadAsync<object>(path,()=>throw new UnityTextAssetException("cache mismatch"),default));
        Assert.Null(await VerifiedCacheReuse.TryReadAsync<object>(path,()=>throw new InvalidDataException("cache mismatch"),default));
        Assert.Equal("owned fixture",await File.ReadAllTextAsync(path));
    }
    [Fact]
    public async Task Cancellation_source_changes_cleanup_and_io_failures_never_become_silent_rebuilds()
    {
        await File.WriteAllTextAsync(path,"owned fixture");
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>VerifiedCacheReuse.TryReadAsync<object>(path,()=>throw new OperationCanceledException(),default));
        await Assert.ThrowsAsync<IOException>(()=>VerifiedCacheReuse.TryReadAsync<object>(path,()=>throw new IOException(),default));
        await Assert.ThrowsAsync<BundleSourceException>(()=>VerifiedCacheReuse.TryReadAsync<object>(path,()=>throw new BundleSourceException(BundleSourceFailure.CacheChanged,"changed"),default));
        var error=new InvalidDataException("cleanup incomplete");error.Data[ResourceInventoryDatabase.CleanupKey]=new[]{new IOException()};
        Assert.Same(error,await Assert.ThrowsAsync<InvalidDataException>(()=>VerifiedCacheReuse.TryReadAsync<object>(path,()=>throw error,default)));
        int reads=0;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>VerifiedCacheReuse.TryReadAsync(path,()=>{reads++;return Task.FromResult(new object());},new(true)));
        Assert.Equal(0,reads);
    }
}
