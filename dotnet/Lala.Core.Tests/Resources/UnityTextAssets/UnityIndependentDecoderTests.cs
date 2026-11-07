using AssetsTools.NET.Extra;
using System.Security.Cryptography;
using System.Text.Json;
using Xunit;

namespace Lala.Core.Tests.Resources;

// Only retained owned, hash-verified fixtures enter the upstream decoder. Malformed
// corpus inputs MUST NOT use this unbounded independent decoder.
public sealed class UnityIndependentDecoderTests
{
    [Theory]
    [InlineData("owned.assets", 1, "Owned")]
    [InlineData("suffix.assets", 1, "Owned")]
    [InlineData("duplicate.assets", 2, "Owned")]
    [InlineData("target.assets", 0, "Owned")]
    [InlineData("external.assets", 1, "Owned")]
    [InlineData("filename-name.assets", 1, "Owned.bytes")]
    public void PinnedAssetsToolsIndependentlyReadsGenuineWriterFiles(string id, int entries, string name)
    {
        var manager = new AssetsManager();
        byte[] owned = UnityFixtures.File(id);
        using var evidence = JsonDocument.Parse(UnityFixtures.File("evidence.json"));
        Assert.Equal(evidence.RootElement.GetProperty("files").GetProperty(id).GetProperty("sha256").GetString(), Convert.ToHexStringLower(SHA256.HashData(owned)));
        using var stream = new MemoryStream(owned, writable: false);
        try
        {
            var instance = manager.LoadAssetsFile(stream, "owned", loadDeps: false);
            Assert.Equal(22U, instance.file.Header.Version);
            Assert.True(instance.file.Metadata.TypeTreeEnabled);
            var text = manager.GetBaseField(instance, instance.file.Metadata.AssetInfos.Single(x => x.TypeId == 49));
            Assert.Equal(name, text["m_Name"].AsString);
            Assert.Equal(UnityFixtures.Payload, text["m_Script"].Value.AsByteArray);
            var bundle = manager.GetBaseField(instance, instance.file.Metadata.AssetInfos.Single(x => x.TypeId == 142));
            var pairs = bundle["m_Container"]["Array"].Children;
            Assert.Equal(entries, pairs.Count);
            Assert.All(pairs, pair => Assert.Equal(UnityFixtures.Path, pair["first"].AsString));
        }
        finally { manager.UnloadAll(); }
    }
}
