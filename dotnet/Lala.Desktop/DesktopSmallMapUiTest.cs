using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
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
            Check(view.DecodeCount==1,"one decode");for(int i=0;i<10;i++)view.Update(input);window.Width=450;await Task.Delay(50);Check(view.DecodeCount==1,"repaint and resize reuse bitmap");
            using(var render=new RenderTargetBitmap(new PixelSize(450,300),new Vector(96,96))){render.Render(view);using var output=new MemoryStream();render.Save(output,PngBitmapEncoderOptions.Default);Check(output.Length>8,"native render");}
            current=false;await Until(()=>view.DisplayedIdentity is null);Check(!view.IsWorking,"revocation clears bitmap");
            view.Update(new SmallMapImageView.Input("bad",new string('0',64),()=>true,()=>png));await Until(()=>!view.IsWorking);Check(view.DisplayedIdentity is null&&view.DecodeCount==1,"bad hash rejected before native decode");
            using var release=new ManualResetEventSlim();var entered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            view.Update(new SmallMapImageView.Input("late",hash,()=>true,()=>{entered.SetResult();release.Wait();return png;}));await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            try{var close=view.DisposeAsync().AsTask();Check(!close.IsCompleted,"close awaits reader");release.Set();await close;Check(view.DisplayedIdentity is null&&!view.IsWorking,"late result cannot republish");}finally{release.Set();}
            Console.WriteLine($"Desktop small map UI: {checks} checks passed; synthetic pixels only.");
        }
        finally{window.Close();}
    }
}
