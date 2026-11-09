using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

// Parse each owned bundle once per batch, but resolve each image only in its exact planned closure.
// Checksums, parsed objects and source identities remain observations, not official admission.
internal static class UnitySpriteExtractor
{
    private sealed record Match(BoundedSerializedFile File, UnityContainerPointer Pointer, VerifiedBundleSource Source);
    internal static SpritePixelCandidate Extract(string assetPath, string versionIdentity, IReadOnlyList<VerifiedBundleSource> sources,
        CancellationToken token = default) => ExtractMany(new Dictionary<string, IReadOnlyList<VerifiedBundleSource>>(StringComparer.Ordinal)
        { [assetPath] = sources }, versionIdentity, token)[assetPath];

    internal static IReadOnlyDictionary<string, SpritePixelCandidate> ExtractMany(
        IReadOnlyDictionary<string, IReadOnlyList<VerifiedBundleSource>> selected, string versionIdentity, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        Require(selected.Count is > 0 and <= 8192, "Image batch count limit");
        Require(!string.IsNullOrEmpty(versionIdentity) && versionIdentity.Length <= 1024 && !versionIdentity.Contains('\0'), "Invalid claimed version identity");
        var closures = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        var sources = new Dictionary<string, VerifiedBundleSource>(StringComparer.Ordinal);
        foreach (var (path, group) in selected)
        {
            token.ThrowIfCancellationRequested();
            Require(!string.IsNullOrEmpty(path) && path.Length <= 1024 && !path.Contains('\0') && !path.Contains('\\') &&
                path.Split('/').All(p => p.Length > 0 && p is not "." and not ".."), "Invalid exact image AssetPath");
            Require(group.Count is > 0 and <= 4, "Image bundle count limit");
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var source in group)
            {
                Require(names.Add(source.Spec.Name), "Duplicate image source");
                if (sources.TryGetValue(source.Spec.Name, out var prior))
                    Require(prior.Spec == source.Spec && prior.Sha256 == source.Sha256, "Conflicting image source identity");
                else sources.Add(source.Spec.Name, source);
            }
            closures.Add(path, names);
        }
        Require(sources.Count <= 4, "Image batch bundle count limit");
        var first = sources.Values.First().Spec; long total = 0;
        foreach (var source in sources.Values)
        {
            var spec = source.Spec;
            Require(spec.DataVersion == first.DataVersion && spec.Package == first.Package && spec.PackageVersion == first.PackageVersion,
                "Mixed-version image bundle set");
            total += spec.Size; Require(spec.Size > 0 && total <= 32 * 1024 * 1024, "Image batch source byte limit");
        }
        var budget = new UnityExtractionBudget(); var matches = new Dictionary<string, List<Match>>(StringComparer.Ordinal);
        foreach (var source in sources.Values)
        {
            using var stream = source.OpenRead(); byte[] input = new byte[checked((int)source.Spec.Size)];
            for (int offset = 0; offset < input.Length;)
            { token.ThrowIfCancellationRequested(); int read = stream.Read(input, offset, Math.Min(65536, input.Length - offset)); Require(read > 0, "Truncated owned image bundle"); offset += read; }
            Require(stream.ReadByte() == -1, "Owned image bundle length changed");
            foreach (var entry in BoundedUnityBundle.Read(input, budget, token))
            {
                var file = BoundedSerializedFile.Read(new(source.Spec.Name, entry.Name), entry.Bytes, budget, token, allowImages: true);
                foreach (var e in file.Container)
                {
                    token.ThrowIfCancellationRequested();
                    if (!closures.TryGetValue(e.Path, out var allowed) || !allowed.Contains(source.Spec.Name)) continue;
                    if (!matches.TryGetValue(e.Path, out var list)) matches.Add(e.Path, list = []);
                    Require(list.Count < 2, "Ambiguous image container path"); list.Add(new(file, e.Pointer, source));
                }
            }
        }
        long pixels = 0; var result = new Dictionary<string, SpritePixelCandidate>(StringComparer.Ordinal);
        foreach (var path in closures.Keys.Order(StringComparer.Ordinal))
        {
            token.ThrowIfCancellationRequested();
            var candidate = Decode(path, versionIdentity, closures[path].Select(name => sources[name]).ToArray(),
                matches.GetValueOrDefault(path) ?? [], token);
            pixels += (long)(candidate.Width * 4 + 1) * candidate.Height + 160;
            Require(pixels <= 96 * 1024 * 1024, "Image batch pixel/PNG budget exceeded");
            result.Add(path, candidate);
        }
        return result;
    }
    private static SpritePixelCandidate Decode(string assetPath, string versionIdentity, IReadOnlyList<VerifiedBundleSource> sources,
        List<Match> matches, CancellationToken token)
    {
        Require(matches.Count == 2, "Expected exact Sprite/Texture container pair");
        var a = matches[0]; var b = matches[1];
        Require(ReferenceEquals(a.File, b.File) && a.Pointer.FileId == 0 && b.Pointer.FileId == 0 &&
            a.Pointer.PathId != 0 && b.Pointer.PathId != 0 && a.Pointer.PathId != b.Pointer.PathId &&
            a.File.Objects.ContainsKey(a.Pointer.PathId) && a.File.Objects.ContainsKey(b.Pointer.PathId), "Image pair must resolve distinctly in the same file");
        if (a.File.Objects[a.Pointer.PathId].ClassId == 28) (a, b) = (b, a);
        Require(a.File.Objects[a.Pointer.PathId].ClassId == 213 && b.File.Objects[b.Pointer.PathId].ClassId == 28, "Wrong image container classes");
        var sprite = UnityImageObjects.Sprite(a.File.Objects[a.Pointer.PathId].Bytes, token);
        var texture = UnityImageObjects.Texture(b.File.Objects[b.Pointer.PathId].Bytes, token);
        Require(sprite.Texture.FileId == 0 && sprite.Texture.PathId == b.Pointer.PathId, "Sprite references another texture");
        string fileName = assetPath[(assetPath.LastIndexOf('/') + 1)..]; int dot = fileName.LastIndexOf('.'); string stem = dot >= 0 ? fileName[..dot] : fileName;
        Require((sprite.Name == fileName || sprite.Name == stem) && (texture.Name == fileName || texture.Name == stem), "Image object name differs from exact path");
        // Caller identity remains a claim; verified bytes and exact PPtrs do not prove official origin.
        string inputs = System.Text.Json.JsonSerializer.Serialize(new { ClaimedIdentity = versionIdentity, Sources = sources.OrderBy(s => s.Spec.Name, StringComparer.Ordinal).Select(s =>
            new { s.Spec.DataVersion, s.Spec.Package, s.Spec.PackageVersion, s.Spec.Name, s.Spec.Md5, s.Spec.Crc32Le, s.Sha256 }) });
        var context = new SpritePixelContext(inputs, a.Source.Sha256, a.File.Identity.EntryName, assetPath, a.Pointer.PathId, b.Pointer.PathId);
        return BoundedSpritePixels.Decode(context, texture.Layout, sprite.Rect, texture.Payload.Span, token);
    }
}
