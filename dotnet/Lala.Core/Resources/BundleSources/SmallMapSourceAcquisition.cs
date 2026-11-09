using System.Globalization;
namespace Lala.Core.Resources;

// Exact manifest-derived streaming route; legacy OpenAsync retains its 32 MiB cap.
internal interface IBundleStreamSource
{
    ValueTask<ResourceResponse> OpenBundleStreamAsync(BundleSourceSpec spec,CancellationToken token);
}
internal sealed record SmallMapAcquisitionResult(SmallMapReceiptBatch Batch,int DownloadCount,long DownloadBytes);
// One invocation per attempt. The 4-file/64 MiB disk stage is distinct from owned
// bytes and never resets/reuses the original 24-file/32 MiB download budget.
internal sealed class SmallMapSourceAcquisition
{
    private int used;
    internal async Task<SmallMapAcquisitionResult?> AcquireAsync(YooAssetManifest manifest,string version,IResourceSource source,
        IBundleSourceCacheReader cache,RuntimeBundleCacheWriter writer,bool allowDownloads,Action checkCurrent,
        string host=OfficialResourceOrigin.DefaultHost,CancellationToken token=default)
    {
        if(Interlocked.Exchange(ref used,1)!=0)throw new InvalidOperationException("Small map acquisition is single-use");
        host=OfficialResourceOrigin.SelectHost(host);ArgumentNullException.ThrowIfNull(checkCurrent);
        void Check(){token.ThrowIfCancellationRequested();checkCurrent();}
        Check();if(source.SelectedHost is {} bound&&bound!=host)throw new BundleSourceException(BundleSourceFailure.ResponseSource,"Staged source origin mismatch");
        var plan=SmallMapSourcePlan.CreateStaged(manifest,version,token);var receipts=new Dictionary<string,BundleStreamReceipt>(StringComparer.Ordinal);var missing=new List<BundleSourceSpec>();
        // Probe the complete plan before any download or cache write.
        foreach(var entry in plan.Entries)
        {
            Check();var input=await cache.OpenReadAsync(entry.Spec,token).ConfigureAwait(false);
            if(input is null){Check();missing.Add(entry.Spec);continue;}
            Exception? primary=null;
            try{Check();receipts.Add(entry.Spec.Name,await BundleStreamVerifier.VerifyAsync(entry.Spec,input,token:token).ConfigureAwait(false));Check();}
            catch(BundleSourceException error) when(error.Failure is BundleSourceFailure.Checksum or BundleSourceFailure.ResponseLength)
            {primary=error;missing.Add(entry.Spec);}
            catch(Exception error){primary=error;throw;}
            finally{ResourceCleanup.DisposePreservingFailure(input,primary);if(primary?.Data.Contains(ResourceCleanup.FailureMarker)==true)throw primary;}
        }
        Check();if(missing.Count>0&&(!allowDownloads||source is not IBundleStreamSource))return null;
        // Reserve all missing bytes once, including any attempt that later fails.
        long bytes=missing.Sum(s=>s.Size);int count=missing.Count;
        if(count>4||bytes>64L*1024*1024)throw new BundleSourceException(BundleSourceFailure.Budget,"Staged download quota exceeded");
        foreach(var spec in missing)
        {
            Check();var response=await ((IBundleStreamSource)source).OpenBundleStreamAsync(spec,token).ConfigureAwait(false);Exception? primary=null;
            try
            {
                Check();if(response.FinalUrl!=spec.Url(host)||response.Status!=200)throw new BundleSourceException(BundleSourceFailure.ResponseSource,"Staged response source mismatch");
                if(response.ContentLength is {} length&&(length.Length is 0 or >20||length.Any(c=>c is <'0' or >'9')||!long.TryParse(length,NumberStyles.None,CultureInfo.InvariantCulture,out long declared)||declared!=spec.Size))
                    throw new BundleSourceException(BundleSourceFailure.ResponseLength,"Staged Content-Length differs from manifest");
                receipts.Add(spec.Name,await writer.StoreStreamAsync(spec,response.Body,token).ConfigureAwait(false));Check();
            }
            catch(Exception error){primary=error;throw;}
            finally{ResourceCleanup.DisposePreservingFailure(response,primary);}
        }
        // Every cache hit and newly installed entry is reopened against its receipt.
        foreach(var receipt in receipts.Values)
        {
            Check();var opened=await VerifiedBundleBlockSource.OpenAsync(cache,receipt,token).ConfigureAwait(false);Exception? primary=null;
            try{Check();}catch(Exception error){primary=error;throw;}
            finally{try{await opened.DisposeAsync().ConfigureAwait(false);}catch(Exception){if(primary is null)throw;ResourceCleanup.Report(true,primary);}}
        }
        Check();return new(new(manifest,version,cache,receipts.Values.ToArray(),token),count,bytes);
    }
}
