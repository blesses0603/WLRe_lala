namespace Lala.Core.Resources;

// Immutable verified source handles; no filesystem paths or caller-provided pixels on production.
internal sealed class PortraitRuntimeBatch
{
    internal PortraitCachePlan Plan { get; }
    internal PortraitMapping? Mapping { get; private init; }
    private readonly Func<Action<PortraitImageCandidate>, CancellationToken, PortraitBatchReceipt> rebuild;
    private readonly PortraitBatchReceipt expected;
    private PortraitRuntimeBatch(PortraitCachePlan plan,
        Func<Action<PortraitImageCandidate>, CancellationToken, PortraitBatchReceipt> rebuild, CancellationToken token)
    {
        Plan = plan; this.rebuild = rebuild;
        // Validate the entire optional decode before retaining its sources for caching.
        expected = rebuild(_ => { }, token);
        BoundedSpritePixels.Check(expected.SourceFingerprint == plan.SourceFingerprint && expected.Count == plan.Keys.Count,
            "Portrait preparation receipt mismatch");
    }
    internal static PortraitRuntimeBatch Create(PortraitSourcePlan.VerifiedPortraitSources sources,
        ReadOnlyMemory<byte> npcRaw, string dataPackageVersion, CancellationToken token)
    {
        var mapping = PortraitMapping.Create(npcRaw.Span, dataPackageVersion, token);
        return new(PortraitCachePlan.FromSources(sources), (consume, ct) => PortraitBatch.Process(sources, consume, ct), token) { Mapping = mapping };
    }
    // Explicit synthetic seam, reachable only through offline owner hooks. No pin replacement.
    internal static PortraitRuntimeBatch ForOfflineTests(PortraitCachePlan plan,
        Func<Action<PortraitImageCandidate>, CancellationToken, PortraitBatchReceipt> rebuild)
        => new(plan, rebuild, default);
    internal PortraitBatchReceipt Rebuild(Action<PortraitImageCandidate> consume, CancellationToken token)
    {
        var actual = rebuild(consume, token);
        BoundedSpritePixels.Check(actual == expected, "Portrait batch changed since preparation");
        return actual;
    }
}
