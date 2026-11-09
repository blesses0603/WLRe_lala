using System.Buffers.Binary;
using System.IO.Compression;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class EmojiPixelBatchTests
{
    private static JsonDocument Fixture(string name="batch")=>JsonDocument.Parse(typeof(EmojiPixelBatchTests).Assembly.GetManifestResourceStream($"Lala.Core.Tests.Resources.Atlases.{name}.json")!);
    private static EmojiMapping Mapping(){using var d=Fixture();return EmojiMapping.ParseLayoutForOfflineTests(Convert.FromBase64String(d.RootElement.GetProperty("raw").GetString()!));}
    private static AtlasPixelCandidate[] Images()
    {
        using var d=Fixture();return d.RootElement.GetProperty("images").EnumerateObject().Select(p=>new AtlasPixelCandidate(p.Name,3,5,Convert.FromBase64String(p.Value.GetProperty("pixels").GetString()!),new string('a',64))).ToArray();
    }
    private static byte[] Pixels(byte[] png,int width,int height)
    {
        Assert.Equal(new byte[]{137,80,78,71,13,10,26,10},png[..8]);
        Assert.Equal((uint)width,BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(16)));Assert.Equal((uint)height,BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(20)));
        int count=(int)BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(33));using var data=new MemoryStream(png,41,count);using var z=new ZLibStream(data,CompressionMode.Decompress);
        var scan=new byte[height*(width*4+1)];z.ReadExactly(scan);Assert.Equal(-1,z.ReadByte());var pixels=new byte[height*width*4];
        for(int y=0;y<height;y++){Assert.Equal(0,scan[y*(width*4+1)]);scan.AsSpan(y*(width*4+1)+1,width*4).CopyTo(pixels.AsSpan(y*width*4));}return pixels;
    }
    [Fact]
    public void Python_tokens_hidden_and_shared_first_frames_match_complete_PNG_pixels()
    {
        using var d=Fixture();var batch=EmojiPixelBatch.Create(Mapping(),Images());Assert.False(batch.HasVerifiedProvenance);Assert.Equal(2,batch.Images.Count);
        foreach(var token in d.RootElement.GetProperty("tokens").EnumerateObject())
        {
            int id=int.Parse(token.Name);var image=batch.Find(id)!;Assert.Equal(token.Value.GetProperty("frame").GetString(),image.Frame);
            Assert.Equal(token.Value.GetProperty("show").GetBoolean(),batch.Mapping.Find(id)!.ShowInList);
            Assert.Equal(token.Value.GetProperty("pixels").GetString(),SpritePng.Hash(Pixels(image.CopyPng(),image.Width,image.Height)));
        }
        Assert.Same(batch.Find(1),batch.Find(3));Assert.Null(batch.Find(0));Assert.Null(batch.Find(4));
        var copy=batch.Find(1)!.CopyPng();copy[0]=0;Assert.Equal(137,batch.Find(1)!.CopyPng()[0]);
    }
    [Fact]
    public void Missing_duplicate_and_late_decode_failures_never_return_a_batch()
    {
        var images=Images();Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.Create(Mapping(),images.Take(1)));
        Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.Create(Mapping(),images.Append(images[0])));
        IEnumerable<AtlasPixelCandidate> Bad(){foreach(var image in images)yield return image;throw new IOException("owned late failure");}
        Assert.Throws<IOException>(()=>EmojiPixelBatch.Create(Mapping(),Bad()));
    }
    [Fact]
    public void Fingerprint_is_order_independent_but_binds_mapping_pixels_and_input_bytes()
    {
        var images=Images();var a=EmojiPixelBatch.Create(Mapping(),images);Assert.Equal(a.Fingerprint,EmojiPixelBatch.Create(Mapping(),images.Reverse()).Fingerprint);
        images[0]=new(images[0].Name,3,5,images[0].CopyPixels(),new string('b',64));Assert.NotEqual(a.Fingerprint,EmojiPixelBatch.Create(Mapping(),images).Fingerprint);
        var p=images[0].CopyPixels();p[0]^=255;images[0]=new(images[0].Name,3,5,p,new string('a',64));Assert.NotEqual(a.Fingerprint,EmojiPixelBatch.Create(Mapping(),images).Fingerprint);
        using var d=Fixture();var raw=Convert.FromBase64String(d.RootElement.GetProperty("raw").GetString()!);raw[11]=1;
        Assert.NotEqual(a.Fingerprint,EmojiPixelBatch.Create(EmojiMapping.ParseLayoutForOfflineTests(raw),Images()).Fingerprint);
    }
    [Fact]
    public void Unwanted_frames_are_ignored_but_enumeration_and_cancellation_remain_bounded()
    {
        var junk=new AtlasPixelCandidate("unused",1,1,new byte[4],"unused");var images=Images();
        Assert.Equal(EmojiPixelBatch.Create(Mapping(),images).Fingerprint,EmojiPixelBatch.Create(Mapping(),images.Append(junk)).Fingerprint);
        Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.Create(Mapping(),Enumerable.Repeat(junk,2049)));
        Assert.Throws<OperationCanceledException>(()=>EmojiPixelBatch.Create(Mapping(),images,new(true)));
        using var stop=new CancellationTokenSource();IEnumerable<AtlasPixelCandidate> Cancel(){yield return images[0];stop.Cancel();yield return images[1];}
        Assert.Throws<OperationCanceledException>(()=>EmojiPixelBatch.Create(Mapping(),Cancel(),stop.Token));
    }
    [Theory][InlineData(0,1,0)][InlineData(513,1,2052)][InlineData(1,1,3)]
    public void Malformed_image_geometry_is_rejected(int width,int height,int length)
        =>Assert.Throws<SpritePixelException>(()=>SpritePng.EncodeEmoji(new("Emoji_001_1",width,height,new byte[length],"owned")));
    [Fact]
    public void Per_image_compressed_quota_is_not_bypassed_by_valid_geometry()
    {
        var bytes=new byte[512*512*4];new Random(17).NextBytes(bytes);var image=new AtlasPixelCandidate("Emoji_001_1",512,512,bytes,"owned");
        Assert.Contains("per-image quota",Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.Create(Mapping(),Images().Prepend(image))).Message);
    }
    [Fact]
    public void Total_PNG_quota_counts_distinct_frames_even_when_pixels_match()
    {
        var raw=new byte[4+17*8];BinaryPrimitives.WriteInt32LittleEndian(raw,17);
        for(int i=0;i<17;i++){int offset=4+i*8;raw[offset]=(byte)(i+1);raw[offset+2]=(byte)(i+1);raw[offset+3]=1;}
        var mapping=EmojiMapping.ParseLayoutForOfflineTests(raw);var bytes=new byte[384*384*4];new Random(29).NextBytes(bytes);
        var images=mapping.Rows.Select(row=>new AtlasPixelCandidate(row.FirstFrame,384,384,bytes,"owned"));
        Assert.Contains("batch exceeds quota",Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.Create(mapping,images)).Message);
    }
    [Fact]
    public void Full_atlas_path_requires_complete_wanted_set_and_exact_backlinks()
    {
        using var d=Fixture("pixels");var objects=new Dictionary<long,UnityObject>();long n=0;
        foreach(var o in d.RootElement.GetProperty("cases")[30].GetProperty("objects").EnumerateArray())objects[++n]=new(o.GetProperty("class").GetInt32(),Convert.FromBase64String(o.GetProperty("bytes").GetString()!));
        var owner=new UnityFileIdentity("owned","CAB-owned");var file=new BoundedSerializedFile{Identity=owner,Objects=objects,Container=[],Externals=[]};var selected=new UnitySelectedObjects([file],[]);
        Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.FromAtlas(Mapping(),selected,owner,1));
        byte[] raw=[1,0,0,0,1,0,1,1,0,0,0,0];var mapping=EmojiMapping.ParseLayoutForOfflineTests(raw);
        var batch=EmojiPixelBatch.FromAtlas(mapping,selected,owner,1);Assert.Single(batch.Images);Assert.False(batch.HasVerifiedProvenance);
        Assert.Equal(Convert.FromBase64String(d.RootElement.GetProperty("cases")[30].GetProperty("pixels").GetString()!),Pixels(batch.Find(1)!.CopyPng(),3,5));
        Assert.Throws<UnityTextAssetException>(()=>EmojiPixelBatch.FromAtlas(mapping,selected,owner,2));
    }
}
