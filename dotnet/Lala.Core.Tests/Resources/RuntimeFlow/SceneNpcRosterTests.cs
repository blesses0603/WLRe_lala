using System.Text;
using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Resources;
using Lala.Core.World.Eve;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class SceneNpcRosterTests
{
    private static EveNpcRow Row(ushort index=0,uint id=99)=>new(index,id,uint.MaxValue,0,[7,7,0]);
    [Fact]
    public void Source_order_indices_uint_coordinates_and_duplicate_events_are_preserved()
    {
        var rows=SceneNpcRosterRequest.Build([Row(8),Row(0),new(13,uint.MaxValue,0,uint.MaxValue,[])],null);
        Assert.Equal(new ushort[]{8,0,13},rows.Select(r=>r.NpcIndex));Assert.Equal("NPC #99",rows[0].Name);
        Assert.Equal(uint.MaxValue,rows[0].X);Assert.Equal(new byte[]{7,7,0},rows[0].EventIds);Assert.Equal(3,rows[0].EventCount);
        Assert.Equal("NPC #4294967295",rows[2].Name);Assert.Equal(0,rows[2].EventCount);
        Assert.All(rows,r=>{Assert.Equal("EventData.NewNpc",r.Source);Assert.False(r.CanInteract);});
    }
    [Theory][InlineData("")][InlineData(null)][InlineData("   ")][InlineData("名稱")]
    public void Names_follow_Python_truthiness_without_trim_or_guess(string? name)
    {var rows=SceneNpcRosterRequest.Build([Row()],new Dictionary<uint,CombatResourceNpc>{{99,new(){Name=name}}});Assert.Equal(string.IsNullOrEmpty(name)?"NPC #99":name,rows[0].Name);}
    [Fact]
    public void Name_truncation_uses_one_hundred_Unicode_codepoints()
    {string name=string.Concat(Enumerable.Repeat("😀",101));var row=SceneNpcRosterRequest.Build([Row()],new Dictionary<uint,CombatResourceNpc>{{99,new(){Name=name}}})[0];Assert.Equal(200,row.Name.Length);Assert.Equal(100,row.Name.EnumerateRunes().Count());}
    [Theory][InlineData("default")][InlineData("duplicate")][InlineData("zero-id")][InlineData("default-events")][InlineData("too-many-events")][InlineData("too-many-rows")]
    public void Invalid_roster_never_returns_partial_rows(string mode)
    {
        ImmutableArray<EveNpcRow> source=mode switch{
            "default"=>default,"duplicate"=>[Row(),Row()],"zero-id"=>[Row(id:0)],
            "default-events"=>[Row() with{EventIds=default}],"too-many-events"=>[Row() with{EventIds=Enumerable.Repeat((byte)1,256).ToImmutableArray()}],
            _=>Enumerable.Range(0,4097).Select(i=>Row((ushort)i)).ToImmutableArray()};
        Assert.Throws<ResourceValidationException>(()=>SceneNpcRosterRequest.Build(source,null));
    }
    [Fact]
    public void Empty_roster_is_known_empty_and_requests_recheck_revoke_during_read()
    {
        var rows=SceneNpcRosterRequest.Build([],null);bool active=true;var request=new SceneNpcRosterRequest(1,"owned",rows,()=>active);
        Assert.True(request.TryReadRows(out var empty));Assert.Empty(empty);Assert.False(request.CanSendPackets);
        active=false;Assert.False(request.TryReadRows(out _));int n=0;
        var race=new SceneNpcRosterRequest(1,"owned",[new(1,99,"Npc",0,0,[])],()=>++n==1);
        Assert.False(race.TryReadRows(out var late));Assert.Empty(late);
    }
}
