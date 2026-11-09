using System.Buffers.Binary;
using System.Security.Cryptography;
using Avalonia.Media.Imaging;

namespace Lala.Desktop;

// UI-thread owned, visible-frame cache. Every call still obtains current admitted bytes.
// Content reuse never substitutes for the runtime's version/account/revocation check.
internal sealed class ItemBitmapCache : IDisposable
{
    private sealed record Entry(byte[] Bytes, Bitmap Bitmap);
    private readonly Dictionary<string, Entry> entries = new(StringComparer.Ordinal);
    private readonly HashSet<string> used = new(StringComparer.Ordinal);
    internal int DecodeCount { get; private set; }
    internal int RetainedCount => entries.Count;
    internal void BeginFrame() => used.Clear();
    internal Bitmap? Read(Func<ushort, byte[]?>? reader, ushort id)
    {
        try
        {
            if (reader?.Invoke(id) is not { Length: > 0 and <= 4194304 } png) return null;
            var copy = png.ToArray();
            if (copy.Length < 33 || !copy.AsSpan(0, 8).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }) ||
                BinaryPrimitives.ReadUInt32BigEndian(copy.AsSpan(8)) != 13 || !copy.AsSpan(12, 4).SequenceEqual("IHDR"u8) ||
                BinaryPrimitives.ReadUInt32BigEndian(copy.AsSpan(16)) is 0 or > 512 ||
                BinaryPrimitives.ReadUInt32BigEndian(copy.AsSpan(20)) is 0 or > 512 ||
                copy[24] != 8 || copy[25] != 6 || copy[26] != 0 || copy[27] != 0 || copy[28] != 0) return null;
            string key = Convert.ToHexStringLower(SHA256.HashData(copy));
            if (entries.TryGetValue(key, out var existing))
            {
                if (!copy.AsSpan().SequenceEqual(existing.Bytes)) return null;
                used.Add(key); return existing.Bitmap;
            }
            // A frame has at most 24 visible inventory cells. Never grow on arbitrary IDs.
            if (used.Count >= 24) return null;
            using var stream = new MemoryStream(copy, writable: false);
            var bitmap = new Bitmap(stream); DecodeCount++;
            if (bitmap.PixelSize.Width is not (> 0 and <= 512) || bitmap.PixelSize.Height is not (> 0 and <= 512))
            { bitmap.Dispose(); return null; }
            entries.Add(key, new(copy, bitmap)); used.Add(key); return bitmap;
        }
        catch (Exception) { return null; }
    }
    internal void EndFrame()
    {
        foreach (string key in entries.Keys.Where(k => !used.Contains(k)).ToArray())
        { entries[key].Bitmap.Dispose(); entries.Remove(key); }
    }
    public void Dispose()
    {
        foreach (var entry in entries.Values) entry.Bitmap.Dispose();
        entries.Clear(); used.Clear();
    }
}
