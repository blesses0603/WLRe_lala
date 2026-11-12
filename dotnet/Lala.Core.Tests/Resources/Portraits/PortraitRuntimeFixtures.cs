using System.Security.Cryptography;
using Lala.Core.Resources;
namespace Lala.Core.Tests.Resources;
internal static class PortraitRuntimeFixtures
{
    internal static readonly PortraitMaterialKey Key = new("player", "0001");
    internal static PortraitRuntimeBatch Batch(Func<int>? seed = null)
    {
        string source = new('a', 64);
        var plan = new PortraitCachePlan(source, [Key]);
        return PortraitRuntimeBatch.ForOfflineTests(plan, (consume, token) =>
        {
            token.ThrowIfCancellationRequested();
            var colors = PortraitRenderer.Parts.ToDictionary(k => k, _ => new UnityMaterialColor(4,4,4,1));
            var material = new PortraitMaterialCandidate("owned", new(2,1), new(1,2), new(0,0), .06f, colors);
            var row = new PortraitLinkedRow(Key, "Assets/owned.mat", 3, material, 2, "Assets/owned.png", null);
            byte[] pixels = Enumerable.Repeat((byte)(seed?.Invoke() ?? 255), 256*256*4).ToArray();
            var image = new PortraitImageCandidate(row, source, pixels, pixels);
            consume(image);
            return new(source, Convert.ToHexStringLower(SHA256.HashData(Convert.FromHexString(image.Fingerprint))), 1);
        });
    }
}
