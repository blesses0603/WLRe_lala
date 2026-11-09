using System.Text.Json;
using System.Buffers.Binary;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class UnityShaderTests
{
    private static JsonElement Fixture()
    {
        using var stream=typeof(UnityShaderTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Portraits.shaders.json")!;
        using var doc=JsonDocument.Parse(stream);return doc.RootElement.Clone();
    }
    private static byte[] Asset()=>Convert.FromBase64String(Fixture().GetProperty("asset").GetString()!);
    private static BoundedSerializedFile Parse(byte[] bytes)=>BoundedSerializedFile.Read(new("owned.bundle","CAB-owned-shader"),bytes,new(),default,allowShaders:true);
    private static UnityShaderLayout Layout()=>Parse(Asset()).Objects.Values.Single().ShaderLayout!;
    public static IEnumerable<object[]> Cases()=>Fixture().GetProperty("cases").EnumerateArray().Select(x=>new object[]{x.Clone()});
    [Theory,MemberData(nameof(Cases))]
    public void Independent_writer_branches_parse_but_cannot_pass_official_shader_pin(JsonElement row)
    {
        var layout=Layout();var bytes=Convert.FromBase64String(row.GetProperty("bytes").GetString()!);
        if(!row.GetProperty("read_ok").GetBoolean()){Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.Read(bytes,layout));return;}
        var result=UnityShaderObjects.Read(bytes,layout);
        Assert.Equal(Fixture().GetProperty("blob_sha256").GetString(),result.BlobSha256);
        Assert.Equal(row.GetProperty("name").GetString()=="unknown-name"?"unknown":"UI_ProfilePhotoWithMask",result.Name);
        Assert.Equal(row.GetProperty("name").GetString()=="black-default"?"black":"white",result.MaskDefault);
        Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.VerifyPortrait(bytes,layout));
    }
    [Fact]
    public void Exact_shader_shape_and_independent_opt_in_are_required()
    {
        byte[] bytes=Asset();Assert.Equal(Fixture().GetProperty("asset_sha256").GetString(),SpritePng.Hash(bytes));
        var identity=new UnityFileIdentity("owned.bundle","CAB-owned-shader");
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(identity,bytes,new(),default));
        Assert.Throws<UnityTextAssetException>(()=>BoundedSerializedFile.Read(identity,bytes,new(),default,allowImages:true,allowMaterials:true));
        var parsed=Parse(bytes);Assert.Equal(48,parsed.Objects.Values.Single().ClassId);
        int index=bytes.AsSpan().IndexOf(System.Text.Encoding.UTF8.GetBytes("compressedBlob"));Assert.True(index>0);bytes[index]=(byte)'X';
        Assert.Throws<UnityTextAssetException>(()=>Parse(bytes));
    }
    [Fact]
    public void Truncations_trailing_bytes_budget_and_cancellation_are_rejected()
    {
        var bytes=Convert.FromBase64String(Fixture().GetProperty("cases")[0].GetProperty("bytes").GetString()!);var layout=Layout();
        for(int i=0;i<bytes.Length;i++)Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.Read(bytes.AsMemory(0,i),layout));
        Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.Read(bytes.Append((byte)0).ToArray(),layout));
        Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.Read(new byte[8*1024*1024+1],layout));
        Assert.ThrowsAny<OperationCanceledException>(()=>UnityShaderObjects.Read(bytes,layout,new(true)));
    }
    [Fact]
    public void Oversized_array_and_invalid_boolean_fail_at_their_fields()
    {
        var fixture=Fixture();var original=Convert.FromBase64String(fixture.GetProperty("cases")[0].GetProperty("bytes").GetString()!);var layout=Layout();
        byte[] bytes=original.ToArray();
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(fixture.GetProperty("offsets").GetProperty("platforms").GetInt32()),16385);
        Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.Read(bytes,layout));
        bytes=original.ToArray();bytes[fixture.GetProperty("offsets").GetProperty("m_ShaderIsBaked").GetInt32()]=2;
        Assert.Throws<UnityTextAssetException>(()=>UnityShaderObjects.Read(bytes,layout));
    }

}
