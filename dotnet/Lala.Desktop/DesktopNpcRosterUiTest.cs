using System.Collections.Immutable;
using Avalonia.Controls;
using Avalonia.VisualTree;
using Lala.Core.Resources;
namespace Lala.Desktop;
internal static class DesktopNpcRosterUiTest
{
    internal static async Task RunAsync()
    {
        int checks=0;void Check(bool ok,string message){if(!ok)throw new InvalidOperationException("NPC roster UI: "+message);checks++;}
        async Task Until(Func<bool> done){using var stop=new CancellationTokenSource(TimeSpan.FromSeconds(10));while(!done())await Task.Delay(10,stop.Token);}
        using var view=new SceneNpcRosterView();var window=new Window{Width=180,Height=300,Content=view};window.Show();bool current=true;
        ImmutableArray<SceneNpcEntry> rows=[new(8,99,"同名 NPC",uint.MaxValue,0,[7,7]),new(0,99,"同名 NPC",0,10,[])];
        var input=new SceneNpcRosterView.Input("scene-one",()=>current,()=>rows);
        try
        {
            Check(view.VisibleCount==0&&view.StatusText.Contains("等待"),"missing source is unavailable");
            view.Update(input);var list=view.GetVisualDescendants().OfType<ListBox>().Single();var items=list.ItemsSource;
            Check(view.VisibleCount==2,"source indices remain separate despite duplicate IDs/names");list.SelectedIndex=1;
            for(int n=0;n<10;n++)view.Update(input);
            Check(view.RowsUpdateCount==1&&ReferenceEquals(items,list.ItemsSource)&&list.SelectedIndex==1,"same identity reuses rows and selection");
            current=false;await Until(()=>view.VisibleCount==0);Check(list.SelectedItem is null,"revocation clears selection");
            view.Update(new SceneNpcRosterView.Input("empty",()=>true,()=>ImmutableArray<SceneNpcEntry>.Empty));
            Check(view.VisibleCount==0&&view.StatusText.Contains("本場景尚無"),"known empty differs from unavailable");
            int calls=0;view.Update(new SceneNpcRosterView.Input("late",()=>++calls==1,()=>rows));Check(view.VisibleCount==0&&view.StatusText.Contains("等待"),"revoked read never exposes rows");
            view.Update(new SceneNpcRosterView.Input("live",()=>true,()=>rows,true));list.SelectedIndex=0;
            rows=rows.SetItem(0,rows[0] with{LiveX=120,LiveY=220,TargetX=150,TargetY=250,LiveVisible=false});
            await Until(()=>view.Selected?.LiveVisible==false);
            Check(view.Selected?.NpcIndex==8&&view.Selected.LiveX==120&&view.Selected.TargetX==150,"dynamic rows refresh without treating a destination as arrival or losing selection");
            Check(view.GetVisualDescendants().OfType<TextBlock>().Any(t=>t.Text?.Contains("移動目的地 (150, 250)")==true),"live NPC detail shows server destination separately");
            current=true;view.Update(input);view.Dispose();Check(view.VisibleCount==0,"close clears rows");view.Update(input);Check(view.VisibleCount==0,"closed view rejects late update");
            Console.WriteLine($"Desktop NPC roster UI: {checks} checks passed; synthetic references, no interaction or movement.");
        }
        finally{window.Close();}
    }
}
