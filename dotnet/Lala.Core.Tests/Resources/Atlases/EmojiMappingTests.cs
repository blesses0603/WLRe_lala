using System.Buffers.Binary;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class EmojiMappingTests
{
    private static JsonDocument Fixture()=>JsonDocument.Parse(typeof(EmojiMappingTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.mapping.json")!);
    public static IEnumerable<object[]> Cases(){using var d=Fixture();foreach(var c in d.RootElement.GetProperty("cases").EnumerateArray())yield return [c.GetProperty("name").GetString()!];}
    internal static byte[] Owned(){using var d=Fixture();return Convert.FromBase64String(d.RootElement.GetProperty("cases")[0].GetProperty("raw").GetString()!);}
    [Theory][MemberData(nameof(Cases))]
    public void Actual_Python_rows_match_but_no_synthetic_data_passes_the_production_pin(string name)
    {
        using var d=Fixture();Assert.Equal(EmojiMapping.KnownSha256,d.RootElement.GetProperty("production_pin").GetString());
        var c=d.RootElement.GetProperty("cases").EnumerateArray().Single(c=>c.GetProperty("name").GetString()==name);var raw=Convert.FromBase64String(c.GetProperty("raw").GetString()!);
        Assert.Throws<UnityTextAssetException>(()=>EmojiMapping.Create(raw));
        var expected=c.GetProperty("expected");if(expected.ValueKind==JsonValueKind.Null){Assert.Throws<UnityTextAssetException>(()=>EmojiMapping.ParseLayoutForOfflineTests(raw));return;}
        var map=EmojiMapping.ParseLayoutForOfflineTests(raw);Assert.False(map.Reviewed);Assert.Equal(expected.EnumerateObject().Count(),map.Rows.Length);
        foreach(var p in expected.EnumerateObject())
        {
            int token=int.Parse(p.Name);var row=map.Find(token)!;Assert.Equal(token,(int)row.Token);
            Assert.Equal(p.Value.GetProperty("id").GetInt32(),row.Id);Assert.Equal(p.Value.GetProperty("mark_id").GetInt32(),row.MarkId);
            Assert.Equal(p.Value.GetProperty("sprite").GetString()+"_1",row.FirstFrame);Assert.Equal(p.Value.GetProperty("text_id").GetUInt32(),row.TextId);
            Assert.Equal(p.Value.GetProperty("show_in_list").GetBoolean(),row.ShowInList);
        }
    }
    [Fact]
    public void Shared_frame_is_deduplicated_without_losing_row_tokens_and_inputs_are_owned()
    {
        var b=Owned();var m=EmojiMapping.ParseLayoutForOfflineTests(b);Array.Fill(b,(byte)0);
        Assert.Equal(3,m.Rows.Length);Assert.Equal(2,m.Frames.Count);Assert.Equal(m.Find(1)!.FirstFrame,m.Find(3)!.FirstFrame);
        Assert.Equal(17,m.Find(1)!.Id);Assert.Equal(3,m.Find(2)!.Id);Assert.Null(m.Find(0));Assert.Null(m.Find(-1));Assert.Null(m.Find(4));Assert.Null(m.Find(int.MaxValue));
    }
    [Fact]
    public void Truncation_trailing_count_limit_and_cancellation_fail()
    {
        var b=Owned();for(int i=0;i<b.Length;i++)Assert.Throws<UnityTextAssetException>(()=>EmojiMapping.ParseLayoutForOfflineTests(b.AsSpan(0,i)));
        Assert.Throws<UnityTextAssetException>(()=>EmojiMapping.ParseLayoutForOfflineTests((byte[])[..b,0]));
        Assert.Throws<UnityTextAssetException>(()=>EmojiMapping.ParseLayoutForOfflineTests(new byte[2045]));
        BinaryPrimitives.WriteUInt32LittleEndian(b,uint.MaxValue);Assert.Throws<UnityTextAssetException>(()=>EmojiMapping.ParseLayoutForOfflineTests(b));
        Assert.Throws<OperationCanceledException>(()=>EmojiMapping.Create(Owned(),new(true)));
    }
}
