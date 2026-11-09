using System.Buffers.Binary;
using System.Security.Cryptography;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Lala.Core.Resources;
namespace Lala.Desktop;

internal sealed class SmallMapImageView:Grid,IAsyncDisposable
{
    internal sealed record Input(string Identity,string Hash,Func<bool> Current,Func<byte[]?> Read);
    private sealed class Marker:Control
    {
        internal SmallMapPixel? Pixel;
        public override void Render(DrawingContext context)
        {
            base.Render(context);if(Pixel is not {} pixel)return;
            double size=Math.Min(Bounds.Width,Bounds.Height);if(size<=0)return;
            var center=new Point((Bounds.Width-size)/2+pixel.X*size/1024,(Bounds.Height-size)/2+pixel.Y*size/1024);
            using(context.PushClip(new Rect(Bounds.Size)))context.DrawEllipse(Brushes.Red,new Pen(Brushes.White,1),center,6,6);
        }
    }
    private readonly Marker marker=new(){IsHitTestVisible=false};private SmallMapPixel? position;
    internal SmallMapPixel? DisplayedMarker=>marker.Pixel;
    internal void SetMarker(SmallMapPixel? pixel)
    {Dispatcher.UIThread.VerifyAccess();position=pixel is {} p&&double.IsFinite(p.X)&&double.IsFinite(p.Y)&&p.X>=0&&p.X<=1024&&p.Y>=0&&p.Y<=1024?p:null;UpdateMarker();}
    private void UpdateMarker(){marker.Pixel=!closed&&DisplayedIdentity is not null&&desired is not null&&Current(desired)?position:null;marker.InvalidateVisual();}
    private readonly Image image=new(){Stretch=Stretch.Uniform};
    private readonly TextBlock status=Ui.Text("尚未同步小地圖",12,Ui.Muted);
    private readonly DispatcherTimer timer=new(){Interval=TimeSpan.FromMilliseconds(200)};
    private Input? desired;private string? failed;private Bitmap? bitmap;private CancellationTokenSource? stop;
    private Task running=Task.CompletedTask;private bool closed;
    internal int DecodeCount {get;private set;}
    internal bool IsWorking {get;private set;}
    internal string? DisplayedIdentity {get;private set;}
    internal SmallMapImageView()
    {Children.Add(image);Children.Add(marker);Children.Add(status);timer.Tick+=(_,_)=>{if(desired is not null&&!Current(desired))Update((Input?)null);};timer.Start();}
    private static bool Current(Input input){try{return input.Current();}catch{return false;}}
    internal void Update(SmallMapRenderRequest? request)=>Update(request is null?(Input?)null:new Input(request.Identity,request.PngSha256,()=>request.IsCurrent,()=>request.TryReadPng(out var png)?png:null));
    internal void Update(Input? next)
    {
        Dispatcher.UIThread.VerifyAccess();if(closed)return;if(next is not null&&!Current(next))next=null;
        if(desired?.Identity!=next?.Identity||desired is not null&&!Current(desired)){stop?.Cancel();Clear();failed=null;}
        desired=next;UpdateMarker();Start();
    }
    private void Clear(){image.Source=null;bitmap?.Dispose();bitmap=null;DisplayedIdentity=null;UpdateMarker();status.IsVisible=true;status.Text="尚未同步小地圖";}
    private void Start()
    {
        if(desired is not null&&!Current(desired)){desired=null;Clear();}
        if(closed||IsWorking||desired is null||DisplayedIdentity==desired.Identity||failed==desired.Identity)return;
        var input=desired;var cancellation=new CancellationTokenSource();stop=cancellation;IsWorking=true;running=RunAsync(input,cancellation);
    }
    private async Task RunAsync(Input input,CancellationTokenSource cancellation)
    {
        Bitmap? decoded=null;int count=0;
        try
        {
            await Task.Run(()=>
            {
                cancellation.Token.ThrowIfCancellationRequested();if(!Current(input))throw new OperationCanceledException();
                var png=input.Read();cancellation.Token.ThrowIfCancellationRequested();
                if(png is null||png.Length is <33 or >4194304||!png.AsSpan(0,8).SequenceEqual(new byte[]{137,80,78,71,13,10,26,10})||
                    BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(16))!=1024||BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(20))!=1024||
                    Convert.ToHexStringLower(SHA256.HashData(png))!=input.Hash)throw new InvalidDataException("Invalid small map PNG");
                using var stream=new MemoryStream(png,false);decoded=new Bitmap(stream);count++;
                if(decoded.PixelSize.Width!=1024||decoded.PixelSize.Height!=1024)throw new InvalidDataException("Small map geometry differs");
            },cancellation.Token);
            if(!closed&&!cancellation.IsCancellationRequested&&desired?.Identity==input.Identity&&Current(input)&&Current(desired))
            {Clear();bitmap=decoded;decoded=null;image.Source=bitmap;DisplayedIdentity=input.Identity;status.IsVisible=false;UpdateMarker();}
        }
        catch(OperationCanceledException) when(cancellation.IsCancellationRequested||!Current(input)){}
        catch(Exception){if(!closed&&desired?.Identity==input.Identity){failed=input.Identity;status.Text="小地圖未通過驗證，請重新準備資源。";}}
        finally{decoded?.Dispose();DecodeCount+=count;IsWorking=false;if(ReferenceEquals(stop,cancellation))stop=null;cancellation.Dispose();if(!closed)Start();}
    }
    public async ValueTask DisposeAsync()
    {Dispatcher.UIThread.VerifyAccess();closed=true;desired=null;timer.Stop();stop?.Cancel();Clear();await running;}
}
