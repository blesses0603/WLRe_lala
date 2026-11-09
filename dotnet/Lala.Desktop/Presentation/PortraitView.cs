using System.Buffers.Binary;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Lala.Core.Resources;

namespace Lala.Desktop;

// UI-owned one-slot worker/cache. No more than one renderer per row can run, even if
// an old callback ignores cancellation. No task completion can revive a retired row.
internal sealed class PortraitView : Border, IAsyncDisposable
{
    private sealed record Input(string Identity,Func<bool> Current,Func<CancellationToken,Task<byte[]?>> Render);
    private readonly Image image=new(){Width=40,Height=40,Stretch=Stretch.Uniform};
    private readonly TextBlock pending=new(){Text="待",Foreground=Ui.Muted,HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Center};
    private readonly DispatcherTimer timer=new(){Interval=TimeSpan.FromMilliseconds(200)};
    private Input? desired;
    private Bitmap? bitmap;
    private CancellationTokenSource? cancellation;
    private Task running=Task.CompletedTask;
    private bool working,closed;
    private string? failed;
    internal string? DisplayedIdentity {get;private set;}
    internal int RenderCount {get;private set;}
    internal bool IsWorking=>working;
    internal PortraitView()
    {
        Width=Height=40;CornerRadius=new(20);BorderBrush=Ui.BorderBrush;BorderThickness=new(1);
        var grid=new Grid();grid.Children.Add(image);grid.Children.Add(pending);Child=grid;
        timer.Tick+=(_,_)=>{if(desired is not null&&!Current(desired))Update(null);};timer.Start();
    }
    internal void Update(PortraitRenderRequest? request,bool absent=false)
    {
        if(closed)return;pending.Text=absent?"":"待";
        Update(request?.Identity,request is null?null:()=>request.IsCurrent,request is null?null:request.RenderAsync);
    }
    // Synthetic native UI tests inject only this presentation seam, never Core provenance.
    internal void Update(string? identity,Func<bool>? current,Func<CancellationToken,Task<byte[]?>>? render)
    {
        Dispatcher.UIThread.VerifyAccess();if(closed)return;
        Input? next=identity is not null&&current is not null&&render is not null?new(identity,current,render):null;
        if(next is not null&&!Current(next))next=null;
        if(desired?.Identity!=next?.Identity)
        {
            cancellation?.Cancel();ClearImage();failed=null;
        }
        desired=next;
        if(next is null){pending.IsVisible=true;return;}
        Start();
    }
    private static bool Current(Input input){try{return input.Current();}catch{return false;}}
    private void ClearImage(){image.Source=null;bitmap?.Dispose();bitmap=null;DisplayedIdentity=null;pending.IsVisible=true;}
    private void Start()
    {
        if(closed||working||desired is null||bitmap is not null||failed==desired.Identity)return;
        if(!Current(desired)){desired=null;ClearImage();return;}
        var input=desired;var stop=new CancellationTokenSource();cancellation=stop;working=true;RenderCount++;
        running=RunAsync(input,stop);
    }
    private async Task RunAsync(Input input,CancellationTokenSource stop)
    {
        Bitmap? decoded=null;
        try
        {
            decoded=await Task.Run(async()=>
            {
                var png=await input.Render(stop.Token).ConfigureAwait(false);stop.Token.ThrowIfCancellationRequested();
                if(png is null||!Current(input))return null;
                if(png.Length is <33 or >524288 || !png.AsSpan(0,8).SequenceEqual(new byte[]{137,80,78,71,13,10,26,10}) ||
                    BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(16))!=256 || BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(20))!=256)
                    throw new InvalidDataException("Portrait geometry is unsupported");
                using var stream=new MemoryStream(png,false);var result=new Bitmap(stream);
                if(result.PixelSize!=new PixelSize(256,256)){result.Dispose();throw new InvalidDataException("Portrait size changed");}
                return result;
            },stop.Token);
            if(!closed&&!stop.IsCancellationRequested&&desired?.Identity==input.Identity&&Current(input)&&Current(desired))
            {
                if(decoded is null)failed=input.Identity;
                else {ClearImage();bitmap=decoded;decoded=null;image.Source=bitmap;DisplayedIdentity=input.Identity;pending.IsVisible=false;}
            }
        }
        catch(OperationCanceledException) when(stop.IsCancellationRequested) { }
        catch(Exception) {if(!closed&&desired?.Identity==input.Identity)failed=input.Identity;}
        finally
        {
            decoded?.Dispose();working=false;if(ReferenceEquals(cancellation,stop))cancellation=null;stop.Dispose();
            if(!closed)Start();
        }
    }
    public async ValueTask DisposeAsync()
    {
        Dispatcher.UIThread.VerifyAccess();closed=true;desired=null;timer.Stop();cancellation?.Cancel();ClearImage();
        await running;
    }
}
