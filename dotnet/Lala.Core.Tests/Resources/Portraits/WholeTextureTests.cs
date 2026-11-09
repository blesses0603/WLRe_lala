using System.Buffers.Binary;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class WholeTextureTests
{
    internal static JsonElement Fixture(string name="textures")
    {
        using var stream=typeof(WholeTextureTests).Assembly.GetManifestResourceStream($"Lala.Core.Tests.Resources.Portraits.{name}.json")!;
        using var doc=JsonDocument.Parse(stream);return doc.RootElement.Clone();
    }
    internal static byte[] TextureBytes()=>Convert.FromBase64String(Fixture().GetProperty("texture").GetString()!);
    private static TexturePixelContext Context=>new("owned-version",new string('a',64),"CAB-owned","Assets/owned.png",7213);
    public static IEnumerable<object[]> Vectors()=>Fixture().GetProperty("vectors").EnumerateArray().Select(x=>new object[]{x.Clone()});
    [Theory,MemberData(nameof(Vectors))]
    public void Whole_pixels_match_UnityPy_without_any_sprite_identity(JsonElement row)
    {
        int w=row.GetProperty("width").GetInt32(),h=row.GetProperty("height").GetInt32(),fmt=row.GetProperty("format").GetInt32(),seed=row.GetProperty("seed").GetInt32();
        int count=fmt==4?w*h*4:((w+3)/4)*((h+3)/4)*(fmt==10?8:16);
        byte[] source=Enumerable.Range(0,count).Select(i=>(byte)((i*37+seed*19+11)%256)).ToArray();
        var candidate=BoundedTexturePixels.Decode(Context,new("owned",new(w,h,fmt),source,1));
        Assert.Equal(row.GetProperty("sha256").GetString(),candidate.PixelSha256);Assert.False(candidate.HasVerifiedProvenance);
        Array.Fill(source,(byte)0);byte[] pixels=candidate.CopyPixels();pixels[0]^=255;
        Assert.Equal(row.GetProperty("sha256").GetString(),SpritePng.Hash(candidate.CopyPixels()));
        Assert.Equal(7213,candidate.Context.TexturePathId);
    }
    [Fact]
    public void Serialized_color_space_is_retained_and_linear_pixels_are_not_silently_relabelled()
    {
        var bytes=TextureBytes();var texture=UnityImageObjects.Texture(bytes,default);Assert.Equal(1,texture.ColorSpace);
        Assert.Equal(Fixture().GetProperty("texture_sha256").GetString(),BoundedTexturePixels.Decode(Context,texture).PixelSha256);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(Fixture().GetProperty("offsets").GetProperty("m_ColorSpace").GetInt32()),0);
        texture=UnityImageObjects.Texture(bytes,default);Assert.Equal(0,texture.ColorSpace);
        Assert.Throws<SpritePixelException>(()=>BoundedTexturePixels.Decode(Context,texture));
    }
    [Fact]
    public void Limits_and_cancel_do_not_relax_sprite_geometry_or_texture_metadata()
    {
        var texture=UnityImageObjects.Texture(TextureBytes(),default);
        foreach(var layout in new[]{texture.Layout with{Width=1025},texture.Layout with{MipCount=2},texture.Layout with{Streamed=true},texture.Layout with{Format=14}})
            Assert.Throws<SpritePixelException>(()=>BoundedTexturePixels.Decode(Context,texture with{Layout=layout}));
        Assert.Throws<SpritePixelException>(()=>BoundedTexturePixels.Decode(Context with{TexturePathId=0},texture));
        Assert.Throws<SpritePixelException>(()=>BoundedTexturePixels.Decode(Context with{AssetPath="Assets/../owned"},texture));
        Assert.Throws<SpritePixelException>(()=>BoundedTexturePixels.Decode(Context,texture with{Payload=new byte[1]}));
        Assert.ThrowsAny<OperationCanceledException>(()=>BoundedTexturePixels.Decode(Context,texture,new(true)));
        Assert.Equal(512,BoundedSpritePixels.MaximumSpriteSide);
    }
}
