using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Collections.Frozen;
using System.Globalization;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed record EmojiRow(byte Token,byte Id,byte MarkId,byte Icon,uint TextId,bool ShowInList)
{
    internal string FirstFrame=>"Emoji_"+Icon.ToString("D3",CultureInfo.InvariantCulture)+"_1";
}
internal sealed class EmojiMapping
{
    internal const string KnownSha256="b21c48d487d83463332157e1d56af0a258f26cecf2e906ca518526badcd5a75b";
    internal ImmutableArray<EmojiRow> Rows {get;}
    internal FrozenSet<string> Frames {get;}
    internal string SourceSha256 {get;}
    internal bool Reviewed {get;}
    private EmojiMapping(ImmutableArray<EmojiRow> rows,string hash,bool reviewed)
    {Rows=rows;SourceSha256=hash;Reviewed=reviewed;Frames=rows.Select(r=>r.FirstFrame).ToFrozenSet(StringComparer.Ordinal);}
    internal EmojiRow? Find(int token)=>token>=1&&token<=Rows.Length?Rows[token-1]:null;
    internal static EmojiMapping Create(ReadOnlySpan<byte> raw,CancellationToken token=default)=>Read(raw,true,token);
    // Structural Python oracle fixtures only; cannot be captured as prepared sources.
    internal static EmojiMapping ParseLayoutForOfflineTests(ReadOnlySpan<byte> raw,CancellationToken token=default)=>Read(raw,false,token);
    private static EmojiMapping Read(ReadOnlySpan<byte> raw,bool reviewed,CancellationToken token)
    {
        token.ThrowIfCancellationRequested();Require(raw.Length is >=12 and <=2044,"EmojiData size exceeds bound");
        byte[] owned=raw.ToArray();string hash=SpritePng.Hash(owned);
        Require(!reviewed||hash==KnownSha256,"EmojiData source fingerprint is not reviewed");
        uint count=BinaryPrimitives.ReadUInt32LittleEndian(owned);
        Require(count is >0 and <=255&&owned.Length==4+count*8,"EmojiData count or length mismatch");
        var rows=ImmutableArray.CreateBuilder<EmojiRow>((int)count);
        for(int i=0;i<count;i++)
        {
            token.ThrowIfCancellationRequested();var r=owned.AsSpan(4+i*8,8);uint text=BinaryPrimitives.ReadUInt32LittleEndian(r[3..]);
            Require(r[0]!=0&&r[2]!=0&&text!=0&&r[7]<=1,"Invalid EmojiData row");
            rows.Add(new((byte)(i+1),r[0],r[1],r[2],text,r[7]==0));
        }
        token.ThrowIfCancellationRequested();return new(rows.MoveToImmutable(),hash,reviewed);
    }
}
