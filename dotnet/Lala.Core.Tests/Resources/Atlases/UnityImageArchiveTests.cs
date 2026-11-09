using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
[Collection("Unity extraction memory bounds")]
public sealed class UnityImageArchiveTests
{
    private static JsonDocument Fixture()=>JsonDocument.Parse(typeof(UnityImageArchiveTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.streams.json")!);
    private static readonly UnityFileIdentity Owner=new("owned.bundle","CAB-owned");
    private const string Path="archive:/CAB-owned/CAB-owned.resS";
    private static byte[] Data(string name){using var d=Fixture();return Convert.FromBase64String(d.RootElement.GetProperty(name).GetString()!);}
    private static byte[] Normal(int index=0){using var d=Fixture();return Convert.FromBase64String(d.RootElement.GetProperty("cases")[index].GetProperty("bytes").GetString()!);}
    [Theory][InlineData(0)][InlineData(1)][InlineData(2)]
    public void Independent_resource_bytes_are_exact_and_require_opt_in(int index)
    {
        var raw=Normal(index);Assert.Throws<UnityTextAssetException>(()=>BoundedUnityBundle.Read(raw,new(),default));
        var archive=UnityImageArchive.Read(Owner.BundleName,raw,new());var hash=archive.SourceSha256;raw[0]=0;
        Assert.Equal(new[]{Owner},archive.SerializedOwners);
        Assert.Throws<NotSupportedException>(()=>((IList<UnityFileIdentity>)archive.SerializedOwners)[0]=Owner with{EntryName="other"});
        Assert.Equal(Enumerable.Range(250,20).Select(i=>(byte)i).ToArray(),archive.CopyResource(Owner,Path,250,20));
        var copy=archive.CopyResource(Owner,Path,0,10);copy[0]=99;Assert.Equal(0,archive.CopyResource(Owner,Path,0,1)[0]);Assert.Equal(hash,archive.SourceSha256);
    }
    public static IEnumerable<object[]> PixelCases(){using var d=Fixture();for(int i=0;i<d.RootElement.GetProperty("pixels").GetArrayLength();i++)yield return [i];}
    [Theory][MemberData(nameof(PixelCases))]
    public void Full_streamed_Sprite_image_matches_independent_UnityPy(int index)
    {
        using var d=Fixture();var row=d.RootElement.GetProperty("pixels")[index];var raw=Convert.FromBase64String(row.GetProperty("bytes").GetString()!);
        var archive=UnityImageArchive.Read(Owner.BundleName,raw,new());var bytes=archive.CopySerialized(Owner);
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(Owner,bytes,new(),default,allowImages:true,allowAtlases:true));
        var file=BoundedSerializedFile.Read(Owner,bytes,new(),default,allowImages:true,allowAtlases:true,imageArchive:archive);
        var selected=new UnitySelectedObjects([file],[]);
        Assert.Throws<UnityTextAssetException>(()=>AtlasSpritePixels.Extract(selected,Owner,1,Owner,2,"Emoji_001_1"));
        var result=AtlasSpritePixels.Extract(selected,Owner,1,Owner,2,"Emoji_001_1",imageArchive:archive);
        Assert.Equal(row.GetProperty("width").GetInt32(),result.Width);Assert.Equal(row.GetProperty("height").GetInt32(),result.Height);
        Assert.Equal(Convert.FromBase64String(row.GetProperty("pixels").GetString()!),result.CopyPixels());Assert.False(result.HasVerifiedProvenance);
        var wrong=UnityImageArchive.Read("other.bundle",raw,new());
        Assert.Throws<UnityTextAssetException>(()=>AtlasSpritePixels.Extract(selected,Owner,1,Owner,2,"Emoji_001_1",imageArchive:wrong));
    }
    [Fact]
    public void Large_archive_is_explicitly_bounded_and_shared_budget_still_applies()
    {
        var raw=Data("large");Assert.Throws<UnityTextAssetException>(()=>BoundedUnityBundle.Read(raw,new(),default));
        var budget=new UnityExtractionBudget();var archive=UnityImageArchive.Read(Owner.BundleName,raw,budget);Assert.True(budget.ExpandedBytes>64*1024*1024);
        Assert.Equal(new byte[4],archive.CopyResource(Owner,Path,64*1024*1024-4,4));
        Assert.Throws<UnityTextAssetException>(()=>UnityImageArchive.Read(Owner.BundleName,raw,budget));
        Assert.Throws<UnityTextAssetException>(()=>UnityImageArchive.Read(Owner.BundleName,Data("over"),new()));
    }
    [Theory][InlineData("unpaired")][InlineData("flags")]
    public void Resource_pairing_and_flags_are_strict(string name)=>Assert.Throws<UnityTextAssetException>(()=>UnityImageArchive.Read(Owner.BundleName,Data(name),new()));
    [Fact]
    public void Paths_owner_spans_and_cancellation_cannot_escape_the_archive()
    {
        var a=UnityImageArchive.Read(Owner.BundleName,Normal(),new());
        foreach(var path in new[]{"CAB-owned.resS","../CAB-owned.resS",Path.ToUpperInvariant(),"archive:/other/CAB-owned.resS"})
            Assert.Throws<UnityTextAssetException>(()=>a.CopyResource(Owner,path,0,1));
        Assert.Throws<UnityTextAssetException>(()=>a.CopyResource(Owner with{BundleName="other.bundle"},Path,0,1));
        Assert.Throws<UnityTextAssetException>(()=>a.CopyResource(Owner with{EntryName="CAB-owned.resS"},Path,0,1));
        foreach(var offset in new[]{-1L,1024L,long.MaxValue})Assert.Throws<UnityTextAssetException>(()=>a.CopyResource(Owner,Path,offset,1));
        foreach(var size in new[]{0U,1025U,16*1024*1024+1U,uint.MaxValue})Assert.Throws<UnityTextAssetException>(()=>a.CopyResource(Owner,Path,0,size));
        Assert.Throws<OperationCanceledException>(()=>a.CopyResource(Owner,Path,0,1,new(true)));
        Assert.Throws<OperationCanceledException>(()=>UnityImageArchive.Read(Owner.BundleName,Normal(),new(),new(true)));
    }
    [Fact]
    public void Every_truncation_fails_with_a_domain_error()
    {
        var raw=Normal(2);for(int n=0;n<raw.Length;n++)Assert.Throws<UnityTextAssetException>(()=>UnityImageArchive.Read(Owner.BundleName,raw.AsMemory(0,n),new()));
    }
}
