using System.Buffers.Binary;
using System.Collections.Frozen;
using System.Text;

namespace Lala.Core.Resources;

internal enum BundleSourceFailure
{
    ManifestSize, ManifestSyntax, DuplicateBundle, DuplicateAsset, InvalidReference,
    ManifestIdentity, MissingRequiredAsset, InvalidBundle, ResponseSource, ResponseLength,
    Checksum, Budget, CacheChanged, VersionsChanged, ManifestChanged, StaleAttempt, SourceUnavailable
}

internal sealed class BundleSourceException(BundleSourceFailure failure, string message) : FormatException(message)
{
    internal BundleSourceFailure Failure { get; } = failure;
}

internal sealed record YooAssetHeader(string FileVersion, bool EnableAddressable, bool LocationToLower,
    bool IncludeAssetGuid, int OutputNameStyle, int BuildBundleType, string BuildPipeline,
    string PackageName, string PackageVersion, string PackageNote);
internal sealed record YooAssetEntry(string Address, string Path, string Guid, IReadOnlyList<string> Tags, int BundleId);
internal sealed record YooBundleEntry(string Name, uint UnityCrc, string FileHash, string FileCrc, long FileSize,
    bool Encrypted, IReadOnlyList<string> Tags, IReadOnlyList<int> DependencyIds);

/// <summary>Actual bounded 2.2.5 binary parser. Parsed bytes are not official-source authority.</summary>
internal sealed class YooAssetManifest
{
    internal const int MaximumItems = 1_000_000;
    internal YooAssetHeader Header { get; }
    internal IReadOnlyList<YooAssetEntry> Assets { get; }
    internal IReadOnlyList<YooBundleEntry> Bundles { get; }
    internal IReadOnlyDictionary<string, int> AssetBundles { get; }
    internal string Sha256 { get; }
    internal string Crc32Le { get; }

    private YooAssetManifest(YooAssetHeader header, List<YooAssetEntry> assets, List<YooBundleEntry> bundles,
        ReadOnlySpan<byte> bytes, CancellationToken cancellationToken)
    {
        Header = header; Assets = assets.AsReadOnly(); Bundles = bundles.AsReadOnly();
        AssetBundles = assets.ToFrozenDictionary(x => x.Path, x => x.BundleId, StringComparer.Ordinal);
        Sha256 = ResourceValidation.Digest(bytes, cancellationToken);
        Crc32Le = ManifestIdentity.Crc32LittleEndian(bytes, cancellationToken);
    }

    internal static YooAssetManifest Parse(ReadOnlySpan<byte> input, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (input.Length is 0 or > ManifestIdentity.MaximumManifestBytes)
            throw new BundleSourceException(BundleSourceFailure.ManifestSize, "Manifest size exceeds bounded parser input");
        // Hashing and parsing share a single owned copy, never caller-owned mutable storage.
        byte[] bytes = input.ToArray();
        var reader = new ManifestReader(bytes, cancellationToken);
        if (reader.U32() != 0x00594f4f) throw Syntax("YooAsset manifest signature mismatch");
        string version = reader.Utf8();
        if (version != "2.2.5") throw Syntax("Unsupported YooAsset manifest format");
        var header = new YooAssetHeader(version, reader.Boolean(), reader.Boolean(), reader.Boolean(),
            reader.I32(), reader.I32(), reader.Utf8(), reader.Utf8(), reader.Utf8(), reader.Utf8());
        int assetCount = reader.Count(12);
        var assets = new List<YooAssetEntry>();
        for (int i = 0; i < assetCount; i++)
            assets.Add(new(reader.Utf8(), reader.Utf8(), reader.Utf8(), reader.Strings(), reader.I32()));
        int bundleCount = reader.Count(23);
        var bundles = new List<YooBundleEntry>();
        for (int i = 0; i < bundleCount; i++)
            bundles.Add(new(reader.Utf8(), reader.U32(), reader.Utf8(), reader.Utf8(), reader.I64(),
                reader.Boolean(), reader.Strings(), reader.Ids()));
        if (reader.Remaining != 0) throw Syntax("Unexpected trailing manifest bytes");
        if (bundles.Select(x => x.Name).Distinct(StringComparer.Ordinal).Count() != bundles.Count)
            throw new BundleSourceException(BundleSourceFailure.DuplicateBundle, "Duplicate bundle names");
        if (assets.Select(x => x.Path).Distinct(StringComparer.Ordinal).Count() != assets.Count)
            throw new BundleSourceException(BundleSourceFailure.DuplicateAsset, "Duplicate asset paths");
        foreach (var bundle in bundles)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (bundle.FileSize < 0) throw Syntax("Negative bundle size");
            if (bundle.DependencyIds.Any(id => id < 0 || id >= bundles.Count))
                throw new BundleSourceException(BundleSourceFailure.InvalidReference, "Invalid dependency ID");
        }
        foreach (var asset in assets)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (asset.BundleId < 0 || asset.BundleId >= bundles.Count)
                throw new BundleSourceException(BundleSourceFailure.InvalidReference, "Invalid asset bundle ID");
        }
        return new(header, assets, bundles, bytes, cancellationToken);
    }

    internal void ValidateIdentity(OfficialVersionSnapshot snapshot, string package)
    {
        if (!ResourceValidation.Packages.Contains(package, StringComparer.Ordinal) ||
            Header.PackageName != package || Header.PackageVersion != snapshot.Packages[package] || Header.OutputNameStyle != 1)
            throw new BundleSourceException(BundleSourceFailure.ManifestIdentity, "Manifest header differs from observed package identity");
    }

    private static BundleSourceException Syntax(string message) => new(BundleSourceFailure.ManifestSyntax, message);
    private ref struct ManifestReader(ReadOnlySpan<byte> bytes, CancellationToken cancellationToken)
    {
        private readonly ReadOnlySpan<byte> _bytes = bytes;
        private readonly CancellationToken _cancellationToken = cancellationToken;
        private int _position;
        internal int Remaining => _bytes.Length - _position;
        private ReadOnlySpan<byte> Take(int size)
        {
            _cancellationToken.ThrowIfCancellationRequested();
            if (size < 0 || size > Remaining) throw Syntax("Unexpected end of manifest");
            var result = _bytes.Slice(_position, size); _position += size; return result;
        }
        internal ushort U16() => BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
        internal uint U32() => BinaryPrimitives.ReadUInt32LittleEndian(Take(4));
        internal int I32() => BinaryPrimitives.ReadInt32LittleEndian(Take(4));
        internal long I64() => BinaryPrimitives.ReadInt64LittleEndian(Take(8));
        internal bool Boolean() => Take(1)[0] switch { 0 => false, 1 => true, _ => throw Syntax("Invalid manifest boolean") };
        internal string Utf8()
        {
            var value = Take(U16());
            try { return new UTF8Encoding(false, true).GetString(value); }
            catch (DecoderFallbackException) { throw Syntax("Invalid manifest UTF-8"); }
        }
        internal int Count(int minimumRowBytes)
        {
            int count = I32();
            if (count < 0 || count > MaximumItems || count > Remaining / minimumRowBytes)
                throw Syntax("Invalid or truncated manifest count");
            return count;
        }
        internal IReadOnlyList<string> Strings()
        {
            int count = U16();
            if (count > Remaining / 2) throw Syntax("Truncated string list");
            var result = new string[count];
            for (int i = 0; i < count; i++) result[i] = Utf8();
            return Array.AsReadOnly(result);
        }
        internal IReadOnlyList<int> Ids()
        {
            int count = U16();
            if (count > Remaining / 4) throw Syntax("Truncated dependency list");
            var result = new int[count];
            for (int i = 0; i < count; i++) result[i] = I32();
            return Array.AsReadOnly(result);
        }
    }
}
