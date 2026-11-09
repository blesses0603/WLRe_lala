using System.Collections.Frozen;
using System.Text.Json;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed class EmojiPngCandidate
{
    private readonly byte[] png;
    internal string Frame {get;}
    internal int Width {get;}
    internal int Height {get;}
    internal string InputFingerprint {get;}
    internal string PixelSha256 {get;}
    internal string PngSha256 {get;}
    internal int PngLength=>png.Length;
    internal byte[] CopyPng()=>png.ToArray();
    internal EmojiPngCandidate(AtlasPixelCandidate pixels,CancellationToken token)
    {
        Frame=pixels.Name;Width=pixels.Width;Height=pixels.Height;InputFingerprint=pixels.InputFingerprint;PixelSha256=pixels.PixelSha256;
        png=SpritePng.EncodeEmoji(pixels,token);Require(png.Length<=1024*1024,"Emoji PNG exceeds per-image quota");PngSha256=SpritePng.Hash(png);
    }
}
// Complete pixel/PNG observation only: no official source admission, storage or publication.
internal sealed class EmojiPixelBatch
{
    internal EmojiMapping Mapping {get;}
    internal FrozenDictionary<string,EmojiPngCandidate> Images {get;}
    internal string Fingerprint {get;}
    internal bool HasVerifiedProvenance=>false;
    internal EmojiPngCandidate? Find(int token)=>Mapping.Find(token) is { } row?Images[row.FirstFrame]:null;
    private EmojiPixelBatch(EmojiMapping mapping,Dictionary<string,EmojiPngCandidate> images)
    {
        Mapping=mapping;Images=images.ToFrozenDictionary(StringComparer.Ordinal);
        Fingerprint=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new{mapping.SourceSha256,Images=images.OrderBy(p=>p.Key,StringComparer.Ordinal).Select(p=>new{p.Key,p.Value.Width,p.Value.Height,p.Value.InputFingerprint,p.Value.PixelSha256,p.Value.PngSha256})}));
    }
    internal static EmojiPixelBatch Create(EmojiMapping mapping,IEnumerable<AtlasPixelCandidate> decoded,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();var images=new Dictionary<string,EmojiPngCandidate>(StringComparer.Ordinal);long bytes=0;int inspected=0;
        foreach(var candidate in decoded)
        {
            token.ThrowIfCancellationRequested();Require(++inspected<=2048,"Emoji decoded list exceeds atlas bound");
            if(!mapping.Frames.Contains(candidate.Name))continue;
            Require(!images.ContainsKey(candidate.Name),"Duplicate emoji first frame");
            var image=new EmojiPngCandidate(candidate,token);bytes+=image.PngLength;
            Require(bytes<=8*1024*1024,"Emoji PNG batch exceeds quota");images.Add(candidate.Name,image);
        }
        Require(images.Count==mapping.Frames.Count && mapping.Frames.All(images.ContainsKey),"Incomplete emoji first-frame set");
        token.ThrowIfCancellationRequested();return new(mapping,images);
    }
    internal static EmojiPixelBatch FromAtlas(EmojiMapping mapping,UnitySelectedObjects selected,UnityFileIdentity atlasFile,long atlasId,
        UnityImageArchive? imageArchive=null,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();var atlas=UnityAtlasObjects.Read(selected.Resolve(atlasFile,new(0,atlasId),687078895)!.Object.Bytes,token);
        IEnumerable<AtlasPixelCandidate> Decode()
        {
            foreach(var pointer in atlas.Sprites)
            {
                token.ThrowIfCancellationRequested();var obj=selected.Resolve(atlasFile,pointer,213)!;
                var sprite=UnityImageObjects.Sprite(obj.Object.Bytes,token,true);
                if(mapping.Frames.Contains(sprite.Name))yield return AtlasSpritePixels.Extract(selected,atlasFile,atlasId,obj.File,obj.PathId,sprite.Name,token,imageArchive);
            }
        }
        return Create(mapping,Decode(),token);
    }
}
