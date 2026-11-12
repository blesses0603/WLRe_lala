using System.Buffers.Binary;
using System.Security.Cryptography;
namespace Lala.Core.Resources;

// A checksum observation bound to an exact manifest spec; not a memory-owned
// source, immutable file handle, provenance grant or runtime publication.
internal sealed record BundleStreamReceipt(BundleSourceSpec Spec,string Sha256);
internal static class BundleStreamVerifier
{
    internal const int BufferBytes=64*1024;
    internal const long MaximumBytes=64L*1024*1024;
    // Caller owns both streams. Output is provisional until successful return;
    // consumers must discard it on failure, never expose partially verified bytes.
    internal static async Task<BundleStreamReceipt> VerifyAsync(BundleSourceSpec spec,Stream input,Stream? provisionalOutput=null,
        string? expectedSha256=null,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(spec);ArgumentNullException.ThrowIfNull(input);token.ThrowIfCancellationRequested();
        if(spec.Size is <=0 or >MaximumBytes)throw new BundleSourceException(BundleSourceFailure.Budget,"Streamed bundle exceeds disk-stage bound");
        if(expectedSha256 is not null && (expectedSha256.Length!=64||expectedSha256.Any(c=>!(c is >= '0' and <= '9' or >= 'a' and <= 'f'))))
            throw new ArgumentException("Invalid expected bundle SHA",nameof(expectedSha256));
        using var md5=IncrementalHash.CreateHash(HashAlgorithmName.MD5);
        using var sha=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        byte[] buffer=new byte[BufferBytes];long length=0;uint crc=uint.MaxValue;
        while(true)
        {
            token.ThrowIfCancellationRequested();int requested=(int)Math.Min(buffer.Length,spec.Size-length+1);
            int count=await input.ReadAsync(buffer.AsMemory(0,requested),token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();
            if(count<0||count>requested||count>spec.Size-length)throw new BundleSourceException(BundleSourceFailure.ResponseLength,"Streamed bundle exceeds declared length");
            if(count==0)break;
            length+=count;md5.AppendData(buffer,0,count);sha.AppendData(buffer,0,count);
            for(int i=0;i<count;i++){if((i&4095)==0)token.ThrowIfCancellationRequested();crc=(crc>>8)^CrcTable[(crc^buffer[i])&255];}
            if(provisionalOutput is not null)await provisionalOutput.WriteAsync(buffer.AsMemory(0,count),token).ConfigureAwait(false);
        }
        if(length!=spec.Size)throw new BundleSourceException(BundleSourceFailure.ResponseLength,"Truncated streamed bundle");
        byte[] crcBytes=new byte[4];BinaryPrimitives.WriteUInt32LittleEndian(crcBytes,crc^uint.MaxValue);
        string digest=Convert.ToHexStringLower(sha.GetHashAndReset());
        if(Convert.ToHexStringLower(md5.GetHashAndReset())!=spec.Md5||Convert.ToHexStringLower(crcBytes)!=spec.Crc32Le||expectedSha256 is not null&&digest!=expectedSha256)
            throw new BundleSourceException(BundleSourceFailure.Checksum,"Streamed bundle checksum mismatch");
        token.ThrowIfCancellationRequested();return new(spec,digest);
    }
    private static readonly uint[] CrcTable=Enumerable.Range(0,256).Select(value=>
    {uint crc=(uint)value;for(int bit=0;bit<8;bit++)crc=(crc&1)==0?crc>>1:(crc>>1)^0xedb88320u;return crc;}).ToArray();
}
