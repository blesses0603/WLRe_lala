using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Bootstrap_rejects_generated_baseline_before_source_or_expression_execution()
    {
        using var fixture = new Fixture();
        await using (var seed = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()))
            Published(await seed.BootstrapAndRefreshAsync(), seed);
        ResourceInventoryReadShapeTests.ReplaceWithGeneratedColumn(fixture.Inventory, "versions", "catalog_key");
        byte[] before = fixture.Bytes(); int probes = 0; var source = new Source();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            WrapConnection = c => ResourceInventoryReadShapeTests.WithReadProbes(c, () => probes++)
        });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.IsType<InvalidDataException>(result.Failure); Assert.False(result.StorageAttempted); Assert.False(result.WasPublished);
        Assert.Equal(0, source.Observations); Assert.Equal(0, probes); Assert.Equal(before, fixture.Bytes());
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Matching_generated_payload_does_not_pass_inspection_or_fresh_runtime_readback(bool stored)
    {
        using var fixture = new Fixture();
        await using (var seed = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()))
            Published(await seed.BootstrapAndRefreshAsync(), seed);
        ResourceInventoryReadShapeTests.ReplaceWithGeneratedColumn(fixture.Inventory, "resources", "data", stored, useProbe: false);
        byte[] before = fixture.Bytes();
        var inspection = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.Invalid, inspection.Status); Assert.False(inspection.RuntimeAdmitted);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await Assert.ThrowsAsync<InvalidDataException>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.Equal(before, fixture.Bytes());
    }
}
