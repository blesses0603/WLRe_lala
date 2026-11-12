using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class BundleReceiptReadTests
{
    private static BundleStreamReceipt Receipt(byte[] bytes,string? name=null)
    {
        var i=BundleSourceFixtures.Index("main-valid");var b=i["bundles"]![0]!;
        if(name is not null)b["name"]=name;
        b["file_size"]=(long)bytes.Length;b["file_hash"]=Convert.ToHexStringLower(MD5.HashData(bytes));b["file_crc"]=ManifestIdentity.Crc32LittleEndian(bytes);
        var m=YooAssetManifest.Parse(BundleSourceFixtures.Encode(i));return new(new("1.3.23",m,m.Bundles[0]),Convert.ToHexStringLower(SHA256.HashData(bytes)));
    }
    private sealed class Cache(byte[] data):IBundleSourceCacheReader
    {
        internal int Active,Peak,Opens;internal Observed? Last;
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec,CancellationToken token)
        {token.ThrowIfCancellationRequested();Opens++;Active++;Peak=Math.Max(Peak,Active);return ValueTask.FromResult<Stream?>(Last=new(data,()=>Active--));}
    }
    private sealed class Observed(byte[] data,Action close):MemoryStream(data)
    {
        internal long Bytes;internal int Maximum;internal bool Hold;private bool closed;
        internal TaskCompletionSource Entered=new(TaskCreationOptions.RunContinuationsAsynchronously),Release=new(TaskCreationOptions.RunContinuationsAsynchronously);
        public override async ValueTask<int> ReadAsync(Memory<byte> b,CancellationToken t=default)
        {Maximum=Math.Max(Maximum,b.Length);if(Hold){Entered.TrySetResult();await Release.Task;}int n=await base.ReadAsync(b,t);Bytes+=n;return n;}
        protected override void Dispose(bool disposing){if(!closed){closed=true;close();}base.Dispose(disposing);}
    }
    [Theory][InlineData(null)][InlineData("")][InlineData("not-a-digest")]
    public async Task Malformed_receipt_digest_cannot_disable_sha_validation(string? digest)
    {
        byte[] bytes=[1,2,3];var cache=new Cache(bytes);var receipt=Receipt(bytes) with{Sha256=digest!};
        await Assert.ThrowsAsync<BundleSourceException>(()=>VerifiedBundleBlockSource.OpenAsync(cache,receipt));Assert.Equal(0,cache.Opens);
    }
    [Fact]
    public async Task Reads_hash_complete_covering_blocks_and_rejects_mutation_outside_requested_slice()
    {
        var data=Enumerable.Range(0,200000).Select(i=>(byte)(i*37)).ToArray();var cache=new Cache(data);
        await using var source=await VerifiedBundleBlockSource.OpenAsync(cache,Receipt(data));
        Assert.Equal(data.Length,cache.Last!.Bytes);Assert.InRange(cache.Last.Maximum,1,65536);
        Assert.Equal(data[65530..65550],await source.ReadRangeAsync(65530,20));
        Assert.Equal(data.Length+131072,cache.Last.Bytes);
        data[60000]^=1;
        Assert.Equal(BundleSourceFailure.Checksum,(await Assert.ThrowsAsync<BundleSourceException>(()=>source.ReadRangeAsync(1,1))).Failure);
    }
    [Fact]
    public async Task Receipt_sha_is_rechecked_and_failed_open_releases_handle()
    {
        byte[] data=[1,2,3];var receipt=Receipt(data);var cache=new Cache(data);data[1]^=1;
        await Assert.ThrowsAsync<BundleSourceException>(()=>VerifiedBundleBlockSource.OpenAsync(cache,receipt));Assert.Equal(0,cache.Active);
        data[1]^=1;
        await Assert.ThrowsAsync<BundleSourceException>(()=>VerifiedBundleBlockSource.OpenAsync(cache,receipt with{Sha256=new string('0',64)}));Assert.Equal(0,cache.Active);
    }
    [Fact]
    public async Task Closing_waits_for_inflight_read_and_rejects_late_result()
    {
        byte[] data=[1,2,3];var cache=new Cache(data);var source=await VerifiedBundleBlockSource.OpenAsync(cache,Receipt(data));
        cache.Last!.Hold=true;var read=source.ReadRangeAsync(0,1);
        await cache.Last.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));var close=source.DisposeAsync().AsTask();Assert.False(close.IsCompleted);
        cache.Last.Release.TrySetResult();await Assert.ThrowsAsync<ObjectDisposedException>(()=>read);await close;Assert.Equal(0,cache.Active);
        await Assert.ThrowsAsync<ObjectDisposedException>(()=>source.ReadRangeAsync(0,1));
    }
    [Fact]
    public async Task Phase_rechecks_after_consumer_and_serializes_cancelled_waiter()
    {
        byte[] data=[1,2,3];var receipt=Receipt(data);var cache=new Cache(data);await using var phase=new BundleReceiptPhase(cache,[receipt]);
        var entered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);var release=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var running=phase.ReadAsync(receipt.Spec.Package,receipt.Spec.Name,async(s,t)=>{entered.SetResult();await release.Task;return await s.ReadRangeAsync(0,1,t);});
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));using var stop=new CancellationTokenSource();
        var queued=phase.ReadAsync(receipt.Spec.Package,receipt.Spec.Name,(s,t)=>s.ReadRangeAsync(0,1,t),stop.Token);stop.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>queued);Assert.Equal(2,cache.Opens);release.SetResult();Assert.Equal(new byte[]{1},await running);
        Assert.Equal(3,cache.Opens);Assert.Equal(1,cache.Peak);Assert.Equal(0,cache.Active);
        await Assert.ThrowsAsync<BundleSourceException>(()=>phase.ReadAsync(receipt.Spec.Package,receipt.Spec.Name,(s,t)=>{data[2]^=1;return Task.FromResult(1);}));Assert.Equal(0,cache.Active);
    }
    [Fact]
    public async Task Phase_close_waits_for_consumer_and_cannot_publish_late_result()
    {
        byte[] data=[1,2,3];var receipt=Receipt(data);var cache=new Cache(data);var phase=new BundleReceiptPhase(cache,[receipt]);
        var entered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);var release=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var running=phase.ReadAsync(receipt.Spec.Package,receipt.Spec.Name,async(s,t)=>{entered.SetResult();await release.Task;return 7;});
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));var close=phase.DisposeAsync().AsTask();Assert.False(close.IsCompleted);release.SetResult();
        await Assert.ThrowsAsync<ObjectDisposedException>(()=>running);await close;Assert.Equal(0,cache.Active);
    }
    [Fact]
    public async Task Duplicate_receipts_and_unknown_selection_are_rejected_without_io()
    {
        byte[] data=[1,2,3];var receipt=Receipt(data);var cache=new Cache(data);
        Assert.Throws<BundleSourceException>(()=>new BundleReceiptPhase(cache,[receipt,receipt]));
        await using var phase=new BundleReceiptPhase(cache,[receipt]);
        await Assert.ThrowsAsync<BundleSourceException>(()=>phase.ReadAsync("wrong",receipt.Spec.Name,(s,t)=>Task.FromResult(1)));Assert.Equal(0,cache.Opens);
    }
    private sealed class MultipleCache(Dictionary<string,byte[]> files):IBundleSourceCacheReader
    {
        internal int Active,Peak;
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec,CancellationToken token)
        {token.ThrowIfCancellationRequested();Active++;Peak=Math.Max(Peak,Active);return ValueTask.FromResult<Stream?>(new Observed(files[spec.Name],()=>Active--));}
    }
    [Fact]
    public async Task Phase_rechecks_unselected_dependency_before_and_after_consumption()
    {
        byte[] a=[1,2,3],b=[4,5,6];var first=Receipt(a,"first.bundle");var second=Receipt(b,"second.bundle");
        var cache=new MultipleCache(new(){{first.Spec.Name,a},{second.Spec.Name,b}});await using var phase=new BundleReceiptPhase(cache,[first,second]);
        bool consumed=false;b[0]^=1;
        await Assert.ThrowsAsync<BundleSourceException>(()=>phase.ReadAsync(first.Spec.Package,first.Spec.Name,(s,t)=>{consumed=true;return Task.FromResult(1);}));Assert.False(consumed);
        b[0]^=1;
        await Assert.ThrowsAsync<BundleSourceException>(()=>phase.ReadAsync(first.Spec.Package,first.Spec.Name,(s,t)=>{b[0]^=1;return Task.FromResult(1);}));
        Assert.Equal(1,cache.Peak);Assert.Equal(0,cache.Active);
    }
    private static byte[] Fixture(string name,int index=0)
    {
        using var d=JsonDocument.Parse(typeof(BundleReceiptReadTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.streams.json")!);
        return Convert.FromBase64String((name=="cases"?d.RootElement.GetProperty(name)[index].GetProperty("bytes"):d.RootElement.GetProperty(name)).GetString()!);
    }
    [Theory][InlineData(0)][InlineData(1)][InlineData(2)]
    public async Task Indexed_archive_matches_independent_resource_bytes(int index)
    {
        var bytes=Fixture("cases",index);var cache=new Cache(bytes);await using var source=await VerifiedBundleBlockSource.OpenAsync(cache,Receipt(bytes));var archive=await StreamedUnityArchive.CreateAsync(source);
        Assert.Equal(Enumerable.Range(250,20).Select(i=>(byte)i).ToArray(),await archive.ReadAsync("CAB-owned.resS",250,20));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>archive.ReadAsync("../CAB-owned.resS",0,1));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>archive.ReadAsync("CAB-owned.resS",long.MaxValue,1));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>archive.ReadAsync("CAB-owned.resS",0,1,new(true)));
    }
    [Fact]
    public async Task Large_virtual_archive_reads_only_intersecting_blocks()
    {
        var bytes=Fixture("over");var cache=new Cache(bytes);await using var source=await VerifiedBundleBlockSource.OpenAsync(cache,Receipt(bytes));var archive=await StreamedUnityArchive.CreateAsync(source);
        Assert.True(archive.LogicalBytes>96L*1024*1024);long before=cache.Last!.Bytes;
        Assert.Equal(new byte[20],await archive.ReadAsync("CAB-owned.resS",96L*1024*1024-20,20));
        Assert.InRange(cache.Last.Bytes-before,1,131072);Assert.InRange(cache.Last.Maximum,1,65536);
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>archive.ReadAsync("CAB-owned.resS",0,16*1024*1024+1));
    }
    [Theory][InlineData("unpaired")][InlineData("flags")]
    public async Task Invalid_directory_is_rejected(string name)
    {
        var bytes=Fixture(name);var cache=new Cache(bytes);await using var source=await VerifiedBundleBlockSource.OpenAsync(cache,Receipt(bytes));await Assert.ThrowsAsync<UnityTextAssetException>(()=>StreamedUnityArchive.CreateAsync(source));
    }
}
