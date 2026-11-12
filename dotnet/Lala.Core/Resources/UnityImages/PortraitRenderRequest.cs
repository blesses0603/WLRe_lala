using System.Text.Json;
namespace Lala.Core.Resources;

/// <summary>Immutable render input with a live lifetime check. This is visual-only and
/// never authorizes login or packets. Reacquire before displaying cached output.</summary>
public sealed class PortraitRenderRequest
{
    private readonly PortraitCachedImage image;
    private readonly PortraitSelection selection;
    private readonly Func<bool> current;
    public string Identity { get; }
    public bool IsCurrent => current();
    internal PortraitRenderRequest(PortraitCachedImage image,PortraitSelection selection,uint role,uint? active,
        Func<bool> current)
    {
        this.image=image;this.selection=selection;this.current=current;
        Identity=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new { image.Fingerprint,selection.Key,role,active,
            Palettes=selection.Palettes.OrderBy(p=>p.Key).Select(p=>new {p.Key,p.Value}) }));
    }
    /// <summary>Bounded 256-square PNG rendered on a worker. Null means the request retired.
    /// Caller owns the returned bytes and must recheck IsCurrent before display.</summary>
    public Task<byte[]?> RenderAsync(CancellationToken token=default) => Task.Run(() =>
    {
        token.ThrowIfCancellationRequested(); if(!IsCurrent)return null;
        var png=image.RenderPng(selection.Palettes,token);
        token.ThrowIfCancellationRequested(); return IsCurrent ? png : null;
    },token);
}
