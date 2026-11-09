using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Lala.Core.Catalogs;

namespace Lala.Core.World;

/// <summary>Caller-claimed Python manifest identity, not OfficialCatalogObservation.CatalogKey.
/// Equality is compatibility only: it proves neither cache integrity nor official provenance.</summary>
public sealed record OfflineNavigationIdentity
{
    public string ClaimedManifestKey { get; }
    public string ClaimedDataVersion { get; }
    public OfflineNavigationIdentity(string claimedManifestKey, string claimedDataVersion)
    {
        if (claimedManifestKey is null || claimedManifestKey.Length != 64 ||
            claimedManifestKey.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f')) ||
            string.IsNullOrEmpty(claimedDataVersion) || claimedDataVersion.Length > 100 ||
            claimedDataVersion.Any(c => c is < ' ' or > '~'))
            throw new NavigationException("Invalid caller-supplied navigation identity");
        ClaimedManifestKey = claimedManifestKey; ClaimedDataVersion = claimedDataVersion;
    }
}

/// <summary>Owned stage rows in the caller-supplied original binary order. No source authentication.</summary>
public sealed class OfflineNavigationStages
{
    public OfflineNavigationIdentity Identity { get; }
    public ImmutableArray<StageDataRow> OriginalOrder { get; }
    public ImmutableDictionary<ushort, StageDataRow> Rows { get; }
    public OfflineNavigationStages(OfflineNavigationIdentity identity, IEnumerable<StageDataRow> originalBinaryOrder,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(identity); ArgumentNullException.ThrowIfNull(originalBinaryOrder);
        Identity = identity;
        var ordered = ImmutableArray.CreateBuilder<StageDataRow>();
        var rows = ImmutableDictionary.CreateBuilder<ushort, StageDataRow>();
        foreach (var row in originalBinaryOrder)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (ordered.Count == StageDataParser.MaxRecords || row is null || rows.ContainsKey(row.Id))
                throw new NavigationException("Invalid, duplicate or oversized navigation stage rows");
            ordered.Add(row); rows.Add(row.Id, row);
        }
        cancellationToken.ThrowIfCancellationRequested();
        OriginalOrder = ordered.ToImmutable(); Rows = rows.ToImmutable();
    }
}

/// <summary>A bounded, immutable caller-supplied mesh. This does not load/review raw cache bytes,
/// verify model digests, activate resources, or establish provenance.</summary>
public sealed class OfflineNavigationCacheEntry
{
    public const int MaxFaces = 10_000;
    public const int MaxConnections = 100_000;
    public OfflineNavigationIdentity Identity { get; }
    public ushort ModelId { get; }
    public NavigationPoint Origin { get; }
    public PreviewNavigationMesh Mesh { get; }
    public OfflineNavigationCacheEntry(OfflineNavigationIdentity identity, ushort modelId,
        NavigationPoint origin, PreviewNavigationMesh mesh)
    {
        ArgumentNullException.ThrowIfNull(identity); ArgumentNullException.ThrowIfNull(mesh);
        NavigationValidation.RequirePoint(origin);
        if (mesh.SceneId != ModelScene(modelId)) throw new NavigationException("Navigation cache model/scene mismatch");
        if (mesh.Faces.Count > MaxFaces || mesh.ConnectionCount > MaxConnections)
            throw new NavigationException("Navigation cache geometry budget exceeded");
        Identity = identity; ModelId = modelId; Origin = origin; Mesh = mesh;
    }
    internal static string ModelScene(ushort model) => "M" + model.ToString("D5", CultureInfo.InvariantCulture);
}

/// <summary>Logical map XY, retaining fractions. Not a packet coordinate or movement command.</summary>
public readonly record struct LogicalNavigationCoordinate(double X, double Y);

/// <summary>Historical offline composition from supplied claims. It never stays current on its own,
/// and must not be used as a runtime lease, trusted source, or movement permission.</summary>
public sealed class OfflineLogicalNavigationRoute
{
    public ushort LogicalMap { get; }
    public ushort StageId { get; }
    public ushort ModelId { get; }
    public OfflineNavigationIdentity Identity { get; }
    public WorldNavigationSnapshot? InputNavigation { get; }
    /// <summary>Reused geometry result; its legacy source labels describe algorithm semantics,
    /// not verified provenance. Use this composition's SourceProvenanceVerified boundary.</summary>
    public NavigationRoute MeshRoute { get; }
    public ImmutableArray<LogicalNavigationCoordinate> LogicalPoints { get; }
    public string NavigationSource => "caller_supplied_offline_navigation_preview";
    public bool IsHistorical => true;
    public bool SourceProvenanceVerified => false;
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    public bool LiveMovementVerified => false;
    public bool NetworkCoordinatesVerified => false;
    public bool RuntimeObstaclesApplied => false;
    internal OfflineLogicalNavigationRoute(ushort logicalMap, StageDataRow stage, OfflineNavigationIdentity identity,
        WorldNavigationSnapshot? navigation, NavigationRoute route, ImmutableArray<LogicalNavigationCoordinate> logicalPoints)
    {
        LogicalMap = logicalMap; StageId = stage.Id; ModelId = stage.ModelId; Identity = identity;
        InputNavigation = navigation; MeshRoute = route; LogicalPoints = logicalPoints;
    }
}

/// <summary>Cache-only port of PreviewRepository.route/load composition. No I/O, download, database,
/// admission, movement, session ownership, or dynamic obstacle rebuild. Supplied claims are not trust.</summary>
public sealed class OfflineLogicalNavigationPreview
{
    // Exact retained Python review pins. There is deliberately no public registry override.
    internal const string ReviewedCoordinateKey = "b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6";
    internal const string ReviewedStageOrder = "1f1bd5ad718542a8469812a5cdabc12155a24ac01fdac6e2dc2506d82c3c41dd";
    public const int MaxCacheEntries = 256;
    public const int MaxTotalFaces = 100_000;
    public const int MaxTotalConnections = 1_000_000;
    private readonly ImmutableDictionary<(ushort Model, string Mode), OfflineNavigationCacheEntry> cache;
    private readonly string reviewedStageOrder;
    public OfflineNavigationIdentity Identity { get; }
    public OfflineNavigationStages Stages { get; }

    public OfflineLogicalNavigationPreview(OfflineNavigationIdentity identity, OfflineNavigationStages stages,
        IEnumerable<OfflineNavigationCacheEntry> cacheEntries, CancellationToken cancellationToken = default)
        : this(identity, stages, cacheEntries, ReviewedStageOrder, cancellationToken) { }

    // Synthetic differential tests can review their own order privately, never via the public API.
    internal OfflineLogicalNavigationPreview(OfflineNavigationIdentity identity, OfflineNavigationStages stages,
        IEnumerable<OfflineNavigationCacheEntry> cacheEntries, string reviewedStageOrder, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(identity); ArgumentNullException.ThrowIfNull(stages);
        ArgumentNullException.ThrowIfNull(cacheEntries);
        if (identity != stages.Identity) throw new NavigationException("Navigation stage catalog/version mismatch");
        Identity = identity; Stages = stages; this.reviewedStageOrder = reviewedStageOrder;
        var entries = ImmutableDictionary.CreateBuilder<(ushort, string), OfflineNavigationCacheEntry>();
        var faces = 0; long connections = 0;
        foreach (var entry in cacheEntries)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (entry is null || entry.Identity != identity) throw new NavigationException("Navigation cache catalog/version mismatch");
            var key = (entry.ModelId, entry.Mesh.TravelMode);
            if (entries.Count == MaxCacheEntries || entries.ContainsKey(key) || (faces += entry.Mesh.Faces.Count) > MaxTotalFaces ||
                (connections += entry.Mesh.ConnectionCount) > MaxTotalConnections)
                throw new NavigationException("Duplicate or oversized navigation cache entries");
            entries.Add(key, entry);
        }
        cancellationToken.ThrowIfCancellationRequested();
        cache = entries.ToImmutable();
    }

    /// <summary>Select only an exact supplied model and travel mode, with no old-version fallback.</summary>
    public OfflineNavigationCacheEntry Load(ushort model, string travelMode = "land", CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        RequireGeneralNavigation(model: model);
        if (travelMode is not ("land" or "sea" or "sky")) throw new NavigationException("未驗證的通行模式。");
        if (!cache.TryGetValue((model, travelMode), out var entry))
            throw new NavigationException("此版本官方導航尚未同步，未使用舊版幾何。");
        return entry;
    }

    public OfflineLogicalNavigationRoute Route(ushort logicalMap, LogicalNavigationCoordinate start, LogicalNavigationCoordinate end,
        double? startHeight = null, double? endHeight = null, WorldNavigationSnapshot? navigation = null,
        string travelMode = "land", bool smooth = false, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (Identity.ClaimedManifestKey != ReviewedCoordinateKey)
            throw new NavigationException("此版本的官方座標邏輯尚未完成驗證。");
        RequireGeneralNavigation(scene: logicalMap);
        if (navigation is { Stale: true } && navigation.Scene == logicalMap)
            throw new NavigationException("場景障礙已變更，尚未完成官方動態幾何重建。");
        if (!Stages.Rows.TryGetValue(logicalMap, out var stage) && logicalMap is >= 61501 and <= 62000)
        {
            var aliases = InstanceAliases(cancellationToken);
            if (aliases.TryGetValue(logicalMap, out var stageId)) Stages.Rows.TryGetValue(stageId, out stage);
        }
        if (stage is null) throw new NavigationException("官方場景表沒有此 ID；副本別名尚未確認。");
        var entry = Load(stage.ModelId, travelMode, cancellationToken);
        var offset = stage.MapHeight == ushort.MaxValue ? 6992 : stage.MapHeight;
        NavigationCoordinate ConvertPoint(LogicalNavigationCoordinate point)
        {
            NavigationValidation.RequirePoint(new(point.X, 0, point.Y));
            var converted = new NavigationCoordinate(point.X * 10 - entry.Origin.X, (offset - point.Y) * 10 - entry.Origin.Z);
            NavigationValidation.RequirePoint(new(converted.X, 0, converted.Z));
            return converted;
        }
        var route = entry.Mesh.Route(ConvertPoint(start), ConvertPoint(end), startHeight, endHeight, smooth, cancellationToken);
        var logicalPoints = ImmutableArray.CreateBuilder<LogicalNavigationCoordinate>(route.Points.Count);
        foreach (var point in route.Points)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var logical = new LogicalNavigationCoordinate((point.X + entry.Origin.X) / 10, offset - (point.Z + entry.Origin.Z) / 10);
            NavigationValidation.RequirePoint(new(logical.X, 0, logical.Y));
            logicalPoints.Add(logical);
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(logicalMap, stage, Identity, navigation, route, logicalPoints.ToImmutable());
    }

    private Dictionary<ushort, ushort> InstanceAliases(CancellationToken token)
    {
        var order = new StringBuilder("[");
        for (var i = 0; i < Stages.OriginalOrder.Length; i++)
        {
            token.ThrowIfCancellationRequested();
            if (i != 0) order.Append(',');
            order.Append(Stages.OriginalOrder[i].Id.ToString(CultureInfo.InvariantCulture));
        }
        order.Append(']');
        if (Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(order.ToString()))) != reviewedStageOrder)
            throw new NavigationException("副本場景的官方原始順序未通過驗證。");
        var aliases = new Dictionary<ushort, ushort>(); var next = 61501;
        foreach (var row in Stages.OriginalOrder)
        {
            token.ThrowIfCancellationRequested();
            // StageDataRow's byte types already enforce source member/capacity bounds.
            if (row.MaxMembers == 0) continue;
            for (var room = 0; room < row.RoomCapacity; room++)
            {
                token.ThrowIfCancellationRequested();
                if (next > 62000 || Stages.Rows.ContainsKey((ushort)next))
                    throw new NavigationException("副本場景別名衝突或超出已審核範圍。");
                aliases.Add((ushort)next++, row.Id);
            }
        }
        return aliases;
    }

    private static void RequireGeneralNavigation(ushort? scene = null, ushort? model = null)
    {
        if (scene is 10000 or 10298 or 10299 or >= 63501 and <= 65500 || model is 10000 or 10004 or 10005)
            throw new NavigationException("玩家小屋僅支援進入與離開，不提供屋內自動導航。");
    }
}
