using System.Collections.Immutable;
namespace Lala.Core.Resources;

/// <summary>Display metadata only; tokens are not permission to send chat.</summary>
public sealed record EmojiGalleryEntry(byte Token,string ImageIdentity,int Width,int Height);
/// <summary>Revocable account-bound gallery. Retained metadata and copied PNGs cannot authorize effects.</summary>
public sealed class EmojiGalleryRequest
{
    private readonly EmojiPngReadback batch;
    private readonly Func<bool> current;
    public string Identity {get;}
    public ImmutableArray<EmojiGalleryEntry> Entries {get;}
    public bool IsCurrent=>current();
    internal EmojiGalleryRequest(EmojiPngReadback batch,Func<bool> current)
    {
        this.batch=batch;this.current=current;Identity=batch.SourceFingerprint+":"+batch.Batch.Fingerprint;
        Entries=batch.Batch.Mapping.Rows.Where(r=>r.ShowInList).Select(r=>
        {var image=batch.Batch.Find(r.Token)!;return new EmojiGalleryEntry(r.Token,image.PngSha256,image.Width,image.Height);}).ToImmutableArray();
    }
    public bool TryReadPng(byte token,out byte[]? png)
    {
        png=null;if(!IsCurrent||!Entries.Any(e=>e.Token==token))return false;
        var copy=batch.CopyPng(token);if(!IsCurrent||copy is null)return false;png=copy;return true;
    }
}
