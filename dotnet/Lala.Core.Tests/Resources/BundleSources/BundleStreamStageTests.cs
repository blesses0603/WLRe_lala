using System.Security.Cryptography;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class BundleStreamStageTests:IDisposable
{
    private readonly string root=Path.Combine(Path.GetTempPath(),"lala-stream-"+Guid.NewGuid().ToString("N"));
    public void Dispose(){if(Directory.Exists(root))Directory.Delete(root,true);}
    private static BundleSourceSpec Spec(long size,string md5,string crc)
    {
        var i=BundleSourceFixtures.Index("main-valid");var b=i["bundles"]![0]!;
        b["file_size"]=size;b["file_hash"]=md5;b["file_crc"]=crc;
        var m=YooAssetManifest.Parse(BundleSourceFixtures.Encode(i));return new("1.3.23",m,m.Bundles[0]);
    }
    private static BundleSourceSpec Spec(byte[] data)=>Spec(data.Length,Convert.ToHexStringLower(MD5.HashData(data)),ManifestIdentity.Crc32LittleEndian(data));
    private string Destination(BundleSourceSpec s)=>Path.Combine(root,"official_sync","bundles",s.Package,s.PackageVersion,s.Md5,s.Name);
    private static byte[] Owned=>Enumerable.Range(0,200000).Select(i=>(byte)(i*37)).ToArray();
    private sealed class ZeroStream(long length):Stream
    {
        private long consumed;internal int MaximumRequested;internal bool Closed;
        public override bool CanRead=>true;public override bool CanSeek=>false;public override bool CanWrite=>false;
        public override long Length=>throw new NotSupportedException();public override long Position{get=>throw new NotSupportedException();set=>throw new NotSupportedException();}
        public override ValueTask<int> ReadAsync(Memory<byte> b,CancellationToken t=default)
        {t.ThrowIfCancellationRequested();MaximumRequested=Math.Max(MaximumRequested,b.Length);int n=(int)Math.Min(b.Length,length-consumed);b.Span[..n].Clear();consumed+=n;return ValueTask.FromResult(n);}
        public override int Read(byte[] b,int o,int c)=>throw new NotSupportedException();public override void Flush()=>throw new NotSupportedException();
        public override long Seek(long o,SeekOrigin s)=>throw new NotSupportedException();public override void SetLength(long v)=>throw new NotSupportedException();public override void Write(byte[] b,int o,int c)=>throw new NotSupportedException();
        protected override void Dispose(bool d){Closed=true;base.Dispose(d);}
    }
    [Fact]
    public async Task Large_owned_zero_stream_uses_bounded_reads_and_independent_Python_digests()
    {
        // Owned zeros at the observed smallmap compressed size, NOT official bytes.
        var s=Spec(43187027,"91af61388a40636feebd02d6bba45131","83e54ea9");using var input=new ZeroStream(s.Size);
        var receipt=await new RuntimeBundleCacheWriter(root).StoreStreamAsync(s,input);
        Assert.Equal("b7fe8b0896ac3f9f7c3bcdb0f6dd57ac568e92541ac36333ffafbd0a2c2aa50f",receipt.Sha256);
        Assert.Equal(s,receipt.Spec);Assert.InRange(input.MaximumRequested,1,65536);Assert.False(input.Closed);
        Assert.Equal(s.Size,new FileInfo(Destination(s)).Length);Assert.Empty(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));
        Assert.Equal(32L*1024*1024,BundleSourcePreparation.MaximumRetainedBytes);
        using var read=await new RuntimeBundleCacheReader(root).OpenReadAsync(s,default);
        Assert.Equal(receipt,await BundleStreamVerifier.VerifyAsync(s,read!,expectedSha256:receipt.Sha256));
    }
    [Theory][InlineData("short")][InlineData("long")][InlineData("checksum")]
    public async Task Invalid_stream_preserves_prior_file_and_removes_only_its_stage(string mode)
    {
        var data=Owned;var s=Spec(data);var writer=new RuntimeBundleCacheWriter(root);
        using(var input=new MemoryStream(data))await writer.StoreStreamAsync(s,input);
        byte[] invalid=mode=="short"?data[..^1]:mode=="long"?[..data,0]:data.ToArray();if(mode=="checksum")invalid[0]^=1;
        using var bad=new MemoryStream(invalid);
        var e=await Assert.ThrowsAsync<BundleSourceException>(()=>writer.StoreStreamAsync(s,bad));
        Assert.Equal(mode=="checksum"?BundleSourceFailure.Checksum:BundleSourceFailure.ResponseLength,e.Failure);
        Assert.Equal(data,File.ReadAllBytes(Destination(s)));Assert.Empty(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));
        Assert.True(bad.CanRead);
    }
    [Theory][InlineData((int)RuntimeBundleCacheWriteStage.TemporaryCreated)][InlineData((int)RuntimeBundleCacheWriteStage.BeforePublish)][InlineData((int)RuntimeBundleCacheWriteStage.BeforeMove)][InlineData((int)RuntimeBundleCacheWriteStage.Published)]
    public async Task Cancellation_drains_stage_but_never_undoes_completed_publish(int checkpoint)
    {
        var stage=(RuntimeBundleCacheWriteStage)checkpoint;
        var data=Owned;var s=Spec(data);using var stop=new CancellationTokenSource();using var input=new MemoryStream(data);
        var writer=new RuntimeBundleCacheWriter(root,at=>{if(at==stage)stop.Cancel();});
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>writer.StoreStreamAsync(s,input,stop.Token));
        Assert.Equal(stage==RuntimeBundleCacheWriteStage.Published,File.Exists(Destination(s)));
        if(File.Exists(Destination(s)))Assert.Equal(data,File.ReadAllBytes(Destination(s)));
        Assert.Empty(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));
    }
    [Fact]
    public async Task Oversize_and_initial_cancel_create_nothing_and_hash_claim_is_rechecked()
    {
        var data=Owned;var s=Spec(data);using var input=new MemoryStream(data);var writer=new RuntimeBundleCacheWriter(root);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>writer.StoreStreamAsync(s,input,new(true)));
        var huge=Spec(64L*1024*1024+1,s.Md5,s.Crc32Le);
        Assert.Equal(BundleSourceFailure.Budget,(await Assert.ThrowsAsync<BundleSourceException>(()=>writer.StoreStreamAsync(huge,input))).Failure);
        Assert.False(Directory.Exists(root));
        await Assert.ThrowsAsync<BundleSourceException>(()=>BundleStreamVerifier.VerifyAsync(s,input,expectedSha256:new string('a',64)));
    }
    [Fact]
    public async Task Mutated_staged_bytes_never_replace_a_valid_entry()
    {
        var data=Owned;var s=Spec(data);var writer=new RuntimeBundleCacheWriter(root,at=>
        {if(at==RuntimeBundleCacheWriteStage.BeforePublish){var file=Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories).Single();var b=File.ReadAllBytes(file);b[0]^=1;File.WriteAllBytes(file,b);}});
        using var input=new MemoryStream(data);
        await Assert.ThrowsAsync<InvalidDataException>(()=>writer.StoreStreamAsync(s,input));
        Assert.False(File.Exists(Destination(s)));Assert.Empty(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));
    }
    private sealed class HeldStream(byte[] data):MemoryStream(data)
    {
        internal readonly TaskCompletionSource Entered=new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly TaskCompletionSource Release=new(TaskCreationOptions.RunContinuationsAsynchronously);
        private bool first=true;
        public override async ValueTask<int> ReadAsync(Memory<byte> b,CancellationToken t=default)
        {if(first){first=false;Entered.TrySetResult();await Release.Task;}return await base.ReadAsync(b,t);}
    }
    [Fact]
    public async Task Same_writer_serializes_stages_and_queued_cancel_does_not_read_or_publish()
    {
        var data=Owned;var s=Spec(data);using var first=new HeldStream(data);using var second=new MemoryStream(data);
        var writer=new RuntimeBundleCacheWriter(root);var running=writer.StoreStreamAsync(s,first);
        try
        {
            await first.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10));using var stop=new CancellationTokenSource();
            var queued=writer.StoreStreamAsync(s,second,stop.Token);Assert.False(queued.IsCompleted);Assert.Equal(0,second.Position);
            stop.Cancel();await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>queued);
            Assert.Single(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));Assert.False(File.Exists(Destination(s)));
        }
        finally{first.Release.TrySetResult();await running;}
        Assert.Equal(data,File.ReadAllBytes(Destination(s)));Assert.Empty(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));
    }
    [Fact]
    public async Task Independent_cooperative_writers_publish_same_bytes_without_partial_files()
    {
        var data=Owned;var s=Spec(data);using var a=new MemoryStream(data);using var b=new MemoryStream(data);
        var results=await Task.WhenAll(new RuntimeBundleCacheWriter(root).StoreStreamAsync(s,a),new RuntimeBundleCacheWriter(root).StoreStreamAsync(s,b));
        Assert.Equal(results[0],results[1]);Assert.Equal(data,File.ReadAllBytes(Destination(s)));
        Assert.Empty(Directory.GetFiles(root,"*.partial",SearchOption.AllDirectories));
    }

}
