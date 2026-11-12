using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Media.Imaging;
using Avalonia.Controls;
using Avalonia.Platform;
namespace Lala.Desktop;
internal static class DesktopPortraitUiTest
{
    internal static async Task RunAsync()
    {
        int checks=0;void Check(bool ok,string text){if(!ok)throw new InvalidOperationException("Portrait UI: "+text);checks++;}
        async Task Until(Func<bool> predicate){using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(10));while(!predicate())await Task.Delay(10,stop.Token);}
        byte[] png;
        using(var bitmap=new WriteableBitmap(new PixelSize(256,256),new Vector(96,96),PixelFormat.Rgba8888,AlphaFormat.Unpremul))
        {
            using(var frame=bitmap.Lock())
            {
                var row=Enumerable.Range(0,1024).Select(i=>(byte)(i%4==0||i%4==3?255:0)).ToArray();
                for(int y=0;y<256;y++)Marshal.Copy(row,0,frame.Address+y*frame.RowBytes,row.Length);
            }
            using var stream=new MemoryStream();bitmap.Save(stream,PngBitmapEncoderOptions.Default);png=stream.ToArray();
        }
        await using var view=new PortraitView();bool current=true;
        var old=new TaskCompletionSource<byte[]?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var pending=new TaskCompletionSource<byte[]?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var window=new Window{Width=100,Height=100,Content=view};window.Show();
        try
        {
        Task<byte[]?> Render(CancellationToken _)=>Task.FromResult<byte[]?>(png);
        view.Update("a",()=>current,Render);await Until(()=>view.DisplayedIdentity=="a");Check(view.RenderCount==1,"initial render");
        await Task.Delay(80);window.UpdateLayout();Check(view.Bounds.Width==40&&view.Bounds.Height==40,"Python 40-pixel row layout");
        using(var drawn=new RenderTargetBitmap(new PixelSize(40,40),new Vector(96,96)))
        {drawn.Render(view);using var bytes=new MemoryStream();drawn.Save(bytes,PngBitmapEncoderOptions.Default);Check(bytes.Length>8,"native portrait row renders");}
        view.Update("a",()=>current,Render);Check(view.RenderCount==1,"same input reused");
        current=false;await Until(()=>view.DisplayedIdentity is null);Check(!view.IsWorking,"revocation clears without rendering");
        var oldStarted=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        view.Update("old",()=>true,_=>{oldStarted.TrySetResult();return old.Task;});await oldStarted.Task.WaitAsync(TimeSpan.FromSeconds(10));int started=view.RenderCount;
        view.Update("new",()=>true,Render);Check(view.RenderCount==started,"noncooperative old task bounds concurrency");
        Check(view.DisplayedIdentity is null,"changed input clears old bitmap");old.SetResult(png);
        await Until(()=>view.DisplayedIdentity=="new");Check(view.RenderCount==started+1,"only current replacement rendered");
        view.Update("bad",()=>true,_=>Task.FromResult<byte[]?>(new byte[40]));await Until(()=>!view.IsWorking);
        int failed=view.RenderCount;Check(view.DisplayedIdentity is null,"bad PNG held");
        view.Update("bad",()=>true,Render);Check(view.RenderCount==failed,"failed identity not repeatedly decoded");
        var closeStarted=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        view.Update("closing",()=>true,_=>{closeStarted.TrySetResult();return pending.Task;});await closeStarted.Task.WaitAsync(TimeSpan.FromSeconds(10));
        Task closing=view.DisposeAsync().AsTask();Check(!closing.IsCompleted,"close waits for noncooperative renderer");
        pending.SetResult(png);await closing;Check(view.DisplayedIdentity is null&&!view.IsWorking,"late result cannot revive closed view");
        int ended=view.RenderCount;view.Update("after",()=>true,Render);Check(view.RenderCount==ended,"closed view rejects more work");
        Console.WriteLine($"Desktop portrait UI: {checks} checks passed; owned synthetic pixels only.");
        }
        finally {old.TrySetResult(png);pending.TrySetResult(png);window.Close();}
    }
}
