using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class AtlasProjectionTests
{
    private static readonly UnityFileIdentity Id=new("owned","CAB-owned");
    private static JsonDocument Fixture()
    {
        using var stream=new System.IO.Compression.GZipStream(typeof(AtlasProjectionTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.projection.json.gz")!,System.IO.Compression.CompressionMode.Decompress);
        return JsonDocument.Parse(stream);
    }
    public static IEnumerable<object[]> Cases(){using var d=Fixture();for(int i=0;i<d.RootElement.GetProperty("fractional").GetArrayLength();i++)yield return [i];}
    [Theory][MemberData(nameof(Cases))]
    public void Fractional_endpoints_match_complete_UnityPy_Pillow_RGBA(int index)
    {
        using var d=Fixture();var row=d.RootElement.GetProperty("fractional")[index];
        var f=BoundedSerializedFile.Read(Id,Convert.FromBase64String(row.GetProperty("asset").GetString()!),new(),default,allowImages:true,allowAtlases:true);
        var result=AtlasSpritePixels.Extract(new([f],[]),Id,1,Id,2,"Emoji_001_1");
        Assert.Equal(row.GetProperty("width").GetInt32(),result.Width);Assert.Equal(row.GetProperty("height").GetInt32(),result.Height);
        Assert.Equal(Convert.FromBase64String(row.GetProperty("pixels").GetString()!),result.CopyPixels());
    }
    [Fact]
    public void Unused_physics_is_not_exposed_but_general_reader_still_rejects()
    {
        using var d=Fixture();var b=Convert.FromBase64String(d.RootElement.GetProperty("projection").GetProperty("unused").GetString()!);
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(Id,b,new(),default,allowImages:true,allowAtlases:true));
        var f=BoundedSerializedFile.ReadEmojiAtlasProjection(Id,b,new(),default);
        Assert.Equal(new long[]{1,2,3},f.Objects.Keys.Order().ToArray());Assert.Single(f.Container);
        Assert.NotEmpty(AtlasSpritePixels.Extract(new([f],[]),Id,1,Id,2,"Emoji_001_1").CopyPixels());
        Assert.Throws<OperationCanceledException>(()=>BoundedSerializedFile.ReadEmojiAtlasProjection(Id,b,new(),new(true)));
        b[11]=0;Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.ReadEmojiAtlasProjection(Id,b,new(),default));
    }
    [Theory][InlineData("selected_physics")][InlineData("duplicate_root")][InlineData("wrong_root_class")][InlineData("missing_sprite")][InlineData("external_sprite")]
    public void Selected_graph_and_container_remain_strict(string name)
    {
        using var d=Fixture();var b=Convert.FromBase64String(d.RootElement.GetProperty("projection").GetProperty(name).GetString()!);
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.ReadEmojiAtlasProjection(Id,b,new(),default));
    }
}
