using System.Buffers.Binary;
using System.Security.Cryptography;

namespace Lala.Core.Resources;

internal enum RuntimeBundleCacheWriteStage { TemporaryCreated, ChunkCopied, BeforePublish, Published }

/// <summary>Persists owned downloaded bytes in the Python-compatible cache. Every file is
/// verified before atomic, same-directory publication and rechecked before successful return.
/// Cache bytes never grant trust. Observed links/reparse points at the selected data root and
/// cache descendants are rejected; ancestors above that root are trusted. These checks are not
/// a hostile-filesystem sandbox or a power-loss durability guarantee.
/// Cooperative writers may publish the same verified bytes. A batch is not a multi-file transaction.</summary>
internal sealed class RuntimeBundleCacheWriter
{
    private const int ChunkBytes = 64 * 1024;
    private readonly string _dataRoot;
    private readonly string _root;
    private readonly Action<RuntimeBundleCacheWriteStage>? _checkpoint;

    internal RuntimeBundleCacheWriter(string absoluteDataRoot) : this(absoluteDataRoot, null) { }

    // Internal observational test seam. It cannot supply paths, bytes or checksum claims.
    internal RuntimeBundleCacheWriter(string absoluteDataRoot, Action<RuntimeBundleCacheWriteStage>? checkpoint)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absoluteDataRoot);
        if (!Path.IsPathFullyQualified(absoluteDataRoot)) throw new ArgumentException("An absolute data root is required", nameof(absoluteDataRoot));
        _dataRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(absoluteDataRoot));
        _root = Path.Combine(_dataRoot, "official_sync", "bundles");
        _checkpoint = checkpoint;
    }

    internal async Task StoreAsync(IReadOnlyList<VerifiedBundleSource> sources, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(sources);
        cancellationToken.ThrowIfCancellationRequested();
        // Snapshot and validate the whole batch before creating directories or publishing files.
        // Counting every supplied handle is conservative when a caller repeats a source.
        long bytes = 0;
        var downloads = new Dictionary<string, VerifiedBundleSource>(StringComparer.Ordinal);
        int maximumDownloads = new BundleSourceBudget().MaximumDownloads;
        foreach (var source in sources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            ArgumentNullException.ThrowIfNull(source);
            if (source.Spec.Size is <= 0 || source.Spec.Size > BundleSourcePreparation.MaximumRetainedBytes - bytes)
                throw new BundleSourceException(BundleSourceFailure.Budget, "Bundle cache batch exceeds the owned-byte bound");
            bytes += source.Spec.Size;
            if (source.Acquisition == BundleAcquisition.Cache) continue;
            if (source.Acquisition != BundleAcquisition.UntrustedSourceDownload)
                throw new InvalidDataException("Only owned downloaded bundles can populate the cache");
            var spec = source.Spec;
            string path = Path.Combine(_root, spec.Package, spec.PackageVersion, spec.Md5, spec.Name);
            if (downloads.TryGetValue(path, out var prior))
            {
                if (prior.Sha256 != source.Sha256 || prior.Spec.Size != spec.Size || prior.Spec.Crc32Le != spec.Crc32Le)
                    throw new InvalidDataException("Conflicting owned bundles select the same cache entry");
            }
            else if (downloads.Count == maximumDownloads)
                throw new BundleSourceException(BundleSourceFailure.Budget, "Bundle cache batch exceeds the download-count bound");
            else downloads.Add(path, source);
        }
        foreach (var (path, source) in downloads)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await StoreOneAsync(path, source, cancellationToken).ConfigureAwait(false);
        }
        cancellationToken.ThrowIfCancellationRequested();
    }

    private async Task StoreOneAsync(string destination, VerifiedBundleSource source, CancellationToken token)
    {
        string directory = Path.GetDirectoryName(destination)!;
        CheckDirectories(directory, create: true, token);
        if (await MatchesAsync(destination, source, token).ConfigureAwait(false)) return;

        string temporary = Path.Combine(directory, ".bundle_" + Guid.NewGuid().ToString("N") + ".partial");
        bool ownsTemporary = false;
        Exception? primary = null;
        try
        {
            CheckDirectories(directory, create: false, token);
            if (CheckLeaf(temporary)) throw new IOException("Bundle cache temporary path already exists");
            var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                ChunkBytes, FileOptions.Asynchronous | FileOptions.SequentialScan);
            ownsTemporary = true;
            Exception? copyFailure = null;
            try
            {
                Checkpoint(RuntimeBundleCacheWriteStage.TemporaryCreated, token);
                CheckDirectories(directory, create: false, token);
                CheckLeaf(temporary);
                using var input = source.OpenRead();
                byte[] chunk = new byte[ChunkBytes];
                long length = 0;
                while (true)
                {
                    token.ThrowIfCancellationRequested();
                    int requested = (int)Math.Min(chunk.Length, source.Spec.Size - length + 1);
                    int read = await input.ReadAsync(chunk.AsMemory(0, requested), token).ConfigureAwait(false);
                    token.ThrowIfCancellationRequested();
                    if (read < 0 || read > requested || read > source.Spec.Size - length)
                        throw new InvalidDataException("Owned bundle stream exceeds its verified length");
                    if (read == 0) break;
                    await output.WriteAsync(chunk.AsMemory(0, read), token).ConfigureAwait(false);
                    length += read;
                    Checkpoint(RuntimeBundleCacheWriteStage.ChunkCopied, token);
                }
                if (length != source.Spec.Size) throw new InvalidDataException("Owned bundle stream was truncated");
                await output.FlushAsync(token).ConfigureAwait(false);
                token.ThrowIfCancellationRequested();
                output.Flush(flushToDisk: true);
            }
            catch (Exception error) { copyFailure = error; throw; }
            finally { ResourceCleanup.DisposePreservingFailure(output, copyFailure); }

            Checkpoint(RuntimeBundleCacheWriteStage.BeforePublish, token);
            if (!await MatchesAsync(temporary, source, token).ConfigureAwait(false))
                throw new InvalidDataException("Staged bundle differs from its verified owned source");
            // A cooperative writer may have installed identical bytes while this one staged.
            if (await MatchesAsync(destination, source, token).ConfigureAwait(false)) return;
            CheckDirectories(directory, create: false, token);
            if (!CheckLeaf(temporary)) throw new IOException("Staged bundle disappeared before publication");
            CheckLeaf(destination);
            token.ThrowIfCancellationRequested();
            File.Move(temporary, destination, overwrite: true);
            ownsTemporary = false;
            Checkpoint(RuntimeBundleCacheWriteStage.Published, token);
            if (!await MatchesAsync(destination, source, token).ConfigureAwait(false))
                throw new InvalidDataException("Installed bundle differs from its verified owned source");
            token.ThrowIfCancellationRequested();
        }
        catch (Exception error) { primary = error; throw; }
        finally
        {
            if (ownsTemporary)
            {
                try
                {
                    if (CheckDirectories(directory, create: false, CancellationToken.None) && CheckLeaf(temporary)) File.Delete(temporary);
                }
                catch (Exception)
                {
                    if (primary is null) throw;
                    ResourceCleanup.Report(true, primary);
                }
            }
        }
    }

    private void Checkpoint(RuntimeBundleCacheWriteStage stage, CancellationToken token)
    {
        _checkpoint?.Invoke(stage);
        token.ThrowIfCancellationRequested();
    }

    private async Task<bool> MatchesAsync(string path, VerifiedBundleSource source, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        string directory = Path.GetDirectoryName(path)!;
        if (!CheckDirectories(directory, create: false, token) || !CheckLeaf(path)) return false;
        FileStream input;
        try
        {
            // Delete sharing permits another cooperative writer's atomic replacement on Windows.
            input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete,
                ChunkBytes, FileOptions.Asynchronous | FileOptions.SequentialScan);
        }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
        Exception? primary = null;
        try
        {
            if (input.Length != source.Spec.Size) return false;
            using var md5 = IncrementalHash.CreateHash(HashAlgorithmName.MD5);
            using var sha256 = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            byte[] chunk = new byte[ChunkBytes];
            long length = 0;
            uint crc = uint.MaxValue;
            while (true)
            {
                token.ThrowIfCancellationRequested();
                int requested = (int)Math.Min(chunk.Length, source.Spec.Size - length + 1);
                int read = await input.ReadAsync(chunk.AsMemory(0, requested), token).ConfigureAwait(false);
                token.ThrowIfCancellationRequested();
                if (read < 0 || read > requested || read > source.Spec.Size - length) return false;
                if (read == 0) break;
                length += read;
                md5.AppendData(chunk, 0, read);
                sha256.AppendData(chunk, 0, read);
                for (int i = 0; i < read; i++)
                {
                    if ((i & 4095) == 0) token.ThrowIfCancellationRequested();
                    crc = (crc >> 8) ^ CrcTable[(crc ^ chunk[i]) & 0xff];
                }
            }
            byte[] crcBytes = new byte[4];
            BinaryPrimitives.WriteUInt32LittleEndian(crcBytes, crc ^ uint.MaxValue);
            token.ThrowIfCancellationRequested();
            return CheckDirectories(directory, create: false, token) && CheckLeaf(path) && length == source.Spec.Size &&
                Convert.ToHexStringLower(md5.GetHashAndReset()) == source.Spec.Md5 &&
                Convert.ToHexStringLower(crcBytes) == source.Spec.Crc32Le &&
                Convert.ToHexStringLower(sha256.GetHashAndReset()) == source.Sha256;
        }
        catch (Exception error) { primary = error; throw; }
        finally { ResourceCleanup.DisposePreservingFailure(input, primary); }
    }

    private bool CheckDirectories(string directory, bool create, CancellationToken token)
    {
        var components = new Stack<string>();
        for (string path = directory; ; path = Path.GetDirectoryName(path) ?? throw new IOException("Bundle cache path is outside its data root"))
        {
            components.Push(path);
            if (path == _dataRoot) break;
        }
        foreach (string path in components)
        {
            token.ThrowIfCancellationRequested();
            var attributes = Attributes(path);
            if (attributes is null)
            {
                if (!create) return false;
                Directory.CreateDirectory(path);
                attributes = File.GetAttributes(path);
            }
            RejectLink(attributes.Value);
            if ((attributes.Value & FileAttributes.Directory) == 0) throw new IOException("Bundle cache directory is not a directory");
        }
        return true;
    }

    private static bool CheckLeaf(string path)
    {
        var attributes = Attributes(path);
        if (attributes is null) return false;
        RejectLink(attributes.Value);
        if ((attributes.Value & FileAttributes.Directory) != 0) throw new IOException("Bundle cache entry is not a regular file");
        return true;
    }

    private static FileAttributes? Attributes(string path)
    {
        try { return File.GetAttributes(path); }
        catch (FileNotFoundException) { return null; }
        catch (DirectoryNotFoundException) { return null; }
    }

    private static void RejectLink(FileAttributes attributes)
    {
        if ((attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("Bundle cache path contains a symbolic link or reparse point");
    }

    private static readonly uint[] CrcTable = Enumerable.Range(0, 256).Select(value =>
    {
        uint crc = (uint)value;
        for (int bit = 0; bit < 8; bit++) crc = (crc & 1) == 0 ? crc >> 1 : (crc >> 1) ^ 0xedb88320u;
        return crc;
    }).ToArray();
}
