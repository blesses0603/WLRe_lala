using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Lala.Core.Resources;

namespace Lala.Android.Preview;

/// <summary>One cancellable image decode, current-source guarded. Never substitutes a demo portrait.</summary>
internal sealed class OfficialImageView : Border
{
    private readonly Image image = new() { Stretch = Stretch.Uniform };
    private readonly TextBlock pending = new() { Text = "待同步", FontSize = 9, Foreground = Brush.Parse("#99B5C8"), HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
    private string? identity;
    private Bitmap? bitmap;
    private CancellationTokenSource? cancellation;
    internal OfficialImageView(double size)
    {
        Width = Height = size; CornerRadius = new(10); BorderThickness = new(.7); BorderBrush = Brush.Parse("#3E7D98"); ClipToBounds = true;
        var grid = new Grid(); grid.Children.Add(image); grid.Children.Add(pending); Child = grid;
        DetachedFromVisualTree += (_, _) => { cancellation?.Cancel(); image.Source = null; bitmap?.Dispose(); bitmap = null; identity = null; };
    }
    internal void Set(PortraitRenderRequest? request) => Set(request?.Identity, request is null ? null : () => request.IsCurrent,
        request is null ? null : request.RenderAsync);
    internal void Set(SmallMapRenderRequest? request) => Set(request?.Identity, request is null ? null : () => request.IsCurrent,
        request is null ? null : _ => Task.FromResult(request.TryReadPng(out var bytes) ? bytes : null));
    internal void Set(string? key, Func<bool>? current, Func<CancellationToken, Task<byte[]?>>? render)
    {
        if (key is null || current is null || render is null || !current())
        { cancellation?.Cancel(); identity = null; image.Source = null; bitmap?.Dispose(); bitmap = null; pending.IsVisible = true; return; }
        if (identity == key) return;
        cancellation?.Cancel(); identity = key; image.Source = null; bitmap?.Dispose(); bitmap = null; pending.IsVisible = true;
        cancellation = new(); _ = DecodeAsync(key, current, render, cancellation);
    }
    private async Task DecodeAsync(string key, Func<bool> current, Func<CancellationToken, Task<byte[]?>> render, CancellationTokenSource stop)
    {
        Bitmap? decoded = null;
        try
        {
            decoded = await Task.Run(async () =>
            {
                var bytes = await render(stop.Token).ConfigureAwait(false); stop.Token.ThrowIfCancellationRequested();
                if (bytes is null || bytes.Length is < 33 or > 4194304 || !current()) return null;
                using var stream = new MemoryStream(bytes, false); var result = new Bitmap(stream);
                if (result.PixelSize.Width > 1024 || result.PixelSize.Height > 1024) { result.Dispose(); return null; }
                return result;
            }, stop.Token);
            if (!stop.IsCancellationRequested && identity == key && current() && decoded is not null)
            { bitmap = decoded; decoded = null; image.Source = bitmap; pending.IsVisible = false; }
        }
        catch (Exception) { /* Missing/retired image remains visibly pending. */ }
        finally { decoded?.Dispose(); if (ReferenceEquals(cancellation, stop)) cancellation = null; stop.Dispose(); }
    }
}
