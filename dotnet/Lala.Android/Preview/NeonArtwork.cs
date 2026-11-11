using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;

namespace Lala.Android.Preview;

/// <summary>Code-drawn interface icons; raster artwork remains separate from controls.</summary>
internal sealed class NeonIcon : Control
{
    private readonly string name;
    private readonly IBrush color;
    internal NeonIcon(string name, IBrush? color = null, double size = 22)
    {
        this.name = name; this.color = color ?? Brush.Parse("#85F4FA");
        Width = Height = size; IsHitTestVisible = false;
    }
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var path = name switch
        {
            "home" => "M3,11 L12,3 L21,11 M5,10 L5,21 L10,21 L10,15 L14,15 L14,21 L19,21 L19,10",
            "chat" => "M4,3 L20,3 Q23,3 23,6 L23,16 Q23,19 20,19 L10,19 L4,23 L4,19 Q1,19 1,16 L1,6 Q1,3 4,3 Z M6,10 L7,10 M11,10 L12,10 M16,10 L17,10",
            "users" => "M15,6 A4,4 0 1 1 7,6 A4,4 0 1 1 15,6 M3,22 L3,19 C3,12 19,12 19,19 L19,22 Z M18,3 C24,3 24,11 18,11 M20,15 Q24,15 24,22",
            "flag" => "M4,24 L4,1 M4,3 Q9,-1 14,4 Q19,8 23,3 L21,16 Q16,20 12,15 Q8,11 4,15",
            "flask" => "M8,2 L16,2 M10,2 L10,9 L3,20 Q2,23 6,23 L18,23 Q22,23 21,20 L14,9 L14,2 M7,15 L17,15",
            "hammer" => "M3,4 L8,1 L16,9 L12,13 Z M12,10 L23,21 L20,24 L9,13",
            "coffee" => "M3,8 L18,8 L18,18 Q18,23 10,23 Q3,23 3,18 Z M18,9 L22,9 Q26,16 18,16 M7,0 L7,5 M12,0 L12,5",
            "save" => "M3,1 L18,1 L23,6 L23,23 L1,23 L1,1 Z M7,1 L7,9 L17,9 L17,1 M6,23 L6,14 L18,14 L18,23",
            "up" => "M12,21 L12,3 M5,10 L12,3 L19,10",
            "down" => "M12,3 L12,21 M5,14 L12,21 L19,14",
            "mail" => "M2,4 L22,4 L22,21 L2,21 Z M2,4 L12,13 L22,4",
            "layers" => "M2,8 L12,2 L22,8 L12,14 Z M2,13 L12,19 L22,13 M2,18 L12,24 L22,18",
            "user" => "M16,7 A4,4 0 1 1 8,7 A4,4 0 1 1 16,7 M4,22 L4,19 C4,12 20,12 20,19 L20,22 Z",
            "bag" => "M5,7 L19,7 L21,22 L3,22 Z M8,10 L8,5 C8,0 16,0 16,5 L16,10",
            "cube" => "M3,6 L12,1 L21,6 L21,18 L12,23 L3,18 Z M3,6 L12,11 L21,6 M12,11 L12,23",
            "shield" => "M12,2 L21,6 L20,14 Q19,20 12,23 Q5,20 4,14 L3,6 Z M7,12 L10,15 L17,8",
            "check" => "M4,12 L9,17 L20,5",
            "refresh" => "M20,8 A9,9 0 0 0 4,5 L2,9 M2,3 L2,9 L8,9 M4,16 A9,9 0 0 0 20,19 L22,15 M16,15 L22,15 L22,21",
            "play" => "M7,3 L21,12 L7,21 Z",
            "stop" => "M5,5 L19,5 L19,19 L5,19 Z",
            "gear" => "M9,2 L15,2 L16,6 L20,6 L22,11 L19,14 L20,18 L15,21 L12,18 L8,21 L3,18 L4,14 L1,11 L3,6 L7,6 Z M16,12 A4,4 0 1 1 8,12 A4,4 0 1 1 16,12",
            "bell" => "M4,17 L6,14 L6,9 A6,6 0 0 1 18,9 L18,14 L20,17 Z M9,21 L15,21 M12,1 L12,3",
            "link" => "M9,15 L15,9 M8,16 L6,18 A4,4 0 0 1 1,12 L7,6 A4,4 0 0 1 13,7 M16,8 L18,6 A4,4 0 0 1 23,12 L17,18 A4,4 0 0 1 11,17",
            "db" => "M3,5 A9,4 0 0 0 21,5 A9,4 0 0 0 3,5 M3,5 L3,19 A9,4 0 0 0 21,19 L21,5 M3,12 A9,4 0 0 0 21,12",
            "file" => "M5,2 L15,2 L21,8 L21,23 L5,23 Z M15,2 L15,8 L21,8 M9,12 L17,12 M9,16 L17,16 M9,20 L14,20",
            "grid" => "M3,3 L9,3 L9,9 L3,9 Z M15,3 L21,3 L21,9 L15,9 Z M3,15 L9,15 L9,21 L3,21 Z M15,15 L21,15 L21,21 L15,21 Z",
            "chart" => "M3,14 L8,14 L8,22 L3,22 Z M10,8 L15,8 L15,22 L10,22 Z M17,2 L22,2 L22,22 L17,22 Z",
            "map" => "M2,5 L9,2 L16,5 L23,2 L23,20 L16,23 L9,20 L2,23 Z M9,2 L9,20 M16,5 L16,23",
            "pin" => "M12,23 C10,18 3,14 3,9 A9,9 0 1 1 21,9 C21,14 14,18 12,23 Z M15,9 A3,3 0 1 1 9,9 A3,3 0 1 1 15,9",
            "target" => "M20,12 A8,8 0 1 1 4,12 A8,8 0 1 1 20,12 M15,12 A3,3 0 1 1 9,12 A3,3 0 1 1 15,12 M12,0 L12,5 M12,19 L12,24 M0,12 L5,12 M19,12 L24,12",
            "sword" => "M4,2 L19,17 L17,19 L2,4 Z M14,20 L20,14 M17,17 L23,23 M20,20 L22,18 M18,22 L20,20",
            "walk" => "M16,3 A2,2 0 1 1 12,3 A2,2 0 1 1 16,3 M14,7 L10,13 L16,17 L17,23 M10,13 L7,22 M11,9 L7,12 L3,12 M14,8 L17,12 L21,12",
            "mountain" => "M1,21 L8,6 L13,13 L17,3 L24,21 Z M6,10 L9,12 L11,10 M15,7 L18,10 L20,8",
            "tent" => "M12,2 L24,22 L0,22 Z M12,2 L12,22 M12,9 L6,22 M12,9 L18,22",
            "star" => "M12,1 L15,9 L23,12 L15,15 L12,23 L9,15 L1,12 L9,9 Z",
            "heart" => "M12,22 L3,12 C-4,3 7,-3 12,5 C17,-3 28,3 21,12 Z",
            "search" => "M17,10 A7,7 0 1 1 3,10 A7,7 0 1 1 17,10 M15,15 L23,23",
            "lock" => "M4,10 L20,10 L20,23 L4,23 Z M7,10 L7,6 A5,5 0 0 1 17,6 L17,10 M12,15 L12,19",
            "download" => "M12,1 L12,17 M5,10 L12,17 L19,10 M2,17 L2,23 L22,23 L22,17",
            "clock" => "M23,12 A11,11 0 1 1 1,12 A11,11 0 1 1 23,12 M12,5 L12,12 L17,15",
            "trash" => "M3,5 L21,5 M8,5 L8,1 L16,1 L16,5 M5,5 L6,23 L18,23 L19,5 M10,9 L10,19 M14,9 L14,19",
            "arrow" => "M3,12 L21,12 M15,6 L21,12 L15,18",
            "chevron" => "M8,4 L16,12 L8,20",
            "plus" => "M12,3 L12,21 M3,12 L21,12",
            "minus" => "M3,12 L21,12",
            _ => "M12,2 A10,10 0 1 1 12,22 A10,10 0 1 1 12,2 M12,7 L12,8 M12,11 L12,18"
        };
        using (context.PushTransform(Matrix.CreateScale(Bounds.Width / 24, Bounds.Height / 24)))
            context.DrawGeometry(null, new Pen(color, 1.65), Geometry.Parse(path));
    }
}

internal sealed class AtlasIcon(Bitmap atlas, int index) : Control
{
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        double w = atlas.PixelSize.Width / 4.0, h = atlas.PixelSize.Height / 6.0;
        context.DrawImage(atlas, new Rect(index % 4 * w, index / 4 * h, w, h), new Rect(Bounds.Size));
    }
}

internal sealed class SheetArtwork(Bitmap atlas, int index) : Control
{
    public override void Render(DrawingContext context)
    {
        base.Render(context); double width = atlas.PixelSize.Width / 3.0;
        context.DrawImage(atlas, new Rect(index * width, 0, width, atlas.PixelSize.Height), new Rect(Bounds.Size));
    }
}

internal sealed class MascotArtwork(Bitmap image) : Control
{
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var source = new Rect(image.PixelSize.Width * .08, image.PixelSize.Height * .02, image.PixelSize.Width * .84, image.PixelSize.Height * .75);
        context.DrawImage(image, source, new Rect(Bounds.Size));
    }
}

internal sealed class CheckStepArtwork : Control
{
    private readonly bool first, last;
    internal CheckStepArtwork(bool first, bool last) { this.first = first; this.last = last; Width = 17; }
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var cyan = Brush.Parse("#70F8F1"); double x = Bounds.Width / 2, y = Bounds.Height / 2;
        context.DrawLine(new Pen(cyan, 1), new(x, first ? y : -3), new(x, last ? y : Bounds.Height + 3));
        context.DrawEllipse(Brush.Parse("#124258"), new Pen(cyan, 1.2), new Point(x, y), 6, 6);
        context.DrawLine(new Pen(cyan, 1.1), new(x - 3, y), new(x - .8, y + 2));
        context.DrawLine(new Pen(cyan, 1.1), new(x - .8, y + 2), new(x + 3.5, y - 2.5));
    }
}

internal sealed class PreviewMapArtwork(Bitmap image, MobilePreviewState state) : Control
{
    internal Action<int, int>? TargetChanged { get; set; }
    internal double Zoom { get; set; } = 1;
    internal PreviewMapArtwork(Bitmap image, MobilePreviewState state, bool interactive) : this(image, state)
    {
        Height = 252; ClipToBounds = true;
        if (interactive) PointerPressed += (_, e) =>
        {
            var p = e.GetPosition(this);
            state.TargetX = (int)Math.Clamp(((p.X / Bounds.Width - .5) / Zoom + .5) * 320, 0, 320);
            state.TargetY = (int)Math.Clamp(((p.Y / Bounds.Height - .5) / Zoom + .5) * 200, 0, 200);
            TargetChanged?.Invoke(state.TargetX, state.TargetY); InvalidateVisual();
        };
    }
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var bounds = new Rect(Bounds.Size);
        double w = image.PixelSize.Width / Zoom, h = image.PixelSize.Height / Zoom;
        context.DrawImage(image, new Rect((image.PixelSize.Width - w) / 2, (image.PixelSize.Height - h) / 2, w, h), bounds);
        context.FillRectangle(Brush.Parse("#37031B31"), bounds);
        var cyan = Brush.Parse("#61FCF4"); var gold = Brush.Parse("#FFE680");
        Point Project(double x, double y) => new(((x - .5) * Zoom + .5) * Bounds.Width, ((y - .5) * Zoom + .5) * Bounds.Height);
        Point start = Project(.4875, .435);
        Point end = Project(state.TargetX / 320.0, state.TargetY / 200.0);
        for (double t = 0; t < 1; t += .07)
        {
            var point = new Point(start.X + (end.X - start.X) * t, start.Y + (end.Y - start.Y) * t);
            context.DrawEllipse(cyan, null, point, 1.6, 1.6);
        }
        foreach (var p in new[] { new Point(.50, .07), new Point(.06, .48), new Point(.94, .48), new Point(.50, .90) })
        {
            var q = Project(p.X, p.Y);
            context.DrawEllipse(Brush.Parse("#B3063C4F"), new Pen(cyan, 1.4), q, 8, 8);
            context.DrawEllipse(cyan, null, q, 2, 2);
        }
        context.DrawEllipse(Brush.Parse("#A0584716"), new Pen(gold, 2), end, 8, 8);
        context.DrawEllipse(gold, null, end, 3, 3);
        using (context.PushTransform(Matrix.CreateTranslation(start.X, start.Y)))
            context.DrawGeometry(cyan, new Pen(Brushes.White, 1), Geometry.Parse("M0,-11 L8,8 L0,4 L-8,8 Z"));
    }
}
