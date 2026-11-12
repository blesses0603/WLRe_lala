using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class PortraitRendererTests
{
    private static PortraitRenderSettings Settings => new(PortraitRenderer.ColorProfile, "UI_ProfilePhotoWithMask", false, 0, .22, 0, new Dictionary<string, double[]>());
    public static IEnumerable<object[]> Vectors()
    {
        using var stream = typeof(PortraitRendererTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Portraits.vectors.json")!;
        using var json = JsonDocument.Parse(stream);
        foreach (var row in json.RootElement.GetProperty("vectors").EnumerateArray()) yield return [row.Clone()];
    }
    [Theory, MemberData(nameof(Vectors))]
    public void Full_rgba_image_matches_actual_Python_renderer(JsonElement row)
    {
        int seed = row.GetProperty("seed").GetInt32();
        byte[] source = Enumerable.Range(0, 256*256*4).Select(i => (byte)((i*37+seed*19+11)%256)).ToArray();
        byte[] mask = Enumerable.Range(0, source.Length).Select(i => (byte)((i*17+(i/4)*31+seed*43)%256)).ToArray();
        var palettes = row.GetProperty("palettes").EnumerateObject().ToDictionary(p => int.Parse(p.Name), p => p.Value.GetInt32());
        var colors = row.GetProperty("colors").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.EnumerateArray().Select(v => v.GetDouble()).ToArray());
        var settings = Settings with { MaskClip = row.GetProperty("clip").GetDouble(), EdgeLength = row.GetProperty("edge").GetDouble(), Colors = colors };
        byte[] result = PortraitRenderer.Render(source, mask, palettes, settings);
        Assert.Equal(row.GetProperty("sha256").GetString(), SpritePng.Hash(result));
        Assert.Equal((byte)(seed*19+11), source[0]);
        result[0] ^= 255; Assert.Equal((byte)(seed*19+11), source[0]);
    }
    [Fact]
    public void Palette_groups_follow_Python_order_and_own_defaults()
    {
        double[] color = [1,2,3]; var defaults = new Dictionary<string,double[]> { [PortraitRenderer.Parts[4]] = color };
        var vectors = PortraitRenderer.PaletteVectors(new Dictionary<int,int> { [1]=123456789, [3]=102030405, [4]=901234567, [5]=901234567 }, defaults);
        color[0] = 99;
        Assert.Equal(new double[] {1,2,3}, vectors[0]); Assert.Equal(new double[] {4,5,6}, vectors[1]);
        Assert.Equal(new double[] {4,0,5}, vectors[9]); Assert.Equal(new double[] {5,6,7}, vectors[8]);
        Assert.Equal(new double[] {2,3,4}, vectors[13]); Assert.Equal(new double[] {1,2,3}, vectors[4]);
    }
    [Fact]
    public void Unknown_variants_geometry_and_nonfinite_inputs_are_rejected()
    {
        byte[] pixels = new byte[256*256*4]; var palettes = new Dictionary<int,int>();
        foreach (var settings in new[] { Settings with { ColorProfile = "pc-linear" }, Settings with { Shader = "unknown" },
            Settings with { HasKeywords = true }, Settings with { UseShapeMask = 1 }, Settings with { MaskClip = double.NaN },
            Settings with { EdgeLength = double.PositiveInfinity }, Settings with { MaskClip = 2 }, Settings with { EdgeLength = -1 } })
            Assert.Throws<SpritePixelException>(() => PortraitRenderer.Render(pixels,pixels,palettes,settings));
        Assert.Throws<SpritePixelException>(() => PortraitRenderer.Render(new byte[4],pixels,palettes,Settings));
        foreach (var pair in new[] { (0,1), (6,1), (1,-1), (1,1000000000) })
            Assert.Throws<SpritePixelException>(() => PortraitRenderer.PaletteVectors(new Dictionary<int,int> { [pair.Item1]=pair.Item2 }, Settings.Colors));
        foreach (var value in new[] { new[] { 1.0 }, new[] { 1.0, double.NaN, 3.0 } })
            Assert.Throws<SpritePixelException>(() => PortraitRenderer.PaletteVectors(palettes,new Dictionary<string,double[]> { [PortraitRenderer.Parts[0]]=value }));
    }
    [Fact]
    public void Cancellation_cannot_return_partial_portrait()
    {
        byte[] pixels = new byte[256*256*4];
        Assert.Throws<OperationCanceledException>(() => PortraitRenderer.Render(pixels,pixels,new Dictionary<int,int>(),Settings,new(true)));
    }
}
