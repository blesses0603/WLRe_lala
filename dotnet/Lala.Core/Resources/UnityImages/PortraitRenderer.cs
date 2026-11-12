namespace Lala.Core.Resources;

// Pure CPU projection of the reviewed Python mobile-gamma profile; not source admission,
// material/PPtr parsing, GPU equivalence, current publication or game authority.
internal sealed record PortraitRenderSettings(string ColorProfile, string Shader, bool HasKeywords,
    int UseShapeMask, double MaskClip, double EdgeLength, IReadOnlyDictionary<string, double[]> Colors);

internal static class PortraitRenderer
{
    internal const string ColorProfile = "official-mobile-gamma-1296";
    internal static readonly IReadOnlyList<string> Parts = Array.AsReadOnly(new[]
    {
        "_1_0_c_Color", "_1_1_HairColor", "_1_2_SkinColor", "_2_0_e_Color0", "_2_1_e_Color1", "_2_2_e_Color2",
        "_3_0_e_Color3", "_3_1_e_Color4", "_4_2_a_Color", "_3_2_s_Color", "_4_0_w_Color0", "_4_1_w_Color1", "_5_0_p_Color", "_13_EyeColor_"
    });
    private static readonly int[][] Groups = [[0, 1, 2], [3, 4, 5], [6, 7, 9], [10, 11, 8], [12, 13]];
    private static double Sat(double x) => Math.Min(1, Math.Max(0, x));
    internal static double[][] PaletteVectors(IReadOnlyDictionary<int, int> palettes, IReadOnlyDictionary<string, double[]> defaults)
    {
        ArgumentNullException.ThrowIfNull(palettes); ArgumentNullException.ThrowIfNull(defaults);
        var vectors = Parts.Select(_ => new[] { 4.0, 4.0, 4.0 }).ToArray();
        for (int i = 0; i < Parts.Count; i++)
        {
            if (!defaults.TryGetValue(Parts[i], out var value)) continue;
            BoundedSpritePixels.Check(value is { Length: >= 3 } && value.Take(3).All(double.IsFinite), "Invalid portrait material color");
            vectors[i] = value!.Take(3).ToArray();
        }
        foreach (var (group, value) in palettes)
        {
            BoundedSpritePixels.Check(group is >= 1 and <= 5 && value is >= 0 and <= 999999999, "Invalid portrait palette");
            int[] chunks = [value / 1000000, value / 1000 % 1000, value % 1000];
            for (int j = 0; j < Groups[group - 1].Length; j++)
            { int chunk = chunks[j]; vectors[Groups[group - 1][j]] = [chunk / 100, chunk / 10 % 10, chunk % 10]; }
        }
        return vectors;
    }
    private static void Shade(ReadOnlySpan<byte> source, ReadOnlySpan<byte> mask, double[][] vectors, Span<double> output)
    {
        Span<double> color = stackalloc double[3] { .4, .4, .4 };
        for (int part = 0; part < 13; part++)
        {
            int channel = part / 5;
            // Preserve the Python literals (rather than accumulated floating point labels).
            double label = (part % 5) switch { 0 => .196, 1 => .392, 2 => .588, 3 => .784, _ => .980 };
            double delta = label - mask[channel] / 255.0;
            double weight = Sat(1 - (Math.Sqrt(3 * delta * delta) - .15) * 100000);
            for (int c = 0; c < 3; c++) color[c] += weight * (vectors[part][c] * .1 - color[c]);
        }
        double a = source[3] / 255.0;
        double mx = mask[0] / 255.0, my = mask[1] / 255.0, mz = 1 - mask[2] / 255.0;
        double eyeWeight = Sat(1 - (Math.Sqrt(mx * mx + my * my + mz * mz) - .5) * 3.333333);
        for (int c = 0; c < 4; c++)
        {
            double normal, eye;
            if (c == 3) { normal = .45 * a; eye = Sat(.45 * a); }
            else
            {
                double b = source[c] / 255.0, v = color[c], e = vectors[13][c];
                double overlay = v > .416667 ? 1 - (2 - 2.4 * v) * (1 - b) : 2.4 * v * b;
                normal = b + .55 * (overlay - b);
                double eyeOverlay = .11 * e > .5 ? 1 - (2 - .22 * e) * (1 - b) : .22 * e * b;
                eye = Sat(b + .55 * (eyeOverlay - b));
            }
            double mixed = normal * a + eyeWeight * (eye - normal * a);
            output[c] = Sat(mixed + .2 * (3 * mixed * mixed - 2 * mixed * mixed * mixed - mixed));
        }
        output[3] += a;
    }
    private static (double Alpha, double Border) Circle(double u, double v, double clip, double edge)
    {
        double x = (u - .5) * 2, y = (v - .5) * 2;
        double inward = 1 - Math.Sqrt(x * x + y * y);
        if (edge == 0) return (inward > clip ? 1 : 0, 0);
        static double Smooth(double value) { double s = Sat(value); return s * s * (3 - 2 * s); }
        double outer = Smooth((inward - (clip - edge)) / edge);
        double inner = Smooth((inward - (clip - .5 * edge)) / (.5 * edge));
        return (outer, Sat(2 * (outer - inner)));
    }
    internal static byte[] Render(ReadOnlySpan<byte> baseRgba, ReadOnlySpan<byte> maskRgba,
        IReadOnlyDictionary<int, int> palettes, PortraitRenderSettings settings, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested(); ArgumentNullException.ThrowIfNull(settings);
        const int side = 256, bytes = side * side * 4;
        BoundedSpritePixels.Check(baseRgba.Length == bytes && maskRgba.Length == bytes, "Unsupported portrait geometry");
        BoundedSpritePixels.Check(settings.ColorProfile == ColorProfile && settings.Shader == "UI_ProfilePhotoWithMask" &&
            !settings.HasKeywords && settings.UseShapeMask == 0, "Unreviewed portrait shader variant");
        BoundedSpritePixels.Check(double.IsFinite(settings.MaskClip) && settings.MaskClip is >= -1 and <= 1 &&
            double.IsFinite(settings.EdgeLength) && settings.EdgeLength is >= 0 and <= 1, "Invalid portrait circle mask");
        var vectors = PaletteVectors(palettes, settings.Colors);
        byte[] source = baseRgba.ToArray(), mask = maskRgba.ToArray(), output = new byte[bytes];
        Span<double> pixel = stackalloc double[4];
        for (int y = 0; y < side; y++)
        {
            token.ThrowIfCancellationRequested();
            for (int x = 0; x < side; x++)
            {
                int offset = (y * side + x) * 4;
                Shade(source.AsSpan(offset, 4), mask.AsSpan(offset, 4), vectors, pixel);
                var (alpha, border) = Circle((x + .5) / side, (y + .5) / side, settings.MaskClip, settings.EdgeLength);
                for (int c = 0; c < 3; c++) pixel[c] += border * (1 - pixel[c]);
                pixel[3] *= alpha;
                for (int c = 0; c < 4; c++)
                {
                    BoundedSpritePixels.Check(double.IsFinite(pixel[c]), "Portrait color calculation overflow");
                    output[offset + c] = (byte)Math.Round(Sat(pixel[c]) * 255, MidpointRounding.ToEven);
                }
            }
        }
        token.ThrowIfCancellationRequested(); return output;
    }
}
