using System.Collections.Frozen;
using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

internal sealed record UnityMaterialColor(float R, float G, float B, float A);
internal sealed record UnityMaterialTexture(UnityContainerPointer Pointer, float ScaleX, float ScaleY, float OffsetX, float OffsetY);
internal sealed record UnityMaterialData(string Name, UnityContainerPointer Shader, bool HasKeywords,
    IReadOnlyDictionary<string, UnityMaterialTexture> Textures, IReadOnlyDictionary<string, float> Floats,
    IReadOnlyDictionary<string, UnityMaterialColor> Colors);
// Parsed claims only. Shader/PPtr resolution, exact source pins and publication are still required.
internal sealed record PortraitMaterialCandidate(string Name, UnityContainerPointer Shader,
    UnityContainerPointer Texture, UnityContainerPointer Mask, float MaskClip,
    IReadOnlyDictionary<string, UnityMaterialColor> Colors);

internal static class UnityMaterialObjects
{
    private static float Float(UnityReadCursor r)
    { float v = BitConverter.Int32BitsToSingle(r.I32()); Require(float.IsFinite(v), "Nonfinite material property"); return v; }
    private static void Bool(UnityReadCursor r) => Require(r.U8() <= 1, "Invalid material boolean");
    private static UnityContainerPointer Pointer(UnityReadCursor r)
    {
        var p = new UnityContainerPointer(r.I32(), r.I64());
        Require(p.FileId is >= 0 and <= 128 && (p.PathId != 0 || p.FileId == 0), "Invalid material pointer"); return p;
    }
    private static Dictionary<string, T> Map<T>(UnityReadCursor r, int limit, Func<UnityReadCursor, T> value, CancellationToken token)
    {
        int count = r.Count(limit, 8); var result = new Dictionary<string, T>(StringComparer.Ordinal);
        for (int i = 0; i < count; i++)
        { token.ThrowIfCancellationRequested(); string key = r.String(256, false); Require(result.TryAdd(key, value(r)), "Duplicate material property"); }
        return result;
    }
    private static int Strings(UnityReadCursor r, CancellationToken token)
    {
        int count = r.Count(128, 4); var seen = new HashSet<string>(StringComparer.Ordinal);
        for (int i = 0; i < count; i++) { token.ThrowIfCancellationRequested(); Require(seen.Add(r.String(256, false)), "Duplicate material string"); }
        r.Align(); return count;
    }
    internal static UnityMaterialData Read(ReadOnlyMemory<byte> bytes, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested(); Require(bytes.Length <= 128 * 1024, "Material byte limit");
        var r = new UnityReadCursor(bytes); string name = r.String(1024, false); var shader = Pointer(r);
        int valid = Strings(r, token), invalid = Strings(r, token);
        r.U32(); Bool(r); Bool(r); r.Align(); r.I32(); // lightmap/GI/queue are not rendering authority
        Map(r, 64, x => x.String(256), token); Strings(r, token);
        var textures = Map(r, 64, x => new UnityMaterialTexture(Pointer(x), Float(x), Float(x), Float(x), Float(x)), token);
        Map(r, 128, x => x.I32(), token);
        var floats = Map(r, 256, Float, token);
        var colors = Map(r, 128, x => new UnityMaterialColor(Float(x), Float(x), Float(x), Float(x)), token);
        // Virtual texture stacks require a separate reviewed interpretation.
        Require(r.Count(0) == 0, "Material texture stacks unsupported"); r.Align(); r.End();
        token.ThrowIfCancellationRequested();
        return new(name, shader, valid != 0 || invalid != 0, textures.ToFrozenDictionary(StringComparer.Ordinal),
            floats.ToFrozenDictionary(StringComparer.Ordinal), colors.ToFrozenDictionary(StringComparer.Ordinal));
    }
    internal static PortraitMaterialCandidate Project(UnityMaterialData material)
    {
        Require(!material.HasKeywords && material.Shader.PathId != 0, "Portrait material shader variant unsupported");
        Require(material.Floats.TryGetValue("_UseShapeMask", out var shape) && shape == 0 &&
            material.Floats.TryGetValue("_EdgeLength", out var edge) && edge == 0 &&
            material.Floats.TryGetValue("_MaskClip", out var clip) && (clip == .06f || clip == .22f), "Portrait material mask variant unsupported");
        UnityMaterialTexture Texture(string key)
        {
            Require(material.Textures.TryGetValue(key, out var t) && t.ScaleX == 1 && t.ScaleY == 1 && t.OffsetX == 0 && t.OffsetY == 0,
                "Missing portrait texture or unreviewed UV transform"); return t!;
        }
        var texture = Texture("_ColorTextures"); var mask = Texture("_ColorMask1");
        Require(texture.Pointer.PathId != 0, "Missing portrait base texture");
        var colors = new Dictionary<string, UnityMaterialColor>(StringComparer.Ordinal);
        foreach (string part in PortraitRenderer.Parts)
        { Require(material.Colors.TryGetValue(part, out var c), "Missing portrait color"); colors.Add(part, c!); }
        // A null mask is only a claim here, not permission to substitute white. Shader validation must establish that default.
        return new(material.Name, material.Shader, texture.Pointer, mask.Pointer, material.Floats["_MaskClip"], colors.ToFrozenDictionary(StringComparer.Ordinal));
    }
}
