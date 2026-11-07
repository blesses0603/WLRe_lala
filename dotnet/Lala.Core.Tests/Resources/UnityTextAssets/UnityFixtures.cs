using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lala.Core.Resources;

namespace Lala.Core.Tests.Resources;

internal static class UnityFixtures
{
    internal const string Path = "Assets/ResourcesBuild/Data/Owned.bytes";
    internal static readonly byte[] Payload = Convert.FromHexString("0001fffe8041424300c3287f");
    internal static byte[] File(string name)
    {
        using var stream = typeof(UnityFixtures).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityTextAssets.Fixtures." + name)!;
        using var output = new MemoryStream(); stream.CopyTo(output); return output.ToArray();
    }
    internal static int Offset(string name) { using var j = JsonDocument.Parse(File("layout.json")); return j.RootElement.GetProperty(name).GetInt32(); }
    internal static byte[] Patch(string field, int value, int delta = 0)
    { byte[] b = File("owned.assets"); BinaryPrimitives.WriteInt32LittleEndian(b.AsSpan(Offset(field) + delta), value); return b; }
    internal static byte[] Wrap(byte[] assets, string cab = "CAB-owned", uint flags = 0x40, int version = 8)
    {
        using var info = new MemoryStream(); using var iw = new BinaryWriter(info);
        iw.Write(new byte[16]); Write32(iw, 1); Write32(iw, assets.Length); Write32(iw, assets.Length); iw.Write(new byte[2]);
        Write32(iw, 1); Write64(iw, 0); Write64(iw, assets.Length); Write32(iw, 4); iw.Write(Encoding.UTF8.GetBytes(cab)); iw.Write((byte)0);
        byte[] meta = info.ToArray(); using var output = new MemoryStream(); using var w = new BinaryWriter(output);
        w.Write(Encoding.UTF8.GetBytes("UnityFS\0")); Write32(w, version); w.Write(Encoding.UTF8.GetBytes("5.x.x\0")); w.Write(Encoding.UTF8.GetBytes("2021.3.45f2\0"));
        long lengthPos = output.Position; Write64(w, 0); Write32(w, meta.Length); Write32(w, meta.Length); Write32(w, unchecked((int)flags));
        if (version >= 7) Pad(w, 16);
        bool atEnd = (flags & 0x80) != 0;
        if (!atEnd) w.Write(meta);
        if ((flags & 0x200) != 0) Pad(w, 16);
        w.Write(assets); if (atEnd) w.Write(meta);
        byte[] result = output.ToArray(); BinaryPrimitives.WriteInt64BigEndian(result.AsSpan((int)lengthPos), result.Length); return result;
    }
    private static void Pad(BinaryWriter w, int n) { while (w.BaseStream.Position % n != 0) w.Write((byte)0); }
    private static void Write32(BinaryWriter w, int n) { Span<byte> b = stackalloc byte[4]; BinaryPrimitives.WriteInt32BigEndian(b, n); w.Write(b); }
    private static void Write64(BinaryWriter w, long n) { Span<byte> b = stackalloc byte[8]; BinaryPrimitives.WriteInt64BigEndian(b, n); w.Write(b); }
    internal static VerifiedBundleSource Source(byte[] bytes, string name = "owned.bundle")
    {
        var json = BundleSourceFixtures.Index(); var row = json["bundles"]![0]!;
        row["name"] = name; row["file_size"] = (long)bytes.Length; row["file_hash"] = Convert.ToHexStringLower(MD5.HashData(bytes));
        row["file_crc"] = ManifestIdentity.Crc32LittleEndian(bytes); row["encrypted"] = false;
        var manifest = YooAssetManifest.Parse(BundleSourceFixtures.Encode(json));
        return VerifiedBundleSource.Verify(new("1.3.21", manifest, manifest.Bundles[0]), bytes, BundleAcquisition.Cache);
    }
    internal static byte[] Extract(byte[] bundle) => UnityTextAssetExtractor.Extract(Path, [Source(bundle)]);
}
