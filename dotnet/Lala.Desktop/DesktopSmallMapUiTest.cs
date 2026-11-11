using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Avalonia.Input;
using Avalonia.VisualTree;
using System.Reflection;
using Pointer = Avalonia.Input.Pointer;
using Lala.Core.Gameplay;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
namespace Lala.Desktop;
internal static class DesktopSmallMapUiTest
{
    internal static async Task RunAsync()
    {
        int checks=0;void Check(bool ok,string text){if(!ok)throw new InvalidOperationException("Small map UI: "+text);checks++;}
        async Task Until(Func<bool> done){using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(10));while(!done())await Task.Delay(10,stop.Token);}
        byte[] png;
        using(var bmp=new WriteableBitmap(new PixelSize(1024,1024),new Vector(96,96),PixelFormat.Rgba8888,AlphaFormat.Unpremul))
        {using(var frame=bmp.Lock()){var row=Enumerable.Repeat(new byte[]{30,120,80,255},1024).SelectMany(x=>x).ToArray();for(int y=0;y<1024;y++)Marshal.Copy(row,0,frame.Address+y*frame.RowBytes,row.Length);}using var output=new MemoryStream();bmp.Save(output,PngBitmapEncoderOptions.Default);png=output.ToArray();}
        var hash=Convert.ToHexStringLower(SHA256.HashData(png));bool current=true;
        await using var view=new SmallMapImageView();var window=new Window{Width=300,Height=300,Content=view};window.Show();
        try
        {
            var input=new SmallMapImageView.Input("owned-map",hash,()=>current,()=>png);view.Update(input);await Until(()=>view.DisplayedIdentity==input.Identity);
            Check(view.DecodeCount==1,"one decode");
            Check(view.TrySelectPixel(new(view.Bounds.Width/2,view.Bounds.Height/2),out var center)&&Math.Abs(center.X-512)<.01&&Math.Abs(center.Y-512)<.01,"double-click selection maps the rendered center to source pixels");
            int clicks=0;view.DestinationDoubleClicked+=_=>clicks++;
            void Press(int count)=>view.RaiseEvent(new PointerPressedEventArgs(view,new Pointer(1,PointerType.Mouse,true),view,new Point(view.Bounds.Width/2,view.Bounds.Height/2),0,
                new PointerPointProperties(RawInputModifiers.LeftMouseButton,PointerUpdateKind.LeftButtonPressed),KeyModifiers.None,count));
            Press(1);Check(clicks==0,"single click does not start movement");Press(2);Check(clicks==1,"double left click raises exactly one destination request");
            view.SetMarker(new SmallMapPixel(512,512));Check(view.DisplayedMarker==new SmallMapPixel(512,512),"confirmed pixel marker overlays current image");
            view.SetMarker(new SmallMapPixel(100,200));Check(view.DisplayedMarker==new SmallMapPixel(100,200)&&view.DecodeCount==1,"position changes do not decode image");
            view.SetMarker(new SmallMapPixel(double.NaN,200));Check(view.DisplayedMarker is null,"nonfinite marker hidden");
            view.SetMarker(new SmallMapPixel(512,512));for(int i=0;i<10;i++)view.Update(input);window.Width=450;await Task.Delay(50);Check(view.DecodeCount==1,"repaint and resize reuse bitmap");
            using(var render=new RenderTargetBitmap(new PixelSize(450,300),new Vector(96,96))){render.Render(view);using var output=new MemoryStream();render.Save(output,PngBitmapEncoderOptions.Default);Check(output.Length>8,"native render");}
            Check(!view.TrySelectPixel(new(0,view.Bounds.Height/2),out _),"letterbox margin cannot select a movement target");
            current=false;await Until(()=>view.DisplayedIdentity is null);Check(!view.IsWorking&&view.DisplayedMarker is null,"revocation clears bitmap and marker");
            Check(!view.TrySelectPixel(new(100,100),out _),"revoked artwork cannot select a movement target");
            view.Update(new SmallMapImageView.Input("bad",new string('0',64),()=>true,()=>png));await Until(()=>!view.IsWorking);Check(view.DisplayedIdentity is null&&view.DecodeCount==1,"bad hash rejected before native decode");
            using var release=new ManualResetEventSlim();var entered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            view.Update(new SmallMapImageView.Input("late",hash,()=>true,()=>{entered.SetResult();release.Wait();return png;}));await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            try{var close=view.DisposeAsync().AsTask();Check(!close.IsCompleted,"close awaits reader");release.Set();await close;Check(view.DisplayedIdentity is null&&!view.IsWorking,"late result cannot republish");}finally{release.Set();}
            await CheckDestinationAsync(png,Check,Until);
            Console.WriteLine($"Desktop small map UI: {checks} checks passed; synthetic pixels only.");
        }
        finally{window.Close();}
    }
    private static async Task CheckDestinationAsync(byte[] png,Action<bool,string> check,Func<Func<bool>,Task> until)
    {
        // Owned synthetic artwork, injected only in this explicit UI test process.
        var assembly=typeof(SmallMapRenderRequest).Assembly;
        object Create(string type,params object[] values)=>Activator.CreateInstance(assembly.GetType("Lala.Core.Resources."+type)!,BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic,null,values,null)!;
        var readback=Create("SmallMapPngReadback","owned-ui-source","owned-ui-batch",1);
        var snapshot=Create("SmallMapPngSnapshot",readback,new Dictionary<int,byte[]>{{10001,png}});
        var stage=new StageDataRow(DesktopTestData.SceneId,0,10001,0,0,0,0,0,0,0,0,0,0,1000,1000,0,0);
        var projection=assembly.GetType("Lala.Core.Resources.SmallMapProjection")!.GetMethod("Create",BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,[stage]);
        bool current=true;
        var request=(SmallMapRenderRequest)Create("SmallMapRenderRequest",snapshot,10001,(Func<bool>)(()=>current),projection!);
        using var session=new DesktopSession();var(state,labels)=DesktopTestData.Create();session.Publish(session.Generation,1,state,labels);
        session.SetGameplayState(session.Generation,true,null,[],System.Collections.Immutable.ImmutableDictionary<string,GameAutomationStatus>.Empty,new(false,"等待目的地"));
        session.AttachGameSender(session.Generation,_=>Task.CompletedTask);
        session.SetSmallMapReader(session.Generation,_=>request);
        int starts=0;GameNavigationTarget? target=null;
        session.AttachNavigation(session.Generation,(_,_)=>throw new InvalidOperationException("preview is not needed in this UI adapter test"),
            (selected,_)=>{starts++;target=selected;return Task.CompletedTask;},()=>Task.CompletedTask);
        await using var map=new MapView(session,()=>{});var window=new Window{Width=430,Height=450,Content=map};window.Show();
        try
        {
            var picture=map.GetVisualDescendants().OfType<SmallMapImageView>().Single();await until(()=>picture.DisplayedIdentity==request.Identity);
            void Press(int count)=>picture.RaiseEvent(new PointerPressedEventArgs(picture,new Pointer(2,PointerType.Mouse,true),window,picture.TranslatePoint(new Point(picture.Bounds.Width/2,picture.Bounds.Height/2),window)!.Value,0,
                new PointerPointProperties(RawInputModifiers.LeftMouseButton,PointerUpdateKind.LeftButtonPressed),KeyModifiers.None,count));
            Press(2);check(starts==0,"disconnected map cannot start navigation");session.SetConnected(session.Generation,true);
            Press(1);check(starts==0,"map single click never calls navigation");Press(2);
            check(starts==1,$"double click invokes navigation once: starts={starts}, ready={session.CanSendGameCommands}, bounds={picture.Bounds}, status={map.GetVisualDescendants().OfType<TextBlock>().Single(t=>t.Name=="MapNavigationStatus").Text}");
            check(target is{Scene:DesktopTestData.SceneId,X:512,Y:488,Synchronize:true},"map double click passes projected coordinates to the account navigation adapter");
            current=false;Press(2);check(starts==1,"stale map cannot invoke navigation");
        }
        finally{window.Close();}
    }
}
