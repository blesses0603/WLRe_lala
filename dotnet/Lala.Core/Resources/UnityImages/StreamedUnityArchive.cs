using System.Collections.Frozen;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

// Opt-in virtual archive index. No full expanded archive allocation or mutable
// pathname lookup. Caller owns the verified source lease and all returned copies.
internal sealed class StreamedUnityArchive
{
    internal const int MaximumBlockBytes=1024*1024,MaximumSliceBytes=16*1024*1024;
    internal const long MaximumLogicalBytes=1024L*1024*1024;
    internal sealed record Entry(string Name,long Offset,long Size,bool IsResource);
    private sealed record Block(long PackedOffset,int Packed,long PlainOffset,int Plain,uint Compression);
    private readonly VerifiedBundleBlockSource source;private readonly Block[] blocks;
    private readonly FrozenDictionary<string,Entry> entries;private readonly SemaphoreSlim gate=new(1,1);
    internal IReadOnlyList<Entry> Entries {get;}
    internal long LogicalBytes {get;}
    internal string SourceSha256=>source.Receipt.Sha256;
    private StreamedUnityArchive(VerifiedBundleBlockSource source,Block[] blocks,List<Entry> entries,long total)
    {this.source=source;this.blocks=blocks;this.entries=entries.ToFrozenDictionary(e=>e.Name,StringComparer.Ordinal);Entries=Array.AsReadOnly(entries.ToArray());LogicalBytes=total;}
    internal static async Task<StreamedUnityArchive> CreateAsync(VerifiedBundleBlockSource source,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(source);token.ThrowIfCancellationRequested();long size=source.Receipt.Spec.Size;
        var header=await source.ReadRangeAsync(0,(int)Math.Min(512,size),token).ConfigureAwait(false);
        var r=new UnityReadCursor(header,true);Require(r.NullString(7)=="UnityFS","Unsupported staged Unity signature");
        uint version=r.U32();Require(version is 6 or 7 or 8,"Unsupported staged Unity version");r.NullString(127);
        Require(r.NullString(127)=="2021.3.45f2"&&r.I64()==size,"Unreviewed staged engine or size");
        uint packed=r.U32(),plain=r.U32(),flags=r.U32();
        Require(packed is >0 and <=BoundedUnityBundle.MaximumBlockInfoBytes&&plain is >0 and <=BoundedUnityBundle.MaximumBlockInfoBytes&&
            (flags&~0x2ffU)==0&&(flags&0x40)!=0&&(flags&0x100)==0,"Invalid staged block metadata flags");
        if(version>=7)r.Align(16);long dataStart=r.Position;bool atEnd=(flags&0x80)!=0;
        long infoStart=atEnd?size-packed:dataStart;Require(infoStart>=dataStart&&packed<=size-infoStart,"Staged metadata exceeds source");
        var encoded=await source.ReadRangeAsync(infoStart,(int)packed,token).ConfigureAwait(false);var info=new byte[(int)plain];
        BoundedUnityBundle.ExpandInto(encoded,info,flags&0x3f,token);
        if(!atEnd)dataStart+=packed;if((flags&0x200)!=0)dataStart=(dataStart+15)/16*16;
        long dataEnd=atEnd?infoStart:size;Require(dataStart<=dataEnd,"Invalid staged data span");
        var ir=new UnityReadCursor(info,true);ir.Take(16);int count=ir.Count(4096,10);Require(count>0,"Missing staged blocks");
        var blocks=new Block[count];long packedAt=dataStart,plainAt=0;
        for(int i=0;i<count;i++)
        {
            token.ThrowIfCancellationRequested();uint expanded=ir.U32(),compressed=ir.U32(),compression=ir.U16();
            Require(expanded is >0 and <=MaximumBlockBytes&&compressed is >0 and <=MaximumBlockBytes&&compression is 0 or 2 or 3,"Staged block exceeds reviewed bounds or compression");
            Require(compressed<=dataEnd-packedAt&&expanded<=MaximumLogicalBytes-plainAt,"Staged aggregate span exceeds bound");
            blocks[i]=new(packedAt,(int)compressed,plainAt,(int)expanded,compression);packedAt+=compressed;plainAt+=expanded;
        }
        Require(packedAt==dataEnd,"Staged compressed data span mismatch");
        count=ir.Count(128,21);Require(count>0,"Missing staged directory");var entries=new List<Entry>(count);var names=new HashSet<string>(StringComparer.Ordinal);long end=0;
        for(int i=0;i<count;i++)
        {
            token.ThrowIfCancellationRequested();long offset=ir.I64(),length=ir.I64();uint entryFlags=ir.U32();string name=ir.NullString(255);
            Require(offset>=end&&length>0&&offset<=plainAt&&length<=plainAt-offset&&entryFlags is 0 or 4,"Invalid staged entry span or flags");
            Require(name.Length>0&&name.All(c=>char.IsAsciiLetterOrDigit(c)||c is '-' or '_' or '.')&&name is not "." and not ".."&&names.Add(name),"Invalid staged entry identity");
            entries.Add(new(name,offset,length,entryFlags==0));end=offset+length;
        }
        ir.End();foreach(var e in entries.Where(e=>e.IsResource))Require(e.Name.EndsWith(".resS",StringComparison.Ordinal)&&entries.Any(o=>!o.IsResource&&o.Name==e.Name[..^5]),"Unpaired staged resource");
        source.EnsureOpen(token);return new(source,blocks,entries,plainAt);
    }
    internal async Task<byte[]> ReadAsync(string entryName,long offset,int count,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(entries.TryGetValue(entryName,out var entry),"Entry is outside exact staged archive");
        Require(offset>=0&&count is >0 and <=MaximumSliceBytes&&offset<=entry!.Size-count,"Staged entry slice exceeds bound");
        await gate.WaitAsync(token).ConfigureAwait(false);
        try
        {
            token.ThrowIfCancellationRequested();var result=new byte[count];long from=entry!.Offset+offset,to=from+count;int written=0;
            foreach(var block in blocks)
            {
                token.ThrowIfCancellationRequested();if(block.PlainOffset>=to)break;if(block.PlainOffset+block.Plain<=from)continue;
                var packed=await source.ReadRangeAsync(block.PackedOffset,block.Packed,token).ConfigureAwait(false);
                var plain=new byte[block.Plain];BoundedUnityBundle.ExpandInto(packed,plain,block.Compression,token);
                long start=Math.Max(from,block.PlainOffset),end=Math.Min(to,block.PlainOffset+block.Plain);int length=(int)(end-start);
                plain.AsSpan((int)(start-block.PlainOffset),length).CopyTo(result.AsSpan((int)(start-from)));written+=length;
            }
            Require(written==count,"Incomplete staged entry slice");source.EnsureOpen(token);return result;
        }
        finally{gate.Release();}
    }
}
