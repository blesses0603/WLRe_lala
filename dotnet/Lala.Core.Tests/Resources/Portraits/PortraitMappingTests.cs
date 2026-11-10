using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class PortraitMappingTests
{
    private static JsonElement Fixture()
    {
        using var s=typeof(PortraitMappingTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Portraits.mapping.json")!;
        using var d=JsonDocument.Parse(s); return d.RootElement.Clone();
    }
    internal static byte[] Raw()=>Convert.FromBase64String(Fixture().GetProperty("raw").GetString()!);
    private static PortraitMapping Mapping()=>PortraitMapping.ParseLayoutForOfflineTests(Raw());
    private static WorldPlayer Player(byte sex=2,byte head=0,uint p1=123456789,uint p5=987654321,uint role=1)
        =>new(role,sex,1,0,0,0,head,0,p1,p5,0,false,[],"owned",0);
    private static RoleSnapshot Role(WorldPlayer player) => new(1, "owned-role", 18, 3, 140, 100, 80, 50, 0, 0,
        player.Sex, player.Head, player.Palette1, player.Palette5, 0, 0, 1, 0, false, new(0, 0, 0, 0, 0, 0, 0, 0, 0));
    [Theory, MemberData(nameof(PlayerCases))]
    public void Role_list_portrait_uses_same_character_and_dyes_without_a_world_player(JsonElement row)
    {
        var player = Player(row.GetProperty("sex").GetByte(), row.GetProperty("head").GetByte());
        var map = Mapping();
        var expected = map.Select(player, State(), false);
        var actual = map.SelectRole(Role(player));
        Assert.Equal(expected?.Key, actual?.Key);
        if (expected is not null) Assert.Equal(expected.Palettes.OrderBy(p => p.Key), actual!.Palettes.OrderBy(p => p.Key));
    }
    [Fact]
    public void Unrecognized_role_appearance_or_invalid_dyes_never_choose_a_default_portrait()
    {
        var map = Mapping();
        Assert.Null(map.SelectRole(Role(Player(sex: 255, head: 255))));
        Assert.Null(map.SelectRole(Role(Player(p1: 1000000000))));
        Assert.Null(map.SelectRole(Role(Player(p5: uint.MaxValue))));
    }
    private static CompanionProfileSnapshot Profile(uint id=7000,ushort modeling=0,long? replacement=null)
        =>new(new(1,id,0,1,1,1,1,1,1,1,1,0,0,0,0,"owned",[],[],0,0,0,0,modeling,0,0),
            ImmutableDictionary<uint,CompanionLearnedSkill>.Empty,
            replacement is null ? ImmutableDictionary<string,long>.Empty : ImmutableDictionary<string,long>.Empty.Add("modeling",replacement.Value));
    private static CompanionReceiveSnapshot State(CompanionProfileSnapshot? first=null,bool duplicate=false,uint? active=7000)
    {
        var rows=ImmutableDictionary<ushort,CompanionProfileSnapshot>.Empty.Add(1,first??Profile());
        if(duplicate)rows=rows.Add(2,first??Profile());
        return new(){Ready=true,ActiveNpcId=active,Companions=rows};
    }
    public static IEnumerable<object[]> PlayerCases()=>Fixture().GetProperty("players").EnumerateArray().Select(x=>new object[]{x.Clone()});
    [Theory,MemberData(nameof(PlayerCases))]
    public void Player_selection_matches_actual_python(JsonElement row)
    {
        var result=Mapping().Select(Player(row.GetProperty("sex").GetByte(),row.GetProperty("head").GetByte()),State(),false);
        var expected=row.GetProperty("expected");
        if(expected.ValueKind==JsonValueKind.Null){Assert.Null(result);return;}
        Assert.Equal(expected[0].GetString(),result!.Key.Kind);Assert.Equal(expected[1].GetString(),result.Key.Icon);
        foreach(var p in expected[2].EnumerateArray())Assert.Equal(p[1].GetInt32(),result.Palettes[p[0].GetInt32()]);
        Assert.Equal(2,result.Palettes.Count);
    }
    [Theory,InlineData(0,"7000"),InlineData(7001,"0071_2"),InlineData(7002,null),InlineData(9000,null)]
    public void Companion_modeling_selects_reviewed_npc_and_palettes(int modeling,string? icon)
    {
        var result=Mapping().Select(Player(),State(Profile(modeling:(ushort)modeling)),true);
        if(icon is null){Assert.Null(result);return;}
        Assert.Equal(icon,result!.Key.Icon);Assert.Equal("companion",result.Key.Kind);
        string npc=modeling==0?"7000":modeling.ToString(System.Globalization.CultureInfo.InvariantCulture);
        foreach(var p in Fixture().GetProperty("npcs").GetProperty(npc).GetProperty("palettes").EnumerateObject())
            Assert.Equal(p.Value.GetInt32(),result.Palettes[int.Parse(p.Name,System.Globalization.CultureInfo.InvariantCulture)]);
    }
    [Theory,InlineData(-1),InlineData(65536),InlineData(long.MaxValue)]
    public void Invalid_modeling_override_never_falls_back(long value)
        =>Assert.Null(Mapping().Select(Player(),State(Profile(replacement:value)),true));
    [Fact]
    public void Missing_ambiguous_and_unrecognized_observations_do_not_pick_defaults()
    {
        var map=Mapping();
        Assert.Null(map.Select(null,State(),true));Assert.Null(map.Select(Player(role:0),State(),false));
        Assert.Null(map.Select(Player(),State(duplicate:true),true));Assert.Null(map.Select(Player(),State(active:null),true));
        Assert.Null(map.Select(Player(),State(active:0),true));Assert.Null(map.Select(Player(),State(active:1),true));
        Assert.Null(map.Select(Player(p1:1000000000),State(),false));Assert.Null(map.Select(Player(p5:uint.MaxValue),State(),false));
        Assert.Equal("0071_2",map.Select(Player(),State(Profile(replacement:7001)),true)!.Key.Icon);
        Assert.Equal(0,map.Select(Player(p1:0),State(),false)!.Palettes[1]);
    }
    [Fact]
    public void Mapping_is_owned_and_production_rejects_synthetic_digest_or_other_version()
    {
        byte[] raw=Raw();var map=PortraitMapping.ParseLayoutForOfflineTests(raw);Array.Fill(raw,(byte)0);
        var selected=map.Select(Player(),State(),true)!;Assert.Equal("7000",selected.Key.Icon);
        Assert.Throws<NotSupportedException>(()=>((IDictionary<int,int>)selected.Palettes).Clear());
        Assert.Throws<CatalogDecodeException>(()=>PortraitMapping.Create(Raw(),PortraitMapping.DataPackageVersion));
        Assert.Throws<SpritePixelException>(()=>PortraitMapping.Create(Raw(),"other"));
        Assert.ThrowsAny<OperationCanceledException>(()=>PortraitMapping.ParseLayoutForOfflineTests(Raw(),new(true)));
    }
    [Fact]
    public void Selection_requires_available_pixels_from_same_readback()
    {
        var raw=Raw(); var mapping=PortraitMapping.ParseLayoutForOfflineTests(raw);
        PortraitImageCandidate? candidate=null; var batch=PortraitRuntimeFixtures.Batch();batch.Rebuild(c=>candidate=c,default);
        var image=new PortraitCachedImage(candidate!,SpritePng.EncodePortrait(candidate!.CopyBase()),SpritePng.EncodePortrait(candidate.CopyMask()));
        var readback=new PortraitPngReadback(new(new string('a',64),new string('b',64),1),
            ImmutableDictionary<PortraitMaterialKey,PortraitCachedImage>.Empty.Add(new("player","0001"),image)){Mapping=mapping};
        Assert.NotNull(readback.Select(Player(),State(),false));
        Assert.Null(readback.Select(Player(2,1),State(),false));Assert.Null(readback.Select(Player(),State(),true));
        Assert.Null((readback with {Mapping=null}).Select(Player(),State(),false));
    }
    [Fact]
    public void Truncation_duplicates_and_palette_overflow_reject()
    {
        byte[] raw=Raw();for(int i=0;i<raw.Length;i++)Assert.ThrowsAny<FormatException>(()=>PortraitMapping.ParseLayoutForOfflineTests(raw.AsSpan(0,i)));
        Assert.ThrowsAny<FormatException>(()=>PortraitMapping.ParseLayoutForOfflineTests([..raw,0]));
        byte[] overflow=Raw();BinaryPrimitives.WriteUInt32LittleEndian(overflow.AsSpan(16),1000000000);
        Assert.Throws<SpritePixelException>(()=>PortraitMapping.ParseLayoutForOfflineTests(overflow));
        byte[] duplicate=Raw();BinaryPrimitives.WriteUInt16LittleEndian(duplicate.AsSpan(4+207+4+1),7000);
        Assert.Throws<CatalogDecodeException>(()=>PortraitMapping.ParseLayoutForOfflineTests(duplicate));
    }
}
