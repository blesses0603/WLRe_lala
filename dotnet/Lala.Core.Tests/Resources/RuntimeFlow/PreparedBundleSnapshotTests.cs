using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class OfflineBundleRuntimePreparationTests
{
    [Fact]
    public async Task Prepared_cache_sources_are_immutable_owned_snapshots_of_accepted_optional_closures()
    {
        var source = WithOptionalInstances(includeDaily: true);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Equal(new[] { "all-ten.bundle", "optional-daily.bundle", "optional-instances.bundle" },
            result.VerifiedSources.Select(handle => handle.Spec.Name).Order(StringComparer.Ordinal));
        Assert.Equal(source.Bundles.Values.Sum(bytes => (long)bytes.Length), result.VerifiedSources.Sum(handle => handle.Spec.Size));
        Assert.True(result.VerifiedSources.Sum(handle => handle.Spec.Size) <= BundleSourcePreparation.MaximumRetainedBytes);
        var list = (IList<VerifiedBundleSource>)result.VerifiedSources;
        Assert.True(list.IsReadOnly); Assert.Throws<NotSupportedException>(list.Clear);
        foreach (var handle in result.VerifiedSources)
        {
            byte[] expected = source.Bundles[handle.Spec.Name].ToArray();
            Array.Fill(source.Bundles[handle.Spec.Name], (byte)0xff);
            using var owned = handle.OpenRead(); using var copy = new MemoryStream();
            owned.CopyTo(copy);
            Assert.False(owned.CanWrite); Assert.Equal(expected, copy.ToArray());
        }
        DailyFlowAssertions.Present(result.Candidate); InstanceFlowAssertions.Present(result.Candidate);
    }

    [Fact]
    public async Task Shared_required_and_optional_bundle_is_retained_once()
    {
        var source = new Script("all-ten-daily-instances.bundle");
        source.Data = RuntimeFlowFixtures.Manifest(source.Bundles, includeDaily: true, includeInstances: true);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Equal("all-ten-daily-instances.bundle", Assert.Single(result.VerifiedSources).Spec.Name);
        DailyFlowAssertions.Present(result.Candidate); InstanceFlowAssertions.Present(result.Candidate);
    }

    [Theory]
    [InlineData("skill")]
    [InlineData("daily")]
    [InlineData("instances")]
    public async Task Rejected_optional_feature_does_not_extend_prepared_cache_snapshot(string feature)
    {
        var source = feature switch
        {
            "skill" => WithOptionalSkill(),
            "daily" => WithOptionalDaily("optional-daily-malformed-task.bundle"),
            _ => WithOptionalInstances("optional-instances-malformed-dungeon.bundle")
        };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal("all-ten.bundle", Assert.Single(result.VerifiedSources).Spec.Name);
    }

    [Fact]
    public async Task Accepted_daily_dependency_is_retained_even_when_first_acquired_for_rejected_skill()
    {
        var source = WithOptionalDaily(includeSkill: true, shareDailyWithSkill: true);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Null(result.Candidate.OptionalSkills); DailyFlowAssertions.Present(result.Candidate);
        Assert.Equal(3, result.DownloadCount);
        Assert.Equal(new[] { "all-ten.bundle", "optional-daily.bundle" },
            result.VerifiedSources.Select(handle => handle.Spec.Name).Order(StringComparer.Ordinal));
    }
}
