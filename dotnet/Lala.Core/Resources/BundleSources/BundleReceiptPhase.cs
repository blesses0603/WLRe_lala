namespace Lala.Core.Resources;

// Cache-read phase only, not network acquisition or publication. Full closure is
// reverified before and after consumption; at most one selected handle is owned.
internal sealed class BundleReceiptPhase:IAsyncDisposable
{
    private readonly BundleStreamReceipt[] receipts;private readonly IBundleSourceCacheReader cache;
    private readonly SemaphoreSlim gate=new(1,1);private readonly object lifecycle=new();private int closed;private Task? disposal;
    internal BundleReceiptPhase(IBundleSourceCacheReader cache,IReadOnlyList<BundleStreamReceipt> receipts)
    {
        ArgumentNullException.ThrowIfNull(cache);ArgumentNullException.ThrowIfNull(receipts);
        if(receipts.Count is <1 or >24)throw new BundleSourceException(BundleSourceFailure.Budget,"Receipt phase count exceeds bound");
        this.receipts=receipts.ToArray();this.cache=cache;long total=0;var keys=new HashSet<(string,string)>();var versions=new Dictionary<string,string>();string? data=null;
        foreach(var r in this.receipts)
        {
            ArgumentNullException.ThrowIfNull(r);var spec=r.Spec;ArgumentNullException.ThrowIfNull(spec);
            total=checked(total+spec.Size);
            if(total>64L*1024*1024)throw new BundleSourceException(BundleSourceFailure.Budget,"Receipt phase exceeds disk-source bound");
            if(r.Sha256 is null||r.Sha256.Length!=64||r.Sha256.Any(c=>!(c is >= '0' and <= '9' or >= 'a' and <= 'f'))||!keys.Add((spec.Package,spec.Name))||
                data is not null&&data!=spec.DataVersion||versions.TryGetValue(spec.Package,out var version)&&version!=spec.PackageVersion)
                throw new BundleSourceException(BundleSourceFailure.ManifestIdentity,"Mixed or duplicate receipt phase identity");
            data=spec.DataVersion;versions[spec.Package]=spec.PackageVersion;
        }
    }
    private void Check(CancellationToken token){token.ThrowIfCancellationRequested();ObjectDisposedException.ThrowIf(Volatile.Read(ref closed)!=0,this);}
    private async Task VerifyClosureAsync(CancellationToken token)
    {
        foreach(var receipt in receipts)
        {
            Check(token);var opened=await VerifiedBundleBlockSource.OpenAsync(cache,receipt,token).ConfigureAwait(false);Exception? primary=null;
            try{Check(token);}
            catch(Exception error){primary=error;throw;}
            finally
            {
                try{await opened.DisposeAsync().ConfigureAwait(false);}
                catch(Exception){if(primary is null)throw;ResourceCleanup.Report(true,primary);}
            }
        }
    }
    internal async Task<T> ReadAsync<T>(string package,string name,Func<VerifiedBundleBlockSource,CancellationToken,Task<T>> consume,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(consume);Check(token);
        var receipt=receipts.SingleOrDefault(r=>r.Spec.Package==package&&r.Spec.Name==name)
            ??throw new BundleSourceException(BundleSourceFailure.MissingRequiredAsset,"Selected source is outside receipt phase");
        await gate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            Check(token);await VerifyClosureAsync(token).ConfigureAwait(false);T result;
            var opened=await VerifiedBundleBlockSource.OpenAsync(cache,receipt,token).ConfigureAwait(false);Exception? primary=null;
            try{Check(token);result=await consume(opened,token).ConfigureAwait(false);Check(token);}
            catch(Exception error){primary=error;throw;}
            finally
            {
                try{await opened.DisposeAsync().ConfigureAwait(false);}
                catch(Exception){if(primary is null)throw;ResourceCleanup.Report(true,primary);}
            }
            await VerifyClosureAsync(token).ConfigureAwait(false);Check(token);return result;
        }
        finally{gate.Release();}
    }
    public ValueTask DisposeAsync(){lock(lifecycle){Volatile.Write(ref closed,1);return new(disposal??=DisposeCoreAsync());}}
    private async Task DisposeCoreAsync(){await gate.WaitAsync().ConfigureAwait(false);gate.Release();}
}
