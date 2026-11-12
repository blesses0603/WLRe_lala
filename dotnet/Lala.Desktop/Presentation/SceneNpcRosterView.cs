using System.Collections.Immutable;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Media;
using Avalonia.Threading;
using Lala.Core.Resources;
namespace Lala.Desktop;

internal sealed class SceneNpcRosterView:Grid,IDisposable
{
    internal sealed record Input(string Identity,Func<bool> Current,Func<ImmutableArray<SceneNpcEntry>?> Read,bool Refresh=false);
    private readonly ListBox list=new(){Name="MapNpcList"};
    private readonly TextBlock status=Ui.Text("等待目前場景 NPC 資料。",11,Ui.Muted);
    private readonly TextBlock detail=Ui.Text("資料表參考；互動尚未啟用。",10,Ui.Muted);
    private readonly DispatcherTimer timer=new(){Interval=TimeSpan.FromMilliseconds(200)};
    private Input? current;private bool disposed;
    private ImmutableArray<SceneNpcEntry> displayed=[];
    internal int RowsUpdateCount {get;private set;}
    internal int VisibleCount=>list.ItemCount;
    internal string StatusText=>status.Text??"";
    internal SceneNpcEntry? Selected => current is not null && Valid(current) ? list.SelectedItem as SceneNpcEntry : null;
    internal SceneNpcRosterView()
    {
        RowDefinitions=new("*,Auto");Ui.At(this,list,0);Ui.At(this,status,0);Ui.At(this,detail,0,1);
        list.ItemTemplate=new FuncDataTemplate<SceneNpcEntry>((row,_)=>
        {var label=Ui.Text(row is null?"":$"{row.Name} [{row.NpcIndex}]{(row.LiveVisible==false?" · 隱藏":"")}",11);label.TextWrapping=TextWrapping.NoWrap;label.TextTrimming=TextTrimming.CharacterEllipsis;if(row is not null)ToolTip.SetTip(label,Describe(row));return label;});
        list.SelectionChanged+=(_,_)=>{if(current is null||!Valid(current)){Update((Input?)null);return;}detail.Text=list.SelectedItem is SceneNpcEntry row?Describe(row):"資料表參考；互動尚未啟用。";};
        timer.Tick+=(_,_)=>{if(current is not null&&!Valid(current))Update((Input?)null);else if(current is {Refresh:true} input)RefreshRows(input);};timer.Start();
    }
    private static string Describe(SceneNpcEntry row)=>$"{row.Name}\nNPC #{row.NpcId}｜索引 {row.NpcIndex}\n參考座標 ({row.X}, {row.Y})"
        +(row.LiveX is {} x&&row.LiveY is {} y?$"\n伺服器座標 ({x}, {y})":"")
        +(row.TargetX is {} tx&&row.TargetY is {} ty?$"\n移動目的地 ({tx}, {ty})":"")
        +(row.LiveVisible is {} visible?visible?"\n伺服器狀態：顯示":"\n伺服器狀態：隱藏":"")
        +$"\n事件 {row.EventCount}；互動前仍由核心核對場景與位置。";
    private static bool Valid(Input input){try{return input.Current();}catch{return false;}}
    internal void Update(SceneNpcRosterRequest? request)=>Update(request is null?(Input?)null:new Input(request.Identity,()=>request.IsCurrent,()=>request.TryReadRows(out var rows)?rows:null));
    internal void Update(SceneNpcRosterRequest? request,Lala.Core.World.WorldNpcRuntime runtime)
    {
        if(request is null){Update((Input?)null);return;}
        Update(new Input(request.Identity+":"+runtime.Revision,()=>request.IsCurrent,()=>
        {
            if(!request.TryReadRows(out var rows))return null;
            double now=System.Diagnostics.Stopwatch.GetTimestamp()/(double)System.Diagnostics.Stopwatch.Frequency;
            return rows.Select(row=>runtime.Npcs.TryGetValue(row.NpcIndex,out var live)
                ?row with{LiveX=live.X,LiveY=live.Y,TargetX=live.TargetX,TargetY=live.TargetY,LiveVisible=live.VisibleAt(now)}:row).ToImmutableArray();
        },true));
    }
    private void RefreshRows(Input input)
    {
        ImmutableArray<SceneNpcEntry>? rows;try{rows=input.Read();}catch{return;}
        if(rows is not {} captured||captured.IsDefault||captured.Length>4096||!Valid(input)||displayed.SequenceEqual(captured))return;
        ushort? selected=(list.SelectedItem as SceneNpcEntry)?.NpcIndex;
        displayed=captured;list.ItemsSource=captured;RowsUpdateCount++;
        if(selected is {} index)list.SelectedItem=captured.FirstOrDefault(r=>r.NpcIndex==index);
    }
    internal void Update(Input? input)
    {
        Dispatcher.UIThread.VerifyAccess();if(disposed)return;
        if(input is not null&&!Valid(input))input=null;
        if(input is not null&&current?.Identity==input.Identity){current=input;return;}
        current=null;displayed=[];list.ItemsSource=null;detail.Text="資料表參考；互動尚未啟用。";status.IsVisible=true;status.Text="等待目前場景 NPC 資料。";
        if(input is null)return;
        ImmutableArray<SceneNpcEntry>? rows;try{rows=input.Read();}catch{return;}
        if(rows is not {} captured||captured.IsDefault||captured.Length>4096||!Valid(input))return;
        current=input;displayed=captured;list.ItemsSource=captured;RowsUpdateCount++;status.IsVisible=captured.Length==0;status.Text="本場景尚無 NPC 資料。";
    }
    public void Dispose(){Dispatcher.UIThread.VerifyAccess();if(disposed)return;Update((Input?)null);disposed=true;timer.Stop();}
}
