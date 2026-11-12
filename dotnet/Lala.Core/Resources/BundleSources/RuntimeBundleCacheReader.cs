namespace Lala.Core.Resources;

/// <summary>Read-only Python-compatible bundle cache. Paths select candidates, never trusted
/// bytes: BundleSourcePreparation rechecks length, MD5 and CRC on each opened stream.
/// Lexical path containment is not a sandbox against hostile filesystem replacement.</summary>
internal sealed class RuntimeBundleCacheReader(string absoluteDataRoot) : IBundleSourceCacheReader
{
    private readonly string _root = Path.Combine(Path.GetFullPath(absoluteDataRoot), "official_sync", "bundles");

    public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        // All components originate in the validated manifest-derived BundleSourceSpec.
        string path = Path.Combine(_root, spec.Package, spec.PackageVersion, spec.Md5, spec.Name);
        Stream? stream;
        try
        {
            stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read,
                64 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
        }
        catch (FileNotFoundException) { stream = null; }
        catch (DirectoryNotFoundException) { stream = null; }
        // Permission, directory and other I/O errors remain failures, not silent downloads.
        return ValueTask.FromResult(stream);
    }
}
