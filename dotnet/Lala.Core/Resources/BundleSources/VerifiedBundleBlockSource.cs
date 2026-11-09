using System.Security.Cryptography;
namespace Lala.Core.Resources;

// One owned read handle, validated against the exact stage receipt. Every later
// read rechecks complete 64 KiB block hashes captured during that full validation.
internal sealed class VerifiedBundleBlockSource:IAsyncDisposable
{
    internal const int BlockBytes=64*1024,MaximumRangeBytes=16*1024*1024;
    internal BundleStreamReceipt Receipt {get;}
    private readonly Stream input;private readonly byte[][] hashes;
    private readonly SemaphoreSlim gate=new(1,1);private readonly object lifecycle=new();
    private Task? disposal;private int closed;
    private VerifiedBundleBlockSource(BundleStreamReceipt receipt,Stream input,byte[][] hashes)
    {Receipt=receipt;this.input=input;this.hashes=hashes;}
    internal static async Task<VerifiedBundleBlockSource> OpenAsync(IBundleSourceCacheReader cache,BundleStreamReceipt receipt,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(cache);ArgumentNullException.ThrowIfNull(receipt);token.ThrowIfCancellationRequested();
        var input=await cache.OpenReadAsync(receipt.Spec,token).ConfigureAwait(false)
            ??throw new BundleSourceException(BundleSourceFailure.CacheChanged,"Staged bundle is missing");
        try
        {
            if(!input.CanRead||!input.CanSeek||input.Position!=0||input.Length!=receipt.Spec.Size)
                throw new BundleSourceException(BundleSourceFailure.ResponseLength,"Staged handle is not an exact seekable source");
            using var capture=new CaptureStream(input);
            await BundleStreamVerifier.VerifyAsync(receipt.Spec,capture,expectedSha256:receipt.Sha256,token:token).ConfigureAwait(false);
            var hashes=capture.Finish();
            if(hashes.Length!=(receipt.Spec.Size+BlockBytes-1)/BlockBytes)throw new InvalidDataException("Incomplete staged block fingerprints");
            token.ThrowIfCancellationRequested();return new(receipt,input,hashes);
        }
        catch(Exception error){ResourceCleanup.DisposePreservingFailure(input,error);throw;}
    }
    internal void EnsureOpen(CancellationToken token=default)=>Check(token);
    private void Check(CancellationToken token)
    {token.ThrowIfCancellationRequested();ObjectDisposedException.ThrowIf(Volatile.Read(ref closed)!=0,this);}
    internal async Task<byte[]> ReadRangeAsync(long offset,int count,CancellationToken token=default)
    {
        Check(token);
        if(offset<0||count is <=0 or >MaximumRangeBytes||offset>Receipt.Spec.Size-count)
            throw new BundleSourceException(BundleSourceFailure.Budget,"Staged range exceeds exact source or range bound");
        await gate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            Check(token);if(input.Length!=Receipt.Spec.Size)throw new BundleSourceException(BundleSourceFailure.CacheChanged,"Staged source length changed");
            var result=new byte[count];var block=new byte[BlockBytes];long end=offset+count;
            int first=(int)(offset/BlockBytes),last=(int)((end-1)/BlockBytes);
            for(int index=first;index<=last;index++)
            {
                Check(token);long start=(long)index*BlockBytes;int length=(int)Math.Min(BlockBytes,Receipt.Spec.Size-start);
                input.Position=start;int read=0;
                while(read<length)
                {int n=await input.ReadAsync(block.AsMemory(read,length-read),token).ConfigureAwait(false);Check(token);if(n<=0||n>length-read)throw new BundleSourceException(BundleSourceFailure.ResponseLength,"Truncated staged block");read+=n;}
                if(!SHA256.HashData(block.AsSpan(0,length)).AsSpan().SequenceEqual(hashes[index]))
                    throw new BundleSourceException(BundleSourceFailure.Checksum,"Staged block changed since receipt validation");
                long from=Math.Max(start,offset),to=Math.Min(start+length,end);
                block.AsSpan((int)(from-start),(int)(to-from)).CopyTo(result.AsSpan((int)(from-offset)));
            }
            Check(token);if(input.Length!=Receipt.Spec.Size)throw new BundleSourceException(BundleSourceFailure.CacheChanged,"Staged source changed during range read");
            return result;
        }
        finally{gate.Release();}
    }
    public ValueTask DisposeAsync()
    {lock(lifecycle){Volatile.Write(ref closed,1);return new(disposal??=DisposeCoreAsync());}}
    private async Task DisposeCoreAsync()
    {await gate.WaitAsync().ConfigureAwait(false);try{await input.DisposeAsync().ConfigureAwait(false);}finally{gate.Release();}}
    private sealed class CaptureStream(Stream source):Stream
    {
        private readonly IncrementalHash hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        private readonly List<byte[]> blocks=[];private int pending;private bool ended;
        internal byte[][] Finish(){if(!ended)throw new InvalidDataException("Incomplete staged scan");return blocks.ToArray();}
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer,CancellationToken token=default)
        {
            int n=await source.ReadAsync(buffer,token).ConfigureAwait(false);
            if(n<0||n>buffer.Length)throw new InvalidDataException("Invalid staged read count");
            if(n==0){if(!ended&&pending>0)blocks.Add(hash.GetHashAndReset());ended=true;return 0;}
            for(int at=0;at<n;)
            {
                int size=Math.Min(BlockBytes-pending,n-at);hash.AppendData(buffer.Span.Slice(at,size));at+=size;pending+=size;
                if(pending==BlockBytes){blocks.Add(hash.GetHashAndReset());pending=0;}
            }
            if(blocks.Count>1024)throw new BundleSourceException(BundleSourceFailure.Budget,"Staged block index exceeds bound");return n;
        }
        protected override void Dispose(bool disposing){if(disposing)hash.Dispose();base.Dispose(disposing);}
        public override bool CanRead=>true;public override bool CanSeek=>false;public override bool CanWrite=>false;
        public override long Length=>throw new NotSupportedException();public override long Position{get=>throw new NotSupportedException();set=>throw new NotSupportedException();}
        public override int Read(byte[] b,int o,int c)=>throw new NotSupportedException();public override void Flush()=>throw new NotSupportedException();public override long Seek(long o,SeekOrigin s)=>throw new NotSupportedException();public override void SetLength(long v)=>throw new NotSupportedException();public override void Write(byte[] b,int o,int c)=>throw new NotSupportedException();
    }
}
