using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Security.Cryptography;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Lala.Core.Resources;
namespace Lala.Desktop;

internal sealed class EmojiGalleryView : Grid,IAsyncDisposable
{
    internal sealed record Input(string Identity,ImmutableArray<EmojiGalleryEntry> Entries,Func<bool> Current,Func<byte,byte[]?> Read);
    private readonly Grid cells=new(){ColumnSpacing=4,RowSpacing=4};
    private readonly TextBlock status=Ui.Text("官方表情尚未接通；等待資源就緒。",12,Ui.Muted);
    private readonly DispatcherTimer timer=new(){Interval=TimeSpan.FromMilliseconds(200)};
    private readonly Dictionary<string,Bitmap> images=[];
    private readonly List<Button> buttons=[];
    private Input? desired;
    private string? failed;
    private CancellationTokenSource? stop;
    private Task running=Task.CompletedTask;
    private bool working,closed;
    private (int Columns,int Rows) layout;
    internal int DecodeCount {get;private set;}
    internal int VisibleCount=>buttons.Count;
    internal bool IsWorking=>working;
    internal string? DisplayedIdentity {get;private set;}
    internal event Action<byte>? Selected;
    internal event Action<int>? Ready;
    internal EmojiGalleryView()
    {
        Children.Add(cells);Children.Add(status);SizeChanged+=(_,_)=>LayoutCells();
        timer.Tick+=(_,_)=>{if(desired is not null&&!Current(desired))Update((Input?)null);};timer.Start();
    }
    internal void Update(EmojiGalleryRequest? request)=>Update(request is null?null:new Input(request.Identity,request.Entries,()=>request.IsCurrent,t=>request.TryReadPng(t,out var png)?png:null));
    private static bool Current(Input input){try{return input.Current();}catch{return false;}}
    internal void Update(Input? next)
    {
        Dispatcher.UIThread.VerifyAccess();if(closed)return;
        if(next is not null&&!Current(next))next=null;
        if(desired?.Identity!=next?.Identity||desired is not null&&!Current(desired))
        {stop?.Cancel();Clear();failed=null;}
        desired=next;if(next is null)return;Start();
    }
    private void Clear()
    {
        cells.Children.Clear();buttons.Clear();foreach(var image in images.Values)image.Dispose();images.Clear();
        DisplayedIdentity=null;status.IsVisible=true;status.Text="官方表情尚未接通；等待資源就緒。";
    }
    private void Start()
    {
        if(closed||working||desired is null||DisplayedIdentity==desired.Identity||failed==desired.Identity)return;
        if(!Current(desired)){Update((Input?)null);return;}
        var input=desired;var cancellation=new CancellationTokenSource();stop=cancellation;working=true;running=RunAsync(input,cancellation);
    }
    private async Task RunAsync(Input input,CancellationTokenSource cancellation)
    {
        var decoded=new Dictionary<string,Bitmap>();int count=0;
        try
        {
            await Task.Run(()=>
            {
                if(input.Entries.Length>255||input.Entries.Any(e=>e.Token==0)||input.Entries.Select(e=>e.Token).Distinct().Count()!=input.Entries.Length)
                    throw new InvalidDataException("Invalid emoji gallery index");
                long total=0;
                foreach(var e in input.Entries)
                {
                    cancellation.Token.ThrowIfCancellationRequested();if(!Current(input))throw new OperationCanceledException();
                    if(e.Width is <1 or >512||e.Height is <1 or >512)throw new InvalidDataException("Invalid emoji geometry");
                    if(decoded.TryGetValue(e.ImageIdentity,out var shared))
                    {if(shared.PixelSize.Width!=e.Width||shared.PixelSize.Height!=e.Height)throw new InvalidDataException("Shared emoji geometry differs");continue;}
                    var png=input.Read(e.Token);
                    if(png is null||png.Length is <33 or >1048576||(total+=png.Length)>8*1024*1024||
                        !png.AsSpan(0,8).SequenceEqual(new byte[]{137,80,78,71,13,10,26,10})||
                        BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(16))!=e.Width||BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(20))!=e.Height||
                        Convert.ToHexStringLower(SHA256.HashData(png))!=e.ImageIdentity)throw new InvalidDataException("Invalid emoji PNG identity");
                    using var stream=new MemoryStream(png,false);var image=new Bitmap(stream);count++;
                    if(image.PixelSize.Width!=e.Width||image.PixelSize.Height!=e.Height){image.Dispose();throw new InvalidDataException("Decoded emoji geometry differs");}
                    decoded.Add(e.ImageIdentity,image);
                }
            },cancellation.Token);
            if(!closed&&!cancellation.IsCancellationRequested&&desired?.Identity==input.Identity&&Current(input)&&Current(desired))
            {
                Clear();foreach(var pair in decoded)images.Add(pair.Key,pair.Value);decoded.Clear();
                foreach(var e in input.Entries)
                {
                    var icon=new Image{Source=images[e.ImageIdentity],Width=24,Height=24,Stretch=Stretch.Uniform};
                    var button=new Button{Name="Emoji"+e.Token,Padding=new Avalonia.Thickness(2),HorizontalAlignment=HorizontalAlignment.Stretch,VerticalAlignment=VerticalAlignment.Stretch,HorizontalContentAlignment=HorizontalAlignment.Center,VerticalContentAlignment=VerticalAlignment.Center,
                        Content=new StackPanel{HorizontalAlignment=HorizontalAlignment.Center,Children={icon,new TextBlock{Text=e.Token.ToString(),FontSize=12,HorizontalAlignment=HorizontalAlignment.Center}}}};
                    button.Click+=(_,_)=>{if(desired?.Identity==input.Identity&&Current(input)&&Current(desired))Selected?.Invoke(e.Token);};
                    buttons.Add(button);cells.Children.Add(button);
                }
                DisplayedIdentity=input.Identity;status.IsVisible=buttons.Count==0;status.Text="沒有可顯示的表情。";
                Ready?.Invoke(buttons.Count);LayoutCells();
            }
        }
        catch(OperationCanceledException) when(cancellation.IsCancellationRequested||!Current(input)){ }
        catch(Exception){if(!closed&&desired?.Identity==input.Identity){failed=input.Identity;status.Text="表情圖片未通過驗證；請重新準備資源。";}}
        finally
        {
            foreach(var image in decoded.Values)image.Dispose();DecodeCount+=count;working=false;
            if(ReferenceEquals(stop,cancellation))stop=null;cancellation.Dispose();if(!closed)Start();
        }
    }
    internal static int? FittedColumns(int count,double width,double height,double cellWidth=52,double cellHeight=58)
    {
        if(count==0)return 1;
        return Enumerable.Range(1,count).Select(c=>new{C=c,R=(count+c-1)/c}).Where(x=>x.C*cellWidth<=width&&x.R*cellHeight<=height)
            .OrderBy(x=>Math.Abs(width/x.C-height/x.R)).ThenBy(x=>x.C*x.R-count).ThenBy(x=>x.C).Select(x=>(int?)x.C).FirstOrDefault();
    }
    internal static (double Width,double Height)? PreferredGrid(int count,double cellWidth,double cellHeight,double maxWidth,double maxHeight)
        =>Enumerable.Range(1,Math.Max(1,count)).Select(c=>(Width:c*cellWidth,Height:Math.Max(1,(count+c-1)/c)*cellHeight))
        .Where(x=>x.Width<=maxWidth&&x.Height<=maxHeight).OrderBy(x=>Math.Abs(x.Width/x.Height-1.35)).ThenBy(x=>x.Width*x.Height)
        .ThenBy(x=>x.Width).ThenBy(x=>x.Height).Select(x=>((double Width,double Height)?)x).FirstOrDefault();
    private void LayoutCells()
    {
        if(buttons.Count==0)return;var columns=FittedColumns(buttons.Count,Bounds.Width,Bounds.Height);if(columns is null){cells.IsVisible=false;status.IsVisible=true;status.Text="視窗空間不足以同頁顯示表情；請放大視窗。";return;}
        cells.IsVisible=true;status.IsVisible=false;
        int rows=(buttons.Count+columns.Value-1)/columns.Value;
        if(layout!=(columns.Value,rows)){cells.ColumnDefinitions=new(string.Join(',',Enumerable.Repeat("*",columns.Value)));cells.RowDefinitions=new(string.Join(',',Enumerable.Repeat("*",rows)));layout=(columns.Value,rows);}
        double iconSize=Math.Clamp(Math.Min(Bounds.Width/columns.Value-28,Bounds.Height/rows-34),24,40);
        for(int i=0;i<buttons.Count;i++){SetColumn(buttons[i],i%columns.Value);SetRow(buttons[i],i/columns.Value);var image=(Image)((StackPanel)buttons[i].Content!).Children[0];image.Width=image.Height=iconSize;}
    }
    public async ValueTask DisposeAsync()
    {Dispatcher.UIThread.VerifyAccess();closed=true;desired=null;timer.Stop();stop?.Cancel();Clear();await running;}
}
