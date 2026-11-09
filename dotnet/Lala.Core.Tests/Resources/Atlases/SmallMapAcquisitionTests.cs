using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class SmallMapAcquisitionTests:IDisposable
{
    private readonly string root=Path.Combine(Path.GetTempPath(),"lala-map-acquire-"+Guid.NewGuid());
    public void Dispose(){if(Directory.Exists(root))Directory.Delete(root,true);}
    private sealed class Body(byte[] bytes,Action disposed):MemoryStream(bytes,false)
    {protected override void Dispose(bool disposing){base.Dispose(disposing);if(disposing)disposed();}}
    private sealed class Source(byte[] bytes):IResourceSource,IBundleStreamSource
    {
        internal int Requests,Disposals;internal string? Length;internal bool WrongUrl;internal Action? Opened;
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)=>throw new InvalidOperationException("not an acquisition operation");
        public ValueTask<ResourceResponse> OpenAsync(string url,CancellationToken token)=>throw new InvalidOperationException("legacy route forbidden");
        public ValueTask<ResourceResponse> OpenBundleStreamAsync(BundleSourceSpec spec,CancellationToken token)
        {Requests++;Opened?.Invoke();return ValueTask.FromResult(new ResourceResponse(WrongUrl?"https://invalid.example/":spec.Url(OfficialResourceOrigin.DefaultHost),200,Length??bytes.Length.ToString(System.Globalization.CultureInfo.InvariantCulture),new Body(bytes,()=>Disposals++)));}
    }
    [Fact]
    public async Task Missing_cache_read_only_has_no_network_or_disk_side_effects()
    {
        var f=SmallMapReceiptTests.Fixture();var source=new Source(f.Bytes);
        Assert.Null(await new SmallMapSourceAcquisition().AcquireAsync(f.Manifest,"1.3.23",source,new RuntimeBundleCacheReader(root),new(root),false,()=>{}));
        Assert.Equal(0,source.Requests);Assert.False(Directory.Exists(root));
    }
    [Fact]
    public async Task Download_is_verified_reopened_then_reused_without_network_and_acquisition_is_single_use()
    {
        var f=SmallMapReceiptTests.Fixture();var source=new Source(f.Bytes);var cache=new RuntimeBundleCacheReader(root);var acquire=new SmallMapSourceAcquisition();
        var first=await acquire.AcquireAsync(f.Manifest,"1.3.23",source,cache,new(root),true,()=>{});Assert.NotNull(first);
        await using var batch=first.Batch;Assert.Equal(1,first.DownloadCount);Assert.Equal(f.Bytes.Length,first.DownloadBytes);Assert.Equal(1,source.Disposals);
        Assert.Equal(10001,(await batch.RebuildAsync(10001)).Model);
        await Assert.ThrowsAsync<InvalidOperationException>(()=>acquire.AcquireAsync(f.Manifest,"1.3.23",source,cache,new(root),true,()=>{}));
        var second=await new SmallMapSourceAcquisition().AcquireAsync(f.Manifest,"1.3.23",source,cache,new(root),false,()=>{});Assert.NotNull(second);
        await using var reused=second.Batch;Assert.Equal(0,second.DownloadCount);Assert.Equal(0,second.DownloadBytes);Assert.Equal(1,source.Requests);
    }
    [Theory][InlineData("source")][InlineData("length")][InlineData("checksum")][InlineData("stale")][InlineData("cancel")]
    public async Task Invalid_or_late_response_is_disposed_without_a_receipt_or_partial_file(string mode)
    {
        var f=SmallMapReceiptTests.Fixture();using var stop=new CancellationTokenSource();bool current=true;
        var bytes=f.Bytes.ToArray();if(mode=="checksum")bytes[^1]^=1;
        var source=new Source(bytes){WrongUrl=mode=="source",Length=mode=="length"?"1":null,Opened=()=>{if(mode=="stale")current=false;if(mode=="cancel")stop.Cancel();}};
        var error=await Record.ExceptionAsync(()=>new SmallMapSourceAcquisition().AcquireAsync(f.Manifest,"1.3.23",source,new RuntimeBundleCacheReader(root),new(root),true,()=>{if(!current)throw new InvalidOperationException("revoked");},token:stop.Token));
        Assert.NotNull(error);Assert.Equal(1,source.Disposals);
        if(Directory.Exists(root))Assert.Empty(Directory.GetFiles(root,"*",SearchOption.AllDirectories));
    }
}
