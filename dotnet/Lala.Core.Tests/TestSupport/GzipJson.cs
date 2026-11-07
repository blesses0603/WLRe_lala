using System.IO.Compression;
using System.Text;

namespace Lala.Core.Tests.TestSupport;

// Generated fixtures use byte literals so their payloads do not consume the assembly's #US heap.
internal static class GzipJson
{
    internal static string Decode(ReadOnlySpan<byte> compressedJson)
    {
        using var input = new MemoryStream(compressedJson.ToArray(), writable: false);
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        using var reader = new StreamReader(gzip, new UTF8Encoding(false, true), detectEncodingFromByteOrderMarks: false);
        return reader.ReadToEnd();
    }
}
