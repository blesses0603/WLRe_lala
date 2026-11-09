using System.Buffers.Binary;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class AtlasPixelTests
{
    private static readonly UnityFileIdentity Id=new("owned","CAB-owned");
    private static JsonDocument Fixture()=>JsonDocument.Parse(typeof(AtlasPixelTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.pixels.json")!);
    public static IEnumerable<object[]> Cases(){using var d=Fixture();for(int i=0;i<30;i++)yield return [i];}
    private static BoundedSerializedFile File(int index=0)
    {
        using var d=Fixture();var objects=new Dictionary<long,UnityObject>();long id=0;
        foreach(var o in d.RootElement.GetProperty("cases")[index].GetProperty("objects").EnumerateArray())objects[++id]=new(o.GetProperty("class").GetInt32(),Convert.FromBase64String(o.GetProperty("bytes").GetString()!));
        return new(){Identity=Id,Objects=objects,Externals=[],Container=[]};
    }
    private static int Offset(int cid,string field){using var d=Fixture();return d.RootElement.GetProperty("offsets").GetProperty(cid.ToString()).GetProperty(field).GetInt32();}
    private static AtlasPixelCandidate Extract(BoundedSerializedFile f,string name="Emoji_001_1",long sprite=2)=>AtlasSpritePixels.Extract(new([f],[]),Id,1,Id,sprite,name);
    private static void Change(BoundedSerializedFile f,long id,int offset,long value,bool wide=false)
    {var bytes=f.Objects[id].Bytes.ToArray();if(wide)BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(offset),value);else BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(offset),(int)value);f.Objects[id]=f.Objects[id] with{Bytes=bytes};}
    [Theory][MemberData(nameof(Cases))]
    public void Real_UnityPy_full_file_pixels_match_including_rotations_alpha_and_BC_formats(int index)
    {
        using var d=Fixture();var row=d.RootElement.GetProperty("cases")[index];var result=Extract(File(index));
        Assert.Equal(row.GetProperty("width").GetInt32(),result.Width);Assert.Equal(row.GetProperty("height").GetInt32(),result.Height);
        Assert.Equal(Convert.FromBase64String(row.GetProperty("pixels").GetString()!),result.CopyPixels());Assert.Equal(row.GetProperty("sha256").GetString(),result.PixelSha256);Assert.False(result.HasVerifiedProvenance);
        var copy=result.CopyPixels();copy[0]^=255;Assert.NotEqual(copy,result.CopyPixels());
    }
    [Fact]
    public void Full_embedded_file_requires_atlas_opt_in_and_reads_all_objects()
    {
        using var d=Fixture();var b=Convert.FromBase64String(d.RootElement.GetProperty("asset").GetString()!);
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(Id,b,new(),default,allowImages:true));
        var f=BoundedSerializedFile.Read(Id,b,new(),default,allowImages:true,allowAtlases:true);Assert.Equal(3,f.Objects.Count);
        Assert.Equal(Extract(File()).PixelSha256,Extract(f).PixelSha256);
        Assert.Throws<UnityTextAssetException>(()=>UnityImageObjects.Sprite(f.Objects[2].Bytes,default));
    }
    [Fact]
    public void Names_keys_membership_and_backlink_must_all_match()
    {
        Assert.Throws<UnityTextAssetException>(()=>Extract(File(),"Emoji_999_1"));
        var f=File();Change(f,2,Offset(213,"m_RenderDataKey"),999);Assert.Throws<UnityTextAssetException>(()=>Extract(f));
        f=File();f.Objects[5]=f.Objects[2];Assert.Throws<UnityTextAssetException>(()=>Extract(f,sprite:5));
        f=File();f.Objects[6]=f.Objects[1];Change(f,2,Offset(213,"m_SpriteAtlas")+4,6,true);Assert.Throws<UnityTextAssetException>(()=>Extract(f));
        f=File();Change(f,2,Offset(213,"m_SpriteAtlas")+4,0,true);Assert.Throws<UnityTextAssetException>(()=>Extract(f)); // No tag-name fallback.
    }
    [Fact]
    public void External_texture_with_same_path_id_as_sprite_requires_full_identity_binding()
    {
        var original=File();var expected=Extract(original);var id2=new UnityFileIdentity("owned2","CAB-texture");
        int pointer=Offset(687078895,"m_RenderDataMap")+4+24;
        Change(original,1,pointer,1);Change(original,1,pointer+4,2,true);
        var other=new BoundedSerializedFile{Identity=id2,Objects=new(){[2]=original.Objects[3]},Externals=[],Container=[]};original.Objects.Remove(3);
        var main=new BoundedSerializedFile{Identity=Id,Objects=original.Objects,Externals=["CAB-texture"],Container=[]};
        Assert.Throws<UnityTextAssetException>(()=>AtlasSpritePixels.Extract(new([main,other],[]),Id,1,Id,2,"Emoji_001_1"));
        var selected=new UnitySelectedObjects([main,other],[new(Id,"CAB-texture",id2)]);
        var result=AtlasSpritePixels.Extract(selected,Id,1,Id,2,"Emoji_001_1");Assert.Equal(expected.CopyPixels(),result.CopyPixels());Assert.NotEqual(expected.InputFingerprint,result.InputFingerprint);
        main.Objects.Clear();other.Objects.Clear();Assert.Equal(result.InputFingerprint,AtlasSpritePixels.Extract(selected,Id,1,Id,2,"Emoji_001_1").InputFingerprint);
    }
    [Fact]
    public void Complete_input_bytes_affect_fingerprint_even_when_pixels_do_not_change()
    {
        var f=File();var a=Extract(f);var bytes=f.Objects[3].Bytes.ToArray();bytes[4]=(byte)'X';f.Objects[3]=f.Objects[3] with{Bytes=bytes};var b=Extract(f);
        Assert.Equal(a.CopyPixels(),b.CopyPixels());Assert.NotEqual(a.InputFingerprint,b.InputFingerprint);
    }
    [Theory][InlineData(0)][InlineData(2)][InlineData(23)][InlineData(67)][InlineData(131)]
    public void Unsupported_packing_does_not_reach_pixels(uint settings)
    {
        var f=File();var atlas=UnityAtlasObjects.Read(f.Objects[1].Bytes);var data=atlas.RenderData.Values.Single() with{Settings=settings};var texture=UnityImageObjects.Texture(f.Objects[3].Bytes,default);
        Assert.Throws<UnityTextAssetException>(()=>AtlasSpritePixels.Decode("owned",new(0,0,3,5),data,texture,null,"owned"));
    }
    [Fact]
    public void Crop_alpha_geometry_color_layout_and_cancellation_are_checked()
    {
        var f=File();var data=UnityAtlasObjects.Read(f.Objects[1].Bytes).RenderData.Values.Single();var texture=UnityImageObjects.Texture(f.Objects[3].Bytes,default);
        AtlasPixelCandidate Decode(UnityAtlasData e,UnityTexturePixels t,UnityTexturePixels? a=null,SpritePixelRect? logical=null)=>AtlasSpritePixels.Decode("owned",logical??new(0,0,3,5),e,t,a,"owned");
        Assert.Throws<UnityTextAssetException>(()=>Decode(data with{Rect=new(2.5f,1,3,5)},texture));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data with{Rect=new(8,1,3,5)},texture));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data with{Downscale=.5f},texture));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data,texture with{ColorSpace=0}));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data,texture with{Layout=texture.Layout with{MipCount=2}}));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data,texture,texture));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data with{Alpha=new(0,4)},texture));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data with{Alpha=new(0,4)},texture,texture with{Layout=texture.Layout with{Width=8}}));
        Assert.Throws<UnityTextAssetException>(()=>Decode(data,texture,logical:new(0,0,1,1)));
        Assert.Throws<OperationCanceledException>(()=>AtlasSpritePixels.Extract(new([f],[]),Id,1,Id,2,"Emoji_001_1",new(true)));
    }
}
