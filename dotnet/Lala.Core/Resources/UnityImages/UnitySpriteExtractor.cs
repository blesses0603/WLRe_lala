using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

/// <summary>Internal bounded checksum-verified bundle -> exact same-file Sprite/Texture candidate.
/// No source acquisition, official provenance, persistent image cache or activation.</summary>
internal static class UnitySpriteExtractor
{
    internal static SpritePixelCandidate Extract(string assetPath, string versionIdentity, IReadOnlyList<VerifiedBundleSource> sources,
        CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested(); ArgumentNullException.ThrowIfNull(sources);
        Require(!string.IsNullOrEmpty(assetPath) && assetPath.Length <= 1024 && !assetPath.Contains('\0') && !assetPath.Contains('\\') &&
            assetPath.Split('/').All(p => p.Length > 0 && p is not "." and not ".."), "Invalid exact image AssetPath");
        Require(!string.IsNullOrEmpty(versionIdentity) && versionIdentity.Length <= 1024 && !versionIdentity.Contains('\0'), "Invalid claimed version identity");
        Require(sources.Count is > 0 and <= 4, "Image bundle count limit");
        var first = sources[0].Spec; var names = new HashSet<string>(StringComparer.Ordinal); long total = 0;
        foreach (var source in sources)
        {
            var s = source.Spec; token.ThrowIfCancellationRequested();
            Require(names.Add(s.Name) && s.DataVersion == first.DataVersion && s.Package == first.Package && s.PackageVersion == first.PackageVersion,
                "Duplicate or mixed-version image bundle set");
            total += s.Size; Require(s.Size > 0 && total <= 32 * 1024 * 1024, "Image bundle byte limit");
        }
        var budget = new UnityExtractionBudget();
        var matches = new List<(BoundedSerializedFile File, UnityContainerPointer Pointer, VerifiedBundleSource Source)>();
        foreach (var source in sources)
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
                    token.ThrowIfCancellationRequested(); if (e.Path != assetPath) continue;
                    Require(matches.Count < 2, "Ambiguous image container path"); matches.Add((file, e.Pointer, source));
                }
            }
        }
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
