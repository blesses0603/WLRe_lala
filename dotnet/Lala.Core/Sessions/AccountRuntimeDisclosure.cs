using Lala.Core.Resources;

namespace Lala.Core.Sessions;

/// <summary>Two independent operation disclosures, not evidence of host permission.</summary>
public sealed class AccountRuntimeDisclosure
{
    public AccountLoginDisclosure Login { get; }
    public AccountResourceDisclosure Resources { get; }
    internal AccountRuntimeDisclosure(AccountLoginDisclosure login, AccountResourceDisclosure resources)
        => (Login, Resources) = (login, resources);
    public override string ToString() => "Prepared account disclosure (identity and local paths redacted)";
}

/// <summary>Fixed production resource destination and local writes. Login permission alone
/// does not authorize these operations. Version-dependent URLs are resolved when preparation runs from
/// validated official metadata, within ResourceUrlPrefix; no login credentials are sent to HTTPS.</summary>
public sealed class AccountResourceDisclosure
{
    public string AbsoluteDataRoot { get; }
    public string InventoryPath { get; }
    public string BundleCacheDirectory { get; }
    public string ItemImageCachePath { get; }
    public string PortraitCachePath { get; }
    public string VersionMapUrl => $"https://{OfficialResourceOrigin.DefaultHost}/WLN/TW/ResourcePath_PC.dat";
    public string ResourceUrlPrefix => $"https://{OfficialResourceOrigin.DefaultHost}/WLN/TW/";
    public string Purpose => "Acquire official HTTPS version metadata, DataPackage and MainPackage " +
        "manifests, required bundles and supported optional item-image and reviewed portrait bundles; bootstrap and independently read back the fixed SQLite resource inventory, item-image cache and portrait cache.";
    public string Writes => "Create directories, persist verified bundles and temporary files in BundleCacheDirectory, " +
        "and create or update InventoryPath, ItemImageCachePath and PortraitCachePath (including SQLite journal files). Stop does not undo completed writes.";
    internal AccountResourceDisclosure(string absoluteDataRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absoluteDataRoot);
        if (!Path.IsPathFullyQualified(absoluteDataRoot))
            throw new ArgumentException("An absolute data root is required.", nameof(absoluteDataRoot));
        AbsoluteDataRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(absoluteDataRoot));
        InventoryPath = Path.Combine(AbsoluteDataRoot, "official_sync", "derived_catalogs", "resource_inventory.sqlite3");
        ItemImageCachePath = Path.Combine(AbsoluteDataRoot, "official_sync", "derived_catalogs", "core_item_images_v1.sqlite3");
        PortraitCachePath = Path.Combine(AbsoluteDataRoot, "official_sync", "derived_catalogs", "core_portraits_v1.sqlite3");
        BundleCacheDirectory = Path.Combine(AbsoluteDataRoot, "official_sync", "bundles");
    }
    public override string ToString() => "Resource operation disclosure (local paths redacted)";
}
