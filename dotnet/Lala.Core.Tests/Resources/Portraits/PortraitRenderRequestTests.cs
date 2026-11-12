using System.Collections.Immutable;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class PortraitRenderRequestTests
{
    private static (PortraitImageCandidate Candidate,PortraitCachedImage Cached) Images()
    {
        PortraitImageCandidate? c=null;PortraitRuntimeFixtures.Batch().Rebuild(x=>c=x,default);
        return(c!,new(c!,SpritePng.EncodePortrait(c!.CopyBase()),SpritePng.EncodePortrait(c.CopyMask())));
    }
    private static PortraitSelection Selection(int value=444444444)=>new(PortraitRuntimeFixtures.Key,ImmutableDictionary<int,int>.Empty.Add(1,value));
    [Fact]
    public async Task Background_png_render_matches_direct_pixels_and_checks_retirement()
    {
        var (candidate,cached)=Images();bool current=true;var choice=Selection();
        var request=new PortraitRenderRequest(cached,choice,1,null,()=>current);
        byte[] png=(await request.RenderAsync())!;
        Assert.Equal(candidate.Render(choice.Palettes),SpritePng.DecodePortrait(png,default));
        Array.Fill(png,(byte)0);Assert.NotEqual(png,await request.RenderAsync());
        current=false;Assert.False(request.IsCurrent);Assert.Null(await request.RenderAsync());
    }
    [Fact]
    public async Task Retirement_during_work_never_returns_pixels_and_cancel_is_observed()
    {
        var (_,image)=Images();int calls=0;
        var request=new PortraitRenderRequest(image,Selection(),1,null,()=>++calls==1);
        Assert.Null(await request.RenderAsync());Assert.Equal(2,calls);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>request.RenderAsync(new(true)));
    }
    [Fact]
    public void Identity_includes_role_palette_and_active_companion()
    {
        var (_,image)=Images();string Key(uint role,int palette,uint? active)=>new PortraitRenderRequest(image,Selection(palette),role,active,()=>true).Identity;
        Assert.Equal(Key(1,4,null),Key(1,4,null));Assert.NotEqual(Key(1,4,null),Key(2,4,null));
        Assert.NotEqual(Key(1,4,null),Key(1,5,null));Assert.NotEqual(Key(1,4,7000),Key(1,4,7001));
    }
    [Theory,InlineData(0),InlineData(8),InlineData(16),InlineData(24),InlineData(33),InlineData(45)]
    public void Damaged_owned_png_is_rejected(int offset)
    {
        byte[] png=Images().Cached.CopyBasePng();png[offset]^=1;
        Assert.ThrowsAny<Exception>(()=>SpritePng.DecodePortrait(png,default));
    }
    [Fact]
    public void Owned_png_boundaries_and_cancel_reject()
    {
        byte[] png=Images().Cached.CopyBasePng();
        Assert.ThrowsAny<Exception>(()=>SpritePng.DecodePortrait(png[..^1],default));
        Assert.ThrowsAny<Exception>(()=>SpritePng.DecodePortrait([..png,0],default));
        Assert.ThrowsAny<OperationCanceledException>(()=>SpritePng.DecodePortrait(png,new(true)));
        Assert.ThrowsAny<Exception>(()=>SpritePng.DecodePortrait(new byte[524289],default));
    }
}
