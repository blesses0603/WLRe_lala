using System.Collections.Immutable;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Media;
using Avalonia.Threading;
using Lala.Core.Resources;
namespace Lala.Desktop;

internal sealed class SceneNpcRosterView:Grid,IDisposable
{
    internal sealed record Input(string Identity,Func<bool> Current,Func<ImmutableArray<SceneNpcEntry>?> Read);
    private readonly ListBox list=new(){Name="MapNpcList"};
    private readonly TextBlock status=Ui.Text("等待目前場景 NPC 資料。",11,Ui.Muted);
    private readonly TextBlock detail=Ui.Text("資料表參考；互動尚未啟用。",10,Ui.Muted);
    private readonly DispatcherTimer timer=new(){Interval=TimeSpan.FromMilliseconds(200)};
    private Input? current;private bool disposed;
    internal int RowsUpdateCount {get;private set;}
    internal int VisibleCount=>list.ItemCount;
    internal string StatusText=>status.Text??"";
    internal SceneNpcRosterView()
    {
        RowDefinitions=new("*,Auto");Ui.At(this,list,0);Ui.At(this,status,0);Ui.At(this,detail,0,1);
        list.ItemTemplate=new FuncDataTemplate<SceneNpcEntry>((row,_)=>
        {var label=Ui.Text(row is null?"":$"{row.Name} [{row.NpcIndex}]",11);label.TextWrapping=TextWrapping.NoWrap;label.TextTrimming=TextTrimming.CharacterEllipsis;if(row is not null)ToolTip.SetTip(label,Describe(row));return label;});
        list.SelectionChanged+=(_,_)=>{if(current is null||!Valid(current)){Update((Input?)null);return;}detail.Text=list.SelectedItem is SceneNpcEntry row?Describe(row):"資料表參考；互動尚未啟用。";};
        timer.Tick+=(_,_)=>{if(current is not null&&!Valid(current))Update((Input?)null);};timer.Start();
    }
    private static string Describe(SceneNpcEntry row)=>$"{row.Name}\nNPC #{row.NpcId}｜索引 {row.NpcIndex}\n參考座標 ({row.X}, {row.Y})\n事件 {row.EventCount}；非即時位置，不能互動。";
    private static bool Valid(Input input){try{return input.Current();}catch{return false;}}
    internal void Update(SceneNpcRosterRequest? request)=>Update(request is null?(Input?)null:new Input(request.Identity,()=>request.IsCurrent,()=>request.TryReadRows(out var rows)?rows:null));
    internal void Update(Input? input)
    {
        Dispatcher.UIThread.VerifyAccess();if(disposed)return;
        if(input is not null&&!Valid(input))input=null;
        if(input is not null&&current?.Identity==input.Identity){current=input;return;}
        current=null;list.ItemsSource=null;detail.Text="資料表參考；互動尚未啟用。";status.IsVisible=true;status.Text="等待目前場景 NPC 資料。";
        if(input is null)return;
        ImmutableArray<SceneNpcEntry>? rows;try{rows=input.Read();}catch{return;}
        if(rows is not {} captured||captured.IsDefault||captured.Length>4096||!Valid(input))return;
        current=input;list.ItemsSource=captured;RowsUpdateCount++;status.IsVisible=captured.Length==0;status.Text="本場景尚無 NPC 資料。";
    }
    public void Dispose(){Dispatcher.UIThread.VerifyAccess();if(disposed)return;Update((Input?)null);disposed=true;timer.Stop();}
}
