using System.Buffers.Binary;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

[Collection("Unity extraction memory bounds")]
public sealed class UnityBoundariesTests
{
    [Theory]
    [InlineData("expansion")] [InlineData("files")] [InlineData("metadata")]
    [InlineData("objects")] [InlineData("entries")] [InlineData("identities")]
    public void AggregateBudgetsRejectBeforeTheirNextGrowth(string id)
    {
        var budget = new UnityExtractionBudget();
        switch (id)
        {
            case "expansion": budget.ExpandedBytes = BoundedUnityBundle.MaximumTotalBytes; break;
            case "files": budget.Files = 128; break;
            case "metadata": budget.MetadataBytes = 16 * 1024 * 1024; break;
            case "objects": budget.Objects = 16_384; break;
            case "entries": budget.ContainerEntries = 100_000; break;
            case "identities": budget.ContainerIdentityBytes = 8 * 1024 * 1024; break;
        }
        if (id is "expansion" or "files") Assert.Throws<UnityTextAssetException>(() =>
            BoundedUnityBundle.Read(UnityFixtures.File("owned-v8-c3.bundle"), budget, default));
        else Assert.Throws<UnityTextAssetException>(() => BoundedSerializedFile.Read(new("a.bundle", "CAB-owned"), UnityFixtures.File("owned.assets"), budget, default));
    }
    [Fact]
    public void AggregateExactBoundariesAccept()
    {
        byte[] assets = UnityFixtures.File("owned.assets");
        var budget = new UnityExtractionBudget
        {
            ExpandedBytes = BoundedUnityBundle.MaximumTotalBytes - assets.Length, Files = 127,
            MetadataBytes = 16 * 1024 * 1024 - BinaryPrimitives.ReadUInt32BigEndian(assets.AsSpan(20)),
            Objects = 16_382, ContainerEntries = 99_999, ContainerIdentityBytes = 8 * 1024 * 1024 - UnityFixtures.Path.Length
        };
        var entries = BoundedUnityBundle.Read(UnityFixtures.File("owned-v8-c3.bundle"), budget, default);
        var file = BoundedSerializedFile.Read(new("a.bundle", "CAB-owned"), entries[0].Bytes, budget, default);
        Assert.Single(file.Container); Assert.Equal(BoundedUnityBundle.MaximumTotalBytes, budget.ExpandedBytes);
        Assert.Equal(16 * 1024 * 1024, budget.MetadataBytes); Assert.Equal(16_384, budget.Objects);
        Assert.Equal(100_000, budget.ContainerEntries); Assert.Equal(8 * 1024 * 1024, budget.ContainerIdentityBytes);
    }
    [Fact]
    public void SuffixTreeStringsAndUnusedEmptyTextAssetsAreValid()
    {
        var main = UnityFixtures.Source(UnityFixtures.Wrap(UnityFixtures.File("suffix.assets")), "main.bundle");
        var unused = UnityFixtures.Source(UnityFixtures.Wrap(UnityFixtures.File("unused-empty.assets")), "unused.bundle");
        Assert.Equal(UnityFixtures.Payload, UnityTextAssetExtractor.Extract(UnityFixtures.Path, [main, unused]));
    }
    [Fact]
    public async Task CancellationDuringLongLz4MatchEitherCancelsOrCompletesExactBytes()
    {
        const int length = 16 * 1024 * 1024;
        // One literal A, one long overlapping match, five trailing B literals.
        // The output buffer is fixed before execution, not enlarged by the stream.
        using var packed = new MemoryStream(); packed.Write([0x1f, (byte)'A', 1, 0]);
        int extension = length - 6 - 4 - 15;
        while (extension >= 255) { packed.WriteByte(255); extension -= 255; }
        packed.WriteByte((byte)extension); packed.Write([0x50, (byte)'B', (byte)'B', (byte)'B', (byte)'B', (byte)'B']);
        byte[] input = packed.ToArray(), output = new byte[length]; using var source = new CancellationTokenSource();
        var task = Task.Run(() => BoundedUnityBundle.ExpandInto(input, output, 3, source.Token));
        // Wait until the overlapping copy actually made progress, then cancel.
        var deadline = DateTime.UtcNow.AddSeconds(5);
        while (Volatile.Read(ref output[4096]) == 0 && !task.IsCompleted && DateTime.UtcNow < deadline) await Task.Yield();
        source.Cancel();
        try
        {
            await task; // Completion may win the scheduler race with cancellation.
            Assert.Equal(-1, output.AsSpan(0, output.Length - 5).IndexOfAnyExcept((byte)'A'));
            Assert.Equal("BBBBB", System.Text.Encoding.ASCII.GetString(output[^5..]));
        }
        catch (OperationCanceledException) { Assert.NotEqual((byte)0, output[4096]); }
    }
    [Fact]
    public void EveryTruncationAndSeededMalformedProbeStaysInsideDomainFailures()
    {
        byte[] bundle = UnityFixtures.File("owned-v8-c3.bundle");
        for (int size = 0; size < bundle.Length; size++)
            Assert.Throws<UnityTextAssetException>(() => BoundedUnityBundle.Read(bundle.AsMemory(0, size), new(), default));
        byte[] assets = UnityFixtures.File("owned.assets");
        for (int size = 0; size < assets.Length; size++)
            Assert.Throws<UnityTextAssetException>(() => BoundedSerializedFile.Read(new("a.bundle", "CAB-owned"), assets.AsMemory(0, size), new(), default));
        int requiredEnd = UnityFixtures.Offset("text") + BinaryPrimitives.ReadInt32LittleEndian(assets.AsSpan(UnityFixtures.Offset("second_object") + 16));
        for (int size = UnityFixtures.Offset("container"); size < requiredEnd; size++)
        {
            byte[] truncated = assets[..size]; BinaryPrimitives.WriteInt64BigEndian(truncated.AsSpan(24), size);
            Assert.Throws<UnityTextAssetException>(() => BoundedSerializedFile.Read(new("a.bundle", "CAB-owned"), truncated, new(), default));
        }
        var random = new Random(0x14249);
        for (int i = 0; i < 512; i++)
        {
            byte[] changed = (byte[])assets.Clone(); int offset = random.Next(changed.Length); changed[offset] ^= (byte)random.Next(1, 256);
            try { BoundedSerializedFile.Read(new("a.bundle", "CAB-owned"), changed, new(), default); }
            catch (UnityTextAssetException) { } // Inert metadata/payload changes can remain valid.
        }
    }

}

[CollectionDefinition("Unity extraction memory bounds", DisableParallelization = true)]
public sealed class UnityExtractionMemoryCollection;
