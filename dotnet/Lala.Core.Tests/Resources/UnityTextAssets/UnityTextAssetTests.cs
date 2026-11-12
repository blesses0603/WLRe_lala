using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class UnityTextAssetTests
{
    [Theory]
    [InlineData("owned-v6-c0.bundle")]
    [InlineData("owned-v7-c0.bundle")]
    [InlineData("owned-v8-c0.bundle")]
    [InlineData("owned-v8-c2.bundle")]
    [InlineData("owned-v8-c3.bundle")]
    [InlineData("owned-multiblock.bundle")]
    public void GenuineUnityPyWriterFixturesExtractExactBinaryPayload(string id)
    {
        byte[] bundle = UnityFixtures.File(id); using var evidence = JsonDocument.Parse(UnityFixtures.File("evidence.json"));
        Assert.Equal(evidence.RootElement.GetProperty("files").GetProperty(id).GetProperty("sha256").GetString(), Convert.ToHexStringLower(SHA256.HashData(bundle)));
        Assert.Equal(UnityFixtures.Payload, UnityFixtures.Extract(bundle));
    }
    [Theory]
    [InlineData(0x40)] [InlineData(0xc0)] [InlineData(0x240)] [InlineData(0x2c0)]
    public void FrontEndAndPaddingLayoutsAreExact(int flags) => Assert.Equal(UnityFixtures.Payload,
        UnityFixtures.Extract(UnityFixtures.Wrap(UnityFixtures.File("owned.assets"), flags: (uint)flags)));

    [Theory]
    [InlineData("Owned.bytes")] [InlineData("Assets/ResourcesBuild/Data/owned.bytes")]
    [InlineData("assets/ResourcesBuild/Data/Owned.bytes")] [InlineData("Assets/ResourcesBuild/Data/Other/Owned.bytes")]
    public void ExactFullCaseSensitivePathRequired(string path) => Assert.Throws<UnityTextAssetException>(() =>
        UnityTextAssetExtractor.Extract(path, [UnityFixtures.Source(UnityFixtures.File("owned-v8-c3.bundle"))]));

    [Theory]
    [InlineData("bad-name.assets")] [InlineData("wrong-class.assets")]
    [InlineData("duplicate.assets")] [InlineData("empty-script.assets")]
    public void NameClassDuplicateAndEmptyScriptFailClosed(string id) => Assert.Throws<UnityTextAssetException>(() => UnityFixtures.Extract(UnityFixtures.Wrap(UnityFixtures.File(id))));

    [Fact]
    public void ExactFilenameAndStemNamesAccepted() => Assert.Equal(UnityFixtures.Payload, UnityFixtures.Extract(UnityFixtures.Wrap(UnityFixtures.File("filename-name.assets"))));

    [Fact]
    public void DuplicateMatchesAcrossBundlesRejectEvenSameCabAndObject()
    {
        byte[] b = UnityFixtures.File("owned-v8-c3.bundle");
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, [UnityFixtures.Source(b, "a.bundle"), UnityFixtures.Source(b, "b.bundle")]));
    }
    [Fact]
    public void ExactFileTupleAndExplicitExternalAllowlistResolveSameCabNames()
    {
        var a = UnityFixtures.Source(UnityFixtures.Wrap(UnityFixtures.File("external.assets")), "a.bundle");
        var b = UnityFixtures.Source(UnityFixtures.Wrap(UnityFixtures.File("target.assets")), "b.bundle");
        var mapping = new UnityExternalBinding(new("a.bundle", "CAB-owned"), "archive:/CAB-owned/CAB-owned", new("b.bundle", "CAB-owned"));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, [a, b]));
        Assert.Equal(UnityFixtures.Payload, UnityTextAssetExtractor.Extract(UnityFixtures.Path, [a, b], [mapping]));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, [a, b], [mapping with { ExternalPath = "archive:/cab-owned/CAB-owned" }]));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, [a, b], [mapping with { Target = new("b.bundle", "cab-owned") }]));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, [a, b], [mapping, mapping]));
    }

    [Theory]
    [InlineData("type_count", -1, 0)] [InlineData("type_count", int.MaxValue, 0)]
    [InlineData("first_class", 114, 0)] [InlineData("first_tree_count", int.MaxValue, 0)]
    [InlineData("first_tree_strings", int.MaxValue, 0)] [InlineData("first_node", int.MaxValue, 4)]
    [InlineData("object_count", 16385, 0)] [InlineData("first_object", -1, 8)]
    [InlineData("first_object", int.MaxValue, 16)] [InlineData("first_object", 2, 20)]
    [InlineData("second_object", 1, 0)] [InlineData("second_object", 0, 8)]
    [InlineData("script_count", 1, 0)] [InlineData("external_count", 129, 0)]
    [InlineData("reference_count", 1, 0)] [InlineData("preload_count", int.MaxValue, 0)]
    [InlineData("container_count", 100001, 0)] [InlineData("container_path_length", 1025, 0)]
    [InlineData("container_file_id", 1, 0)] [InlineData("container_path_id", 9999, 0)]
    [InlineData("script_length", -1, 0)] [InlineData("script_length", 16777217, 0)]
    public void MalformedAllocationDrivingFieldsRejectBeforeAllocation(string field, int value, int delta)
    { Assert.Throws<UnityTextAssetException>(() => UnityFixtures.Extract(UnityFixtures.Wrap(UnityFixtures.Patch(field, value, delta)))); }

    [Theory]
    [InlineData("stripped")] [InlineData("node-depth")] [InlineData("node-array")] [InlineData("node-align")]
    [InlineData("endian")] [InlineData("format")] [InlineData("metadata-size")]
    [InlineData("declared-length")] [InlineData("data-offset")]
    public void UnsupportedMetadataIsRejected(string id)
    {
        byte[] a = UnityFixtures.File("owned.assets");
        switch (id)
        {
            case "stripped": a[UnityFixtures.Offset("type_enabled")] = 0; break;
            case "node-depth": a[UnityFixtures.Offset("first_node") + 2] = 255; break;
            case "node-array": a[UnityFixtures.Offset("first_node") + 3] = 1; break;
            case "node-align": a[UnityFixtures.Offset("first_node") + 21] ^= 0x40; break;
            case "endian": a[16] = 1; break;
            case "format": a[11] = 23; break;
            case "metadata-size": BinaryPrimitives.WriteUInt32BigEndian(a.AsSpan(20), 4 * 1024 * 1024 + 1); break;
            case "declared-length": a[31] ^= 1; break;
            case "data-offset": BinaryPrimitives.WriteInt64BigEndian(a.AsSpan(32), long.MaxValue); break;
        }
        Assert.Throws<UnityTextAssetException>(() => UnityFixtures.Extract(UnityFixtures.Wrap(a)));
    }

    [Theory]
    [InlineData("version")] [InlineData("length")] [InlineData("info-size")] [InlineData("lzma")]
    [InlineData("encrypted")] [InlineData("block-count")] [InlineData("block-length")]
    [InlineData("directory-count")] [InlineData("directory-offset")] [InlineData("directory-size")]
    [InlineData("directory-flags")] [InlineData("directory-path")]
    public void MalformedBundleHeaderAndDirectoryReject(string id)
    {
        byte[] b = UnityFixtures.File("owned-v8-c0.bundle");
        switch (id)
        {
            case "version": b[11] = 9; break;
            case "length": b[37] ^= 1; break;
            case "info-size": BinaryPrimitives.WriteInt32BigEndian(b.AsSpan(38), int.MaxValue); break;
            case "lzma": b[49] = 0x41; break;
            case "encrypted": b[48] = 4; break;
            case "block-count": BinaryPrimitives.WriteInt32BigEndian(b.AsSpan(80), int.MaxValue); break;
            case "block-length": BinaryPrimitives.WriteInt32BigEndian(b.AsSpan(84), int.MaxValue); break;
            case "directory-count": BinaryPrimitives.WriteInt32BigEndian(b.AsSpan(94), int.MaxValue); break;
            case "directory-offset": b[98] = 0xff; break;
            case "directory-size": b[106] = 0x7f; break;
            case "directory-flags": b[117] = 0; break;
            case "directory-path": b[118] = (byte)'/'; break;
        }
        Assert.Throws<UnityTextAssetException>(() => UnityFixtures.Extract(b));
    }

    [Theory]
    [InlineData("14410100", 9)] [InlineData("00", 1)] [InlineData("0f", 8)] [InlineData("f0ff", 10)]
    [InlineData("10000000", 5)] [InlineData("10410200", 5)] [InlineData("10410100", 4)]
    [InlineData("f0ffffffffffffffffffffffffffffffff00", 32)]
    public void MalformedLz4Rejects(string hex, int length) => Assert.Throws<UnityTextAssetException>(() =>
        BoundedUnityBundle.ExpandInto(Convert.FromHexString(hex), new byte[length], 3, default));

    [Fact]
    public void Lz4OverlapAndCancellationAreBounded()
    {
        byte[] output = new byte[19]; BoundedUnityBundle.ExpandInto(Convert.FromHexString("19410100504242424242"), output, 3, default);
        Assert.Equal("AAAAAAAAAAAAAABBBBB", System.Text.Encoding.ASCII.GetString(output));
        using var canceled = new CancellationTokenSource(); canceled.Cancel();
        Assert.Throws<OperationCanceledException>(() => BoundedUnityBundle.ExpandInto([0], new byte[4], 3, canceled.Token));
        Assert.Throws<OperationCanceledException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path,
            [UnityFixtures.Source(UnityFixtures.File("owned-v8-c3.bundle"))], cancellationToken: canceled.Token));
    }

    [Fact]
    public void OwnedInputAndReturnedPayloadDoNotAlias()
    {
        byte[] input = UnityFixtures.File("owned-v8-c3.bundle"); var owned = UnityFixtures.Source(input); input.AsSpan().Clear();
        byte[] first = UnityTextAssetExtractor.Extract(UnityFixtures.Path, [owned]); first.AsSpan().Clear();
        Assert.Equal(UnityFixtures.Payload, UnityTextAssetExtractor.Extract(UnityFixtures.Path, [owned]));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, [owned, owned]));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, []));
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(UnityFixtures.Path, Enumerable.Repeat(owned, 25).ToArray()));
    }
    [Fact]
    public void TwentyFourDistinctBundleIdentitiesAreAcceptedWithoutCabAliasing()
    {
        var sources = new List<VerifiedBundleSource> { UnityFixtures.Source(UnityFixtures.File("owned-v8-c3.bundle"), "main.bundle") };
        byte[] unused = UnityFixtures.Wrap(UnityFixtures.File("target.assets"));
        for (int i = 0; i < 23; i++) sources.Add(UnityFixtures.Source(unused, $"unused{i}.bundle"));
        Assert.Equal(UnityFixtures.Payload, UnityTextAssetExtractor.Extract(UnityFixtures.Path, sources));
    }

}
