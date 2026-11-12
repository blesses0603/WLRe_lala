using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

/// <summary>Internal offline byte decoder, not an official-origin or readiness authority.</summary>
internal static class UnityTextAssetExtractor
{
    internal static byte[] Extract(string assetPath, IReadOnlyList<VerifiedBundleSource> sources,
        IReadOnlyList<UnityExternalBinding>? externalBindings = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(sources); cancellationToken.ThrowIfCancellationRequested();
        Require(!string.IsNullOrEmpty(assetPath) && assetPath.Length <= 1024 && !assetPath.Contains('\0') && !assetPath.Contains('\\') &&
            assetPath.Split('/').All(part => part.Length > 0 && part is not "." and not ".."), "Invalid exact AssetPath");
        Require(sources.Count is >= 1 and <= 24, "Expected 1 to 24 verified bundles");
        externalBindings ??= Array.Empty<UnityExternalBinding>(); Require(externalBindings.Count <= 128, "External allowlist exceeds bound");
        // These records are keyed by the full supplied bundle identity and exact directory name.
        // Matching CAB basenames in different bundles never alias, even when casing differs.
        var names = new HashSet<string>(StringComparer.Ordinal); long total = 0;
        var first = sources[0].Spec;
        foreach (var source in sources)
        {
            cancellationToken.ThrowIfCancellationRequested(); var spec = source.Spec;
            Require(spec.DataVersion == first.DataVersion && spec.Package == first.Package && spec.PackageVersion == first.PackageVersion && names.Add(spec.Name),
                "Duplicate or mixed-version bundle identities");
            Require(spec.Size is > 0 and <= BoundedUnityBundle.MaximumBundleBytes, "Bundle exceeds extraction bound");
            total += spec.Size; Require(total <= BoundedUnityBundle.MaximumTotalBytes, "Combined bundle bytes exceed extraction bound");
        }
        var files = new Dictionary<UnityFileIdentity, BoundedSerializedFile>(); var budget = new UnityExtractionBudget();
        foreach (var source in sources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            using var stream = source.OpenRead();
            byte[] input = ReadOwned(stream, checked((int)source.Spec.Size), cancellationToken);
            foreach (var entry in BoundedUnityBundle.Read(input, budget, cancellationToken))
            {
                var id = new UnityFileIdentity(source.Spec.Name, entry.Name);
                Require(files.TryAdd(id, BoundedSerializedFile.Read(id, entry.Bytes, budget, cancellationToken)), "Duplicate SerializedFile identity");
            }
        }
        var allowlist = new Dictionary<(UnityFileIdentity Source, string Path), UnityFileIdentity>();
        foreach (var binding in externalBindings)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Require(files.ContainsKey(binding.Source) && files.ContainsKey(binding.Target) &&
                files[binding.Source].Externals.Contains(binding.ExternalPath, StringComparer.Ordinal) &&
                allowlist.TryAdd((binding.Source, binding.ExternalPath), binding.Target), "Invalid or ambiguous external allowlist");
        }
        BoundedSerializedFile? foundFile = null; UnityContainerPointer? found = null;
        foreach (var file in files.Values)
            foreach (var entry in file.Container)
            {
                cancellationToken.ThrowIfCancellationRequested(); if (!StringComparer.Ordinal.Equals(entry.Path, assetPath)) continue;
                Require(found is null, "Duplicate exact AssetPath in supplied containers"); found = entry.Pointer; foundFile = file;
            }
        Require(found is not null && foundFile is not null, "Exact AssetPath missing from supplied containers");
        var target = foundFile!; var pointer = found!;
        Require(pointer.FileId >= 0 && pointer.FileId <= target.Externals.Count, "Invalid external PPtr index");
        if (pointer.FileId > 0)
        {
            Require(allowlist.TryGetValue((target.Identity, target.Externals[pointer.FileId - 1]), out var id), "External PPtr not explicitly allowlisted");
            target = files[id!];
        }
        Require(pointer.PathId != 0 && target.Objects.TryGetValue(pointer.PathId, out _), "Missing PPtr target");
        var obj = target.Objects[pointer.PathId]; Require(obj.ClassId == 49, "Exact AssetPath does not resolve to TextAsset class49");
        var text = BoundedSerializedFile.ValidateText(obj.Bytes, cancellationToken);
        Require(text.Payload.Length > 0, "Empty requested TextAsset script");
        string filename = assetPath[(assetPath.LastIndexOf('/') + 1)..]; int dot = filename.LastIndexOf('.');
        string stem = dot >= 0 ? filename[..dot] : filename;
        Require(text.Name == filename || text.Name == stem, "TextAsset name differs from exact AssetPath");
        cancellationToken.ThrowIfCancellationRequested(); return text.Payload.ToArray();
    }

    // Stream ownership remains local, including cancellation/failure. No reopenable paths escape.
    private static byte[] ReadOwned(Stream stream, int length, CancellationToken token)
    {
        byte[] bytes = new byte[length]; int offset = 0;
        while (offset < bytes.Length)
        {
            token.ThrowIfCancellationRequested(); int read = stream.Read(bytes, offset, Math.Min(64 * 1024, bytes.Length - offset));
            Require(read > 0, "Truncated owned bundle"); offset += read;
        }
        token.ThrowIfCancellationRequested(); Require(stream.ReadByte() == -1, "Owned bundle length changed"); return bytes;
    }
}
