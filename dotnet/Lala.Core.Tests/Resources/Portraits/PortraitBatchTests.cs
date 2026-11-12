using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class PortraitBatchTests
{
    private static (Dictionary<PortraitMaterialKey,string> Wanted,Dictionary<UnityFileIdentity,BoundedSerializedFile> Files) Model(bool localMask=false)
    {
        var wanted=new Dictionary<PortraitMaterialKey,string>();var objects=new Dictionary<long,UnityObject>();var container=new List<UnityContainerEntry>();
        byte[] material=Convert.FromBase64String(WholeTextureTests.Fixture("materials").GetProperty("cases")[localMask?1:0].GetProperty("bytes").GetString()!);
        for(int i=1;i<=778;i++)
        {
            bool player=i<=15;string icon=(player?i:i-15).ToString("D4");var key=new PortraitMaterialKey(player?"player":"companion",icon);
            string path=$"Assets/ResourcesBuild/Other/{(player?"Avatar2DMaterial":"Avatar2DNPCMaterial")}/{icon}/{(player?"PhotoAvatar_":"PhotoAvatarNPC_")}{icon}.mat";
            wanted.Add(key,path);objects.Add(1000+i,new(21,material));container.Add(new(path,new(0,1000+i)));
        }
        byte[] texture=WholeTextureTests.TextureBytes();if(localMask)objects.Add(99,new(28,texture));
        var mf=PortraitBatchLayout.MaterialFile;var tf=PortraitBatchLayout.TextureFile;var sf=PortraitBatchLayout.ShaderFile;
        var files=new Dictionary<UnityFileIdentity,BoundedSerializedFile>
        {
            [mf]=new(){Identity=mf,Objects=objects,Container=container,Externals=new[]{"archive:/"+tf.EntryName+"/"+tf.EntryName,sf.EntryName}},
            [tf]=new(){Identity=tf,Objects=new(){[7213]=new(28,texture)},Container=new(){new("Assets/ResourcesBuild/Texture/Avatar2DNPC/Avatar2DNPC_7213.png",new(0,7213))},Externals=[]},
            [sf]=new(){Identity=sf,Objects=new(){[PortraitBatchLayout.ShaderId]=new(48,new byte[]{1})},Container=[],Externals=[]}
        };return(wanted,files); // Structural claims only: this Shader must never pass actual Process verification.
    }
    [Theory,InlineData(false),InlineData(true)]
    public void Complete_layout_preserves_shared_pointer_and_default_vs_local_mask(bool local)
    {
        var (wanted,files)=Model(local);var rows=PortraitBatchLayout.Build(wanted,files);
        Assert.Equal(778,rows.Count);Assert.Equal(15,rows.Count(r=>r.Key.Kind=="player"));
        Assert.All(rows,r=>{Assert.Equal(7213,r.TextureId);Assert.Equal(local?99L:(long?)null,r.MaskId);});
        Assert.Equal(rows.OrderBy(r=>r.Key.Kind,StringComparer.Ordinal).ThenBy(r=>r.Key.Icon,StringComparer.Ordinal),rows);
    }
    [Theory,InlineData("missing-material"),InlineData("duplicate-texture"),InlineData("wrong-class"),InlineData("missing-shader"),InlineData("external-mismatch"),InlineData("incomplete")]
    public void Layout_rejects_incomplete_ambiguous_or_misdirected_projection(string change)
    {
        var (wanted,files)=Model();var mf=files[PortraitBatchLayout.MaterialFile];var tf=files[PortraitBatchLayout.TextureFile];
        switch(change)
        {
            case "missing-material":mf.Container.RemoveAt(0);break;
            case "duplicate-texture":tf.Container.Add(tf.Container[0]);break;
            case "wrong-class":tf.Objects[7213]=new(21,tf.Objects[7213].Bytes);break;
            case "missing-shader":files[PortraitBatchLayout.ShaderFile].Objects.Clear();break;
            case "external-mismatch":((string[])mf.Externals)[0]="CAB-unselected";break;
            case "incomplete":wanted.Remove(wanted.Keys.First());break;
        }
        Assert.Throws<UnityTextAssetException>(()=>PortraitBatchLayout.Build(wanted,files));
    }
    [Fact]
    public void Pixel_candidate_owns_inputs_and_does_not_claim_publication()
    {
        var (wanted,files)=Model();var row=PortraitBatchLayout.Build(wanted,files)[0];
        byte[] basis=Enumerable.Repeat((byte)127,256*256*4).ToArray(),mask=Enumerable.Repeat((byte)255,basis.Length).ToArray();
        var candidate=new PortraitImageCandidate(row,"owned-claim",basis,mask);string hash=SpritePng.Hash(candidate.Render(new Dictionary<int,int>()));
        Array.Fill(basis,(byte)0);Array.Fill(mask,(byte)0);
        Assert.Equal(hash,SpritePng.Hash(candidate.Render(new Dictionary<int,int>())));Assert.False(candidate.HasVerifiedProvenance);
        Assert.ThrowsAny<OperationCanceledException>(()=>candidate.Render(new Dictionary<int,int>(),new(true)));
        Assert.ThrowsAny<OperationCanceledException>(()=>PortraitBatchLayout.Build(wanted,files,new(true)));
        bool consumed=false;Assert.Throws<ArgumentNullException>(()=>PortraitBatch.Process(null!,_=>consumed=true));Assert.False(consumed);
    }
}
