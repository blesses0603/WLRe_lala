using Xunit;
using System.Buffers.Binary;
using System.Text.Json;
using Lala.Core.Resources;
namespace Lala.Core.Tests.Resources;
public sealed class UnityAtlasTests
{
    private static JsonDocument Fixture()=>JsonDocument.Parse(typeof(UnityAtlasTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.atlases.json")!);
    public static IEnumerable<object[]> Cases(){using var doc=Fixture();foreach(var c in doc.RootElement.GetProperty("cases").EnumerateArray())yield return [c.GetProperty("name").GetString()!,Convert.FromBase64String(c.GetProperty("bytes").GetString()!),c.GetProperty("ok").GetBoolean()];}
    private static byte[] Default(){using var d=Fixture();return Convert.FromBase64String(d.RootElement.GetProperty("cases")[0].GetProperty("bytes").GetString()!);}
    [Theory][MemberData(nameof(Cases))]
    public void Independent_writer_cases(string name,byte[] bytes,bool ok)
    {Assert.NotEmpty(name);if(ok)Assert.Equal(2,UnityAtlasObjects.Read(bytes).RenderData.Count);else Assert.Throws<UnityTextAssetException>(()=>UnityAtlasObjects.Read(bytes));}
    [Fact]
    public void Exact_fields_are_owned_and_preserved_without_pixel_authority()
    {
        var bytes=Default();var a=UnityAtlasObjects.Read(bytes);Array.Fill(bytes,(byte)0);
        Assert.Equal("OwnedEmojiAtlas",a.Name);Assert.Equal("OwnedEmoji",a.Tag);
        Assert.Equal(new UnityContainerPointer(1,-3),a.Sprites[1]);Assert.Equal("Emoji_002_1",a.Names[1]);
        var d=a.RenderData[new(4,5,6,7,-101)];Assert.Equal(new UnityContainerPointer(1,101),d.Texture);
        Assert.Equal(new UnityContainerPointer(0,0),d.Alpha);Assert.Equal(new SpritePixelRect(4,2,32,24),d.Rect);
        Assert.Equal(new UnityAtlasVector(1,2),d.TextureOffset);Assert.Equal(new UnityAtlasVector(3,4),d.AtlasOffset);
        Assert.Equal(new UnityAtlasVector(5,6,7,8),d.Uv);Assert.Equal(1,d.Downscale);Assert.Equal(3u,d.Settings);
    }
    [Fact]
    public void Every_truncation_trailing_bytes_capacity_and_cancellation_fail()
    {
        var b=Default();for(int i=0;i<b.Length;i++)Assert.Throws<UnityTextAssetException>(()=>UnityAtlasObjects.Read(b.AsMemory(0,i)));
        Assert.Throws<UnityTextAssetException>(()=>UnityAtlasObjects.Read((byte[])[..b,0]));
        Assert.Throws<UnityTextAssetException>(()=>UnityAtlasObjects.Read(new byte[2*1024*1024+1]));
        Assert.Throws<OperationCanceledException>(()=>UnityAtlasObjects.Read(b,new(true)));
        int count=(4+BinaryPrimitives.ReadInt32LittleEndian(b)+3)&~3;
        BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(count),int.MaxValue);
        Assert.Throws<UnityTextAssetException>(()=>UnityAtlasObjects.Read(b));
    }
    [Fact]
    public void Embedded_schema_requires_explicit_opt_in_and_exact_shape()
    {
        using var doc=Fixture();var b=Convert.FromBase64String(doc.RootElement.GetProperty("asset").GetString()!);
        var id=new UnityFileIdentity("owned","CAB-owned");
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(id,b,new(),default));
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(id,b,new(),default,allowImages:true));
        var parsed=BoundedSerializedFile.Read(id,b,new(),default,allowAtlases:true);
        Assert.Single(parsed.Objects);Assert.Equal(687078895,parsed.Objects[1].ClassId);
        Assert.Equal(2,UnityAtlasObjects.Read(parsed.Objects[1].Bytes).Sprites.Count);
        // Unique schema field name; same-size mutation must not broaden acceptance.
        var target=System.Text.Encoding.UTF8.GetBytes("m_PackedSprites\0");int at=b.AsSpan().IndexOf(target);Assert.True(at>=0);b[at]=(byte)'X';
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(id,b,new(),default,allowAtlases:true));
    }
}
