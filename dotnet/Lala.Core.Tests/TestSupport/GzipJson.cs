using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;

namespace Lala.Core.Tests.TestSupport;

// Existing byte-literal callers remain supported. New large fixture families can use
// named embedded resources without adding compressed bytes to C# compilation syntax.
internal static class GzipJson
{
    internal static string Decode(ReadOnlySpan<byte> compressedJson)
    {
        using var input = new MemoryStream(compressedJson.ToArray(), writable: false);
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        using var reader = new StreamReader(gzip, new UTF8Encoding(false, true), detectEncodingFromByteOrderMarks: false);
        return reader.ReadToEnd();
    }

    internal static string DecodeResource(string resourceName, string compressedSha256, string decodedSha256,
        int maxCompressedBytes = 500_000, int maxDecodedBytes = 32 * 1024 * 1024)
    {
        using var input = typeof(GzipJson).Assembly.GetManifestResourceStream(resourceName)
            ?? throw new InvalidDataException("Missing gzip JSON fixture resource: " + resourceName);
        return DecodeVerified(input, compressedSha256, decodedSha256, maxCompressedBytes, maxDecodedBytes);
    }

    // Tests can exercise corrupt streams without embedding intentionally broken resources.
    internal static string DecodeVerified(Stream input, string compressedSha256, string decodedSha256,
        int maxCompressedBytes = 500_000, int maxDecodedBytes = 32 * 1024 * 1024)
    {
        if (maxCompressedBytes <= 0 || maxDecodedBytes <= 0)
            throw new ArgumentOutOfRangeException(nameof(maxCompressedBytes));
        byte[] compressed = ReadBounded(input, maxCompressedBytes);
        VerifyHash(compressed, compressedSha256);
        using var compressedStream = new MemoryStream(compressed, writable: false);
        using var gzip = new GZipStream(compressedStream, CompressionMode.Decompress);
        byte[] decoded = ReadBounded(gzip, maxDecodedBytes);
        VerifyHash(decoded, decodedSha256);
        return new UTF8Encoding(false, true).GetString(decoded);
    }

    private static byte[] ReadBounded(Stream input, int maximum)
    {
        using var output = new MemoryStream();
        Span<byte> buffer = stackalloc byte[8192];
        int count;
        while ((count = input.Read(buffer)) != 0)
        {
            if (count > maximum - output.Length) throw new InvalidDataException("Gzip JSON fixture exceeds byte limit");
            output.Write(buffer[..count]);
        }
        return output.ToArray();
    }

    private static void VerifyHash(byte[] bytes, string expected)
    {
        if (expected.Length != 64 || expected.Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f')) ||
            Convert.ToHexStringLower(SHA256.HashData(bytes)) != expected)
            throw new InvalidDataException("Gzip JSON fixture SHA-256 mismatch");
    }
}
