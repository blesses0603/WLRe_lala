using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class UnitySelectedObjectTests
{
    private static readonly UnityFileIdentity Material=new("material.bundle","CAB-material"),Texture=new("texture.bundle","CAB-texture");
    private static BoundedSerializedFile File(UnityFileIdentity id,int cls,long pid,byte[] bytes,params string[] externals)=>
        new(){Identity=id,Externals=externals,Objects=new(){[pid]=new(cls,bytes)},Container=[]};
    [Fact]
    public void Exact_external_binding_uses_pointer_and_owns_bytes_and_indexes()
    {
        byte[] bytes=[1,2,3];string[] externals=["archive:/CAB-texture/CAB-texture"];
        var material=File(Material,21,7214,[4],externals);var texture=File(Texture,28,7213,bytes);
        var binding=new UnityExternalBinding(Material,externals[0],Texture);
        var resolver=new UnitySelectedObjects([material,texture],[binding]);
        bytes[0]=99;texture.Objects.Clear();externals[0]="untrusted";
        var found=resolver.Resolve(Material,new(1,7213),28)!;
        Assert.Equal(Texture,found.File);Assert.Equal(7213,found.PathId);Assert.Equal(new byte[]{1,2,3},found.Object.Bytes.ToArray());
        Assert.Throws<UnityTextAssetException>(()=>resolver.Resolve(Material,new(1,7214),28));
    }
    [Theory,InlineData(-1,1L),InlineData(2,1L),InlineData(1,0L),InlineData(0,0L),InlineData(0,999L)]
    public void Bad_pointers_cannot_resolve(int fid,long pid)
    {
        var resolver=new UnitySelectedObjects([File(Material,21,1,[1],"CAB-texture")],[]);
        Assert.Throws<UnityTextAssetException>(()=>resolver.Resolve(Material,new(fid,pid),21));
    }
    [Fact]
    public void Null_masks_require_explicit_permission_and_do_not_produce_a_white_texture()
    {
        var resolver=new UnitySelectedObjects([File(Material,21,1,[1],"CAB-texture")],[]);
        Assert.Null(resolver.Resolve(Material,new(0,0),28,allowNull:true));
        Assert.Throws<UnityTextAssetException>(()=>resolver.Resolve(Material,new(1,0),28,allowNull:true));
        Assert.Throws<UnityTextAssetException>(()=>resolver.Resolve(Material,new(0,1),28));
        Assert.Throws<UnityTextAssetException>(()=>resolver.Resolve(Texture,new(0,1),21));
    }
    [Fact]
    public void Similar_basenames_missing_bindings_and_duplicate_bindings_are_rejected()
    {
        var material=File(Material,21,1,[1],"archive:/CAB-texture/CAB-texture");var texture=File(Texture,28,2,[2]);
        var resolver=new UnitySelectedObjects([material,texture],[]);
        Assert.Throws<UnityTextAssetException>(()=>resolver.Resolve(Material,new(1,2),28));
        var wrong=new UnityExternalBinding(Material,"CAB-texture",Texture);
        Assert.Throws<UnityTextAssetException>(()=>new UnitySelectedObjects([material,texture],[wrong]));
        var exact=wrong with{ExternalPath=material.Externals[0]};
        Assert.Throws<UnityTextAssetException>(()=>new UnitySelectedObjects([material,texture],[exact,exact]));
        Assert.Throws<UnityTextAssetException>(()=>new UnitySelectedObjects([material,material],[]));
        Assert.Throws<UnityTextAssetException>(()=>new UnitySelectedObjects([material],[exact]));
        Assert.ThrowsAny<OperationCanceledException>(()=>new UnitySelectedObjects([material,texture],[exact],new(true)));
    }
}
