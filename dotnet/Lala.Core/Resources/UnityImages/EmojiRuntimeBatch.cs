namespace Lala.Core.Resources;

// Offline composition seam only until the reviewed full official closure is implemented.
// No production factory accepts caller-provided pixels or a claimed source fingerprint.
internal sealed class EmojiRuntimeBatch
{
    internal string SourceFingerprint {get;}
    private readonly Func<CancellationToken,EmojiPixelBatch> rebuild;
    private readonly string expected;
    private EmojiRuntimeBatch(string source,Func<CancellationToken,EmojiPixelBatch> rebuild)
    {UnityReadCursor.Require(source.Length==64&&source.All(c=>c is >= '0' and <= '9' or >= 'a' and <= 'f'),"Invalid emoji source fingerprint");ArgumentNullException.ThrowIfNull(rebuild);SourceFingerprint=source;this.rebuild=rebuild;expected=rebuild(default).Fingerprint;}
    internal static EmojiRuntimeBatch ForOfflineTests(string source,Func<CancellationToken,EmojiPixelBatch> rebuild)=>new(source,rebuild);
    internal EmojiPixelBatch Rebuild(CancellationToken token)
    {
        var batch=rebuild(token);UnityReadCursor.Require(batch.Fingerprint==expected,"Emoji batch changed since preparation");return batch;
    }
}
