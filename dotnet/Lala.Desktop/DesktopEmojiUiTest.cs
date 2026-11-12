using System.Runtime.InteropServices;
using System.Collections.Immutable;
using System.Security.Cryptography;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using Avalonia.VisualTree;
using Lala.Core.Resources;
namespace Lala.Desktop;
internal static class DesktopEmojiUiTest
{
    internal static async Task RunAsync()
    {
        int checks=0;void Check(bool ok,string text){if(!ok)throw new InvalidOperationException("Emoji UI: "+text);checks++;}
        async Task Until(Func<bool> condition){using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(10));while(!condition())await Task.Delay(10,stop.Token);}
        byte[] png;
        using(var bitmap=new WriteableBitmap(new PixelSize(3,5),new Vector(96,96),PixelFormat.Rgba8888,AlphaFormat.Unpremul))
        {
            using(var frame=bitmap.Lock())for(int y=0;y<5;y++)Marshal.Copy(new byte[]{255,0,0,255,255,0,0,255,255,0,0,255},0,frame.Address+y*frame.RowBytes,12);
            using var data=new MemoryStream();bitmap.Save(data,PngBitmapEncoderOptions.Default);png=data.ToArray();
        }
        string hash=Convert.ToHexStringLower(SHA256.HashData(png));var entries=System.Collections.Immutable.ImmutableArray.Create(new EmojiGalleryEntry(1,hash,3,5),new EmojiGalleryEntry(3,hash,3,5));
        await using var view=new EmojiGalleryView();var window=new Window{Width=300,Height=200,Content=view};window.Show();
        bool current=true;byte selected=0;view.Selected+=t=>selected=t;
        var input=new EmojiGalleryView.Input("owned",entries,()=>current,_=>png);
        try
        {
            view.Update(input);await Until(()=>view.DisplayedIdentity=="owned");await Task.Delay(50);window.UpdateLayout();
            Check(view.VisibleCount==2&&view.DecodeCount==1,"shared first frame decoded once");
            var buttons=view.GetVisualDescendants().OfType<Button>().ToArray();Check(buttons.Length==2,"exact visible token count");
            buttons[1].RaiseEvent(new RoutedEventArgs(Button.ClickEvent));Check(selected==3,"row token selection");
            for(int i=0;i<10;i++)view.Update(input);
            Check(view.DecodeCount==1&&ReferenceEquals(buttons[0],view.GetVisualDescendants().OfType<Button>().First()),"unchanged updates reuse bitmaps and buttons");
            window.Width=450;await Task.Delay(50);window.UpdateLayout();Check(view.DecodeCount==1,"resize does not decode pixels");
            using(var rendered=new RenderTargetBitmap(new PixelSize(450,200),new Vector(96,96)))
            {rendered.Render(view);using var bytes=new MemoryStream();rendered.Save(bytes,PngBitmapEncoderOptions.Default);Check(bytes.Length>8,"gallery renders natively");
                if(Program.ScreenshotDirectory is {} directory){Directory.CreateDirectory(directory);File.WriteAllBytes(Path.Combine(directory,"emoji-owned.png"),bytes.ToArray());}}
            current=false;buttons[0].RaiseEvent(new RoutedEventArgs(Button.ClickEvent));Check(selected==3,"revoked click ignored");
            await Until(()=>view.DisplayedIdentity is null);Check(view.VisibleCount==0,"revocation removes all buttons");
            view.Update(new EmojiGalleryView.Input("bad",entries,()=>true,_=>new byte[40]));await Until(()=>!view.IsWorking);
            int failed=view.DecodeCount;view.Update(new EmojiGalleryView.Input("bad",entries,()=>true,_=>png));Check(!view.IsWorking&&view.DecodeCount==failed,"failed identity not retried on repaint");
            using var release=new ManualResetEventSlim();var entered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            view.Update(new EmojiGalleryView.Input("blocked",entries,()=>true,_=>{entered.TrySetResult();release.Wait();return png;}));await entered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            try
            {
                var closing=view.DisposeAsync().AsTask();Check(!closing.IsCompleted,"close waits for outstanding decoder");release.Set();await closing;
                Check(view.VisibleCount==0&&view.DisplayedIdentity is null&&!view.IsWorking,"late result cannot revive closed gallery");
            }
            finally{release.Set();}
            Check(EmojiGalleryView.FittedColumns(0,100,100)==1,"empty grid");
            Check(EmojiGalleryView.FittedColumns(2,104,58)==2,"exact grid bound");
            Check(EmojiGalleryView.FittedColumns(2,103,58) is null,"too-small grid rejected");
            var preferred=EmojiGalleryView.PreferredGrid(62,52,58,1240,760);Check(preferred is not null&&EmojiGalleryView.FittedColumns(62,preferred.Value.Width,preferred.Value.Height) is not null,"all 62 fit without scrolling");
            using var session=new DesktopSession();bool shutdown=false;using var manager=new DesktopWindows(session,()=>shutdown=true);manager.OpenMain();await Task.Delay(50);
            var picker=manager.OpenPythonFeature("emoji");await Task.Delay(50);
            var gallery=picker.GetVisualDescendants().OfType<EmojiGalleryView>().Single();
            var many=Enumerable.Range(1,62).Select(i=>new EmojiGalleryEntry((byte)i,hash,3,5)).ToImmutableArray();
            gallery.Update(new EmojiGalleryView.Input("owned-62",many,()=>true,_=>png));await Until(()=>gallery.VisibleCount==62);
            await Until(()=>{picker.UpdateLayout();return gallery.GetVisualDescendants().OfType<Button>().Count(b=>b.Bounds.Width>=48&&b.Bounds.Height>=54)==62;});
            Check(gallery.DecodeCount==1,"actual picker shares one image across 62 tokens");
            var actualButtons=gallery.GetVisualDescendants().OfType<Button>().ToArray();
            Check(actualButtons.Length==62&&actualButtons.All(b=>b.Bounds.Width>=48&&b.Bounds.Height>=54),"actual picker sizes every cell");
            Check(actualButtons.All(b=>b.TranslatePoint(new Point(0,0),gallery) is {} point&&point.X>=0&&point.Y>=0&&point.X+b.Bounds.Width<=gallery.Bounds.Width+1&&point.Y+b.Bounds.Height<=gallery.Bounds.Height+1),"all cells fit without scrolling or overlap: "+gallery.Bounds+" last="+actualButtons[^1].Bounds+" at="+actualButtons[^1].TranslatePoint(new Point(0,0),gallery));
            if(Program.ScreenshotDirectory is {} galleryDirectory)
            {
                using var capture=new RenderTargetBitmap(new PixelSize((int)Math.Ceiling(picker.Bounds.Width),(int)Math.Ceiling(picker.Bounds.Height)),new Vector(96,96));
                capture.Render(picker);using var output=File.Create(Path.Combine(galleryDirectory,"emoji-gallery-owned.png"));capture.Save(output,PngBitmapEncoderOptions.Default);
            }
            picker.Close();await Until(()=>!picker.IsVisible);Check(!gallery.IsWorking&&gallery.VisibleCount==0,"actual picker closes after clearing");
            var edit=manager.Dashboard.GetVisualDescendants().OfType<TextBox>().Single(t=>t.Name=="ChatInput");
            edit.Text="AB";edit.SelectionStart=0;edit.SelectionEnd=1;manager.Dashboard.InsertEmojiDraft(3,session.Generation);Check(edit.Text=="[Emoji3]B","insert only into local selection");
            edit.Text=new string('x',512);edit.SelectionStart=edit.SelectionEnd=512;manager.Dashboard.InsertEmojiDraft(1,session.Generation);Check(edit.Text.Length==512,"draft length bounded");
            long old=session.Generation;session.Reset();manager.Dashboard.InsertEmojiDraft(1,old);Check(edit.Text==""&&!session.CanSendGameCommands,"account replacement rejects stale draft and no send authority");
            var closingPicker=manager.OpenPythonFeature("emoji");await Task.Delay(50);
            var closingGallery=closingPicker.GetVisualDescendants().OfType<EmojiGalleryView>().Single();
            using var releaseShutdown=new ManualResetEventSlim();var shutdownEntered=new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            closingGallery.Update(new EmojiGalleryView.Input("shutdown",entries,()=>true,_=>{shutdownEntered.TrySetResult();releaseShutdown.Wait();return png;}));
            await shutdownEntered.Task.WaitAsync(TimeSpan.FromSeconds(10));
            try
            {
                manager.RequestShutdown();await Task.Delay(40);Check(!shutdown,"application shutdown waits for gallery work");
                releaseShutdown.Set();await Until(()=>shutdown);Check(!closingGallery.IsWorking&&closingGallery.VisibleCount==0,"application shutdown drains and clears gallery");
            }
            finally{releaseShutdown.Set();}
            Console.WriteLine($"Desktop emoji UI: {checks} checks passed; owned synthetic pixels, no official source acceptance.");
        }
        finally{window.Close();}
    }
}
