using System.Buffers.Binary;
using System.Text;

namespace Lala.Core.Resources;

// Internal until the real official fetch/full YooAsset parser adapter is ported. An arbitrary caller
// cannot mint a public "verified Manifest" using a supplied CRC or header. Synthetic tests use this
// seam, just as Python tests construct VerifiedManifest; it does not establish source authenticity.
internal sealed record ManifestIdentityInput(string DataVersion, string Package, string PackageVersion,
    string HeaderPackage, string HeaderVersion, string FileVersion, string OfficialCrc32Le, byte[] Bytes);
internal sealed record ManifestPackageIdentity(string Name, string FullVersion, string ManifestSha256, string ManifestCrc32Le);

/// <summary>Exact pure catalog_identity.py CRC/SHA identity derivation; not runtime activation.</summary>
internal sealed class ManifestIdentity
{
    internal const int MaximumManifestBytes = 8 * 1024 * 1024;
    internal string DataVersion { get; }
    internal string ExeVersion { get; }
    internal IReadOnlyList<ManifestPackageIdentity> Packages { get; }
    internal string Key { get; }
    private ManifestIdentity(OfficialVersionSnapshot snapshot, List<ManifestPackageIdentity> packages, CancellationToken cancellationToken)
    {
        DataVersion = snapshot.DataVersion; ExeVersion = snapshot.ExeVersion; Packages = packages.AsReadOnly();
        string identity = "{\"data_ver\":" + ResourceValidation.Quote(DataVersion) + ",\"exe_version\":" + ResourceValidation.Quote(ExeVersion) +
            ",\"packages\":[" + string.Join(',', packages.Select(p => "{\"full_version\":" + ResourceValidation.Quote(p.FullVersion) +
                ",\"manifest_crc32_le\":" + ResourceValidation.Quote(p.ManifestCrc32Le) + ",\"manifest_sha256\":" + ResourceValidation.Quote(p.ManifestSha256) +
                ",\"name\":" + ResourceValidation.Quote(p.Name) + "}")) + "],\"schema_version\":1}";
        Key = ResourceValidation.Digest(Encoding.ASCII.GetBytes(identity), cancellationToken);
    }
    internal static ManifestIdentity Derive(OfficialVersionSnapshot snapshot, IReadOnlyDictionary<string, ManifestIdentityInput> manifests, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(snapshot);
        if (manifests is null || manifests.Count != 2 || ResourceValidation.Packages.Any(name => !manifests.ContainsKey(name)))
            throw new ResourceValidationException("Both official Package manifests are required");
        var packages = new List<ManifestPackageIdentity>();
        foreach (string name in ResourceValidation.Packages)
        {
            cancellationToken.ThrowIfCancellationRequested();
            ManifestIdentityInput input = manifests[name];
            if (input is null || input.Package != name || input.DataVersion != snapshot.DataVersion || input.PackageVersion != snapshot.Packages[name])
                throw new ResourceValidationException("Official snapshot/Manifest identity mismatch");
            if (input.HeaderPackage != name || input.HeaderVersion != input.PackageVersion || input.FileVersion != "2.2.5")
                throw new ResourceValidationException("YooAsset parser header identity mismatch");
            if (input.Bytes is null || input.Bytes.Length is 0 or > MaximumManifestBytes)
                throw new ResourceValidationException("Private Manifest size is not trustworthy");
            // Hash and CRC the same owned copy. Returned identity never retains mutable byte arrays.
            byte[] bytes = input.Bytes.ToArray();
            string crc = Crc32LittleEndian(bytes, cancellationToken);
            if (crc != input.OfficialCrc32Le)
                throw new ResourceValidationException("Private Manifest CRC differs from official verification");
            packages.Add(new(name, input.PackageVersion, ResourceValidation.Digest(bytes, cancellationToken), crc));
        }
        return new(snapshot, packages, cancellationToken);
    }
    internal static void ConfirmStable(OfficialVersionSnapshot before, OfficialVersionSnapshot after,
        ManifestIdentity initial, IReadOnlyDictionary<string, ManifestIdentityInput> rereadManifests, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!before.HasSameIdentity(after))
            throw new ResourceValidationException("Official versions changed during runtime load");
        if (Derive(after, rereadManifests, cancellationToken).Key != initial.Key)
            throw new ResourceValidationException("Official manifests changed during runtime load");
    }
    private static readonly uint[] CrcTable = Enumerable.Range(0, 256).Select(value =>
    {
        uint crc = (uint)value;
        for (int bit = 0; bit < 8; bit++) crc = (crc & 1) == 0 ? crc >> 1 : (crc >> 1) ^ 0xedb88320u;
        return crc;
    }).ToArray();
    internal static string Crc32LittleEndian(ReadOnlySpan<byte> bytes, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        uint crc = uint.MaxValue;
        for (int index = 0; index < bytes.Length; index++)
        {
            if ((index & 4095) == 0) cancellationToken.ThrowIfCancellationRequested();
            crc = (crc >> 8) ^ CrcTable[(crc ^ bytes[index]) & 0xff];
        }
        cancellationToken.ThrowIfCancellationRequested();
        Span<byte> result = stackalloc byte[4];
        BinaryPrimitives.WriteUInt32LittleEndian(result, crc ^ uint.MaxValue);
        return Convert.ToHexStringLower(result);
    }
}
