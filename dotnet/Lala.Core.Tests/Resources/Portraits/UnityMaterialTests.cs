using System.Buffers.Binary;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;

public sealed class UnityMaterialTests
{
    private static JsonElement Fixture()
    {
        using var stream = typeof(UnityMaterialTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Portraits.materials.json")!;
        using var json = JsonDocument.Parse(stream); return json.RootElement.Clone();
    }
    public static IEnumerable<object[]> Cases() => Fixture().GetProperty("cases").EnumerateArray().Select(row => new object[] { row.Clone() });
    private static byte[] DefaultBytes() => Convert.FromBase64String(Fixture().GetProperty("cases")[0].GetProperty("bytes").GetString()!);
    [Theory, MemberData(nameof(Cases))]
    public void Independent_writer_materials_match_bounded_reader_and_reviewed_variants(JsonElement row)
    {
        byte[] bytes = Convert.FromBase64String(row.GetProperty("bytes").GetString()!);
        if (!row.GetProperty("read_ok").GetBoolean()) { Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Read(bytes)); return; }
        var material = UnityMaterialObjects.Read(bytes);
        if (!row.GetProperty("project_ok").GetBoolean()) { Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Project(material)); return; }
        var candidate = UnityMaterialObjects.Project(material);
        Assert.Equal("PhotoAvatarNPC_7214", candidate.Name);
        Assert.Equal(new UnityContainerPointer(1,7213), candidate.Texture); // Shared texture identity, never guessed from material name.
        Assert.Equal(new UnityContainerPointer(2,-1215708881511709531), candidate.Shader);
        Assert.Equal(.06f, candidate.MaskClip); Assert.Equal(14,candidate.Colors.Count);
        Assert.Equal(3f,candidate.Colors["_13_EyeColor_"].R);
        Assert.Equal(row.GetProperty("name").GetString()=="owned-local-mask" ? 99L : 0L, candidate.Mask.PathId);
        Array.Fill(bytes,(byte)0); Assert.Equal(4f,candidate.Colors["_13_EyeColor_"].G);
    }
    [Fact]
    public void Serialized_material_requires_separate_opt_in_and_exact_embedded_shape()
    {
        var fixture=Fixture(); byte[] bytes=Convert.FromBase64String(fixture.GetProperty("asset").GetString()!);
        Assert.Equal(fixture.GetProperty("asset_sha256").GetString(),SpritePng.Hash(bytes));
        var identity=new UnityFileIdentity("owned.bundle","CAB-owned-material");
        Assert.Throws<UnityTextAssetException>(() => BoundedSerializedFile.Read(identity,bytes,new(),default));
        Assert.Throws<UnityTextAssetException>(() => BoundedSerializedFile.Read(identity,bytes,new(),default,allowImages:true));
        var file=BoundedSerializedFile.Read(identity,bytes,new(),default,allowMaterials:true);
        Assert.Equal(21,file.Objects[1].ClassId); Assert.Equal(2,file.Externals.Count);
        Assert.Equal(7213,UnityMaterialObjects.Project(UnityMaterialObjects.Read(file.Objects[1].Bytes)).Texture.PathId);
        // Type-tree mutation, not object data: a reviewed shape cannot be silently substituted.
        int position=bytes.AsSpan().IndexOf(System.Text.Encoding.UTF8.GetBytes("m_SavedProperties"));
        Assert.True(position>0); bytes[position]=(byte)'x';
        Assert.Throws<UnityTextAssetException>(() => BoundedSerializedFile.Read(identity,bytes,new(),default,allowMaterials:true));
    }
    [Fact]
    public void Every_truncation_trailing_bytes_and_cancellation_are_rejected()
    {
        byte[] bytes=DefaultBytes();
        for(int length=0;length<bytes.Length;length++)
            Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Read(bytes.AsMemory(0,length)));
        Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Read(bytes.Append((byte)0).ToArray()));
        Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Read(new byte[128*1024+1]));
        Assert.ThrowsAny<OperationCanceledException>(() => UnityMaterialObjects.Read(bytes,new(true)));
    }
    [Fact]
    public void Huge_keyword_count_fails_before_allocation_and_invalid_boolean_is_rejected()
    {
        byte[] bytes=DefaultBytes(); int nameBytes=BinaryPrimitives.ReadInt32LittleEndian(bytes);
        int keywords=((4+nameBytes+3)/4)*4+12;
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(keywords),int.MaxValue);
        Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Read(bytes));
        bytes=DefaultBytes();bytes[keywords+12]=2;
        Assert.Throws<UnityTextAssetException>(() => UnityMaterialObjects.Read(bytes));
    }
}
