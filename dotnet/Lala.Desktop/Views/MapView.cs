using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace Lala.Desktop;

/// <summary>Compact original map layout. A missing map image never becomes a fabricated map.</summary>
public sealed class MapView : UserControl,IAsyncDisposable
{
    private readonly DesktopSession session;
    private readonly TextBlock title = Ui.Text("小地圖｜等待角色地圖", 14, bold: true);
    private readonly TextBlock position = Ui.Text("等待角色地圖同步…", 12, Ui.Muted);
    private readonly TextBlock mapMessage = Ui.Text("尚未同步小地圖", 14, Ui.Muted);
    private readonly TextBlock navigationStatus = Ui.Text("導航：等待目前地圖。", 11, Ui.Muted);
    private bool subscribed;
    private readonly SmallMapImageView picture=new();
    private readonly SceneNpcRosterView npcRoster=new();
    private readonly List<Button> gameButtons = [];
    private readonly ListBox portalList = new() { FontSize = 11 };
    private sealed record PortalChoice(ushort Index, ushort Destination, string Label)
    { public override string ToString() => Label; }
    private Button syncNavigation = null!, cancelNavigation = null!;
    private CancellationTokenSource? syncing;
    private Task? syncOperation;

    public MapView(DesktopSession session, Action openNavigation)
    {
        this.session = session;
        Name = "MapView";
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto"), Margin = new Thickness(6, 4) };
        title.Name = "MapTitle";
        title.TextWrapping = TextWrapping.NoWrap;
        title.TextTrimming = TextTrimming.CharacterEllipsis;
        title.Margin = new Thickness(0, 0, 0, 4);
        Ui.At(body, title, 0);

        var content = new Grid { ColumnDefinitions = new ColumnDefinitions("125,*") };
        var sidebar = new Grid { RowDefinitions = new RowDefinitions("*,Auto,Auto"), Margin = new Thickness(0, 0, 6, 0) };
        var portals = portalList;
        portals.Margin = new Thickness(4);
        var monsters = Ui.Text("等待怪物資料。", 11, Ui.Muted);
        monsters.Margin = new Thickness(4);
        var npc = new Grid { RowDefinitions = new RowDefinitions("*,Auto,Auto") };
        Ui.At(npc,npcRoster,0);
        var npcButtons = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*") };
        var interact = GameButton("互動", "MapNpcInteract", () =>
        {
            var npc = npcRoster.Selected ?? throw new InvalidOperationException("請先選擇 NPC。");
            return new("npc", "start", npc.NpcId, npc.NpcIndex, X: checked((int)npc.X), Y: checked((int)npc.Y), Scene: session.Snapshot.Player?.Scene ?? 0);
        });
        var next = GameButton("接續", "MapNpcContinue", () => session.Snapshot.Local.Session.NpcDialogue.Active ? new("npc", "next") : new("event", "continue"));
        foreach (var button in new[] { interact, next })
        {
            button.Padding = new Thickness(3, 2);
            button.FontSize = 11;
            button.HorizontalAlignment = HorizontalAlignment.Stretch;
        }
        Ui.At(npcButtons, interact, 0);
        Ui.At(npcButtons, next, 1);
        Ui.At(npc, npcButtons, 0, 1);
        var more = Ui.Unavailable("更多操作", "MapNpcMore");
        more.FontSize = 11;
        more.Padding = new Thickness(3, 2);
        more.HorizontalAlignment = HorizontalAlignment.Stretch;
        Ui.At(npc, more, 0, 2);
        var lists = Ui.Tabs(("傳點", portals), ("NPC", npc), ("怪物", monsters));
        lists.Name = "MapLists";
        // These three labels fit the legacy 125px sidebar without a horizontal tab scroller.
        foreach (var item in ((IEnumerable<TabItem>)lists.ItemsSource!))
        {
            item.Padding = new Thickness(4, 4);
            item.FontSize = 11;
        }
        Ui.At(sidebar, lists, 0);
        var audit = Ui.Button("逐圖核對", () =>
            navigationStatus.Text = "逐圖核對：尚未同步同版小地圖與入口資料。", "MapAudit");
        audit.FontSize = 11;
        audit.Padding = new Thickness(3, 2);
        audit.HorizontalAlignment = HorizontalAlignment.Stretch;
        Ui.At(sidebar, audit, 0, 1);
        var change = GameButton("通過選取出口", "MapPortalGo", () =>
        {
            var row = portalList.SelectedItem as PortalChoice ?? throw new InvalidOperationException("請選擇已有同版目的地的出口。");
            return new("portal", Target: row.Destination, Index: row.Index, Scene: session.Snapshot.Player?.Scene ?? 0);
        });
        change.FontSize = 11;
        change.Padding = new Thickness(3, 2);
        change.HorizontalAlignment = HorizontalAlignment.Stretch;
        Ui.At(sidebar, change, 0, 2);
        Ui.At(content, sidebar, 0);

        mapMessage.Name = "MapEmptyState";
        mapMessage.TextAlignment = TextAlignment.Center;
        position.Name = "MapPosition";
        position.TextAlignment = TextAlignment.Center;
        var missing = new Grid{RowDefinitions=new RowDefinitions("*,Auto,Auto")};
        picture.Name="SmallMapImage";Ui.At(missing,picture,0);Ui.At(missing,mapMessage,0,1);Ui.At(missing,position,0,2);
        var map = new Border
        {
            Name = "MapSurface", Background = Brush.Parse("#18232c"), Padding = new Thickness(8),
            BorderBrush = Ui.BorderBrush, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(4), Child = missing
        };
        ToolTip.SetTip(map, "取得同版小地圖與座標轉換資料後，才可在圖上顯示位置與選取目的地。");
        Ui.At(content, map, 1);
        Ui.At(body, content, 0, 1);

        var actions = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*,*"), Margin = new Thickness(0, 4, 0, 0) };
        var preview = Ui.Button("導航預覽", openNavigation, "MapOpenNavigation");
        var sync = syncNavigation = Ui.Button("同步導航", () => _ = (syncOperation = SynchronizeAsync()), "MapSyncNavigation");
        var cancel = cancelNavigation = Ui.Button("停止導航", async () => { syncing?.Cancel(); await session.StopNavigationAsync(); }, "MapCancelSync");
        var buttons = new[] { preview, sync, cancel };
        for (int i = 0; i < buttons.Length; i++)
        {
            buttons[i].FontSize = 12;
            buttons[i].Padding = new Thickness(3, 2);
            buttons[i].HorizontalAlignment = HorizontalAlignment.Stretch;
            Ui.At(actions, buttons[i], i);
        }
        Ui.At(body, actions, 0, 2);
        navigationStatus.Name = "MapNavigationStatus";
        navigationStatus.Margin = new Thickness(0, 3, 0, 0);
        Ui.At(body, navigationStatus, 0, 3);
        Content = new Border
        {
            Name = "MapFrame", Background = Ui.Panel, BorderBrush = Ui.BorderBrush,
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(7), Child = body
        };
        AttachedToVisualTree += (_, _) => Subscribe();
        DetachedFromVisualTree += (_, _) => Unsubscribe();
        Refresh();
    }

    private void Subscribe()
    {
        if (subscribed) return;
        subscribed = true;
        session.Changed += Changed;
        Refresh();
    }

    private void Unsubscribe()
    {
        if (!subscribed) return;
        subscribed = false;
        session.Changed -= Changed;
        picture.Update((Lala.Core.Resources.SmallMapRenderRequest?)null);
        npcRoster.Update((Lala.Core.Resources.SceneNpcRosterRequest?)null);
    }

    private void Changed() => Ui.OnUi(() => { if (subscribed) Refresh(); });
    private Button GameButton(string label, string name, Func<Lala.Core.Gameplay.GameAction> create)
    {
        var button = Ui.Button(label, async () =>
        {
            try { await session.ExecuteGameActionAsync(create()); navigationStatus.Text = session.ActionStatus?.Message ?? "操作已送出。"; }
            catch (Exception error) when (error is Lala.Core.Protocol.ProtocolException or InvalidOperationException) { navigationStatus.Text = error.Message; }
        }, name);
        button.IsEnabled = false; gameButtons.Add(button); return button;
    }

    private void Refresh()
    {
        var view = session.ReadView();
        syncNavigation.IsEnabled = session.CanSendGameCommands && syncing is null;
        cancelNavigation.IsEnabled = syncing is not null || session.NavigationStatus.Running || session.Automations.GetValueOrDefault("roaming")?.Enabled == true;
        foreach (var button in gameButtons) button.IsEnabled = session.CanSendGameCommands && session.ActionStatus?.Pending != true;
        var world = view.Snapshot.Local.World;
        var player = world.Player;
        var selectedPortal = (portalList.SelectedItem as PortalChoice)?.Index;
        var portalSource = session.Catalogs?.PortalObservations.Reconciled;
        var portalRows = portalSource?.Destinations.Where(pair => pair.Key.Scene == player?.Scene && pair.Value.DestinationVerified && pair.Value.Destination is > 0 && !portalSource.Issues.ContainsKey(pair.Key))
            .OrderBy(pair => pair.Key.Index).Select(pair => new PortalChoice(pair.Key.Index, pair.Value.Destination!.Value, $"{pair.Key.Index} → {view.Labels.Scene(pair.Value.Destination!.Value)}")).ToArray() ?? [];
        portalList.ItemsSource = portalRows;
        portalList.SelectedItem = portalRows.FirstOrDefault(row => row.Index == selectedPortal);
        title.Text = player is null ? "小地圖｜等待角色地圖" : "小地圖｜" + view.Labels.Scene(player.Scene);
        ToolTip.SetTip(title, title.Text);
        npcRoster.Update(player is null?null:session.ReadNpcRoster(view.Snapshot,player.Scene));
        var mapRequest=player is null?null:session.ReadSmallMap(view.Snapshot,player.Scene);picture.Update(mapRequest);
        mapMessage.Text = mapRequest is not null ? "地圖預覽" : player is null ? "尚未同步小地圖" : "此地圖的同版圖片\n尚未同步";
        var confirmed = world.Location.Confirmed;
        Lala.Core.Resources.SmallMapPixel? marker=null;
        if(player is not null&&world.Location.ConfirmedIsCurrent&&confirmed?.Scene==player.Scene&&mapRequest?.TryProjectPosition(confirmed.X,confirmed.Y,out var pixel)==true)marker=pixel;
        picture.SetMarker(marker);
        position.Text = player is not null && world.Location.ConfirmedIsCurrent && confirmed?.Scene == player.Scene
            ? $"已確認座標\n{confirmed.X}, {confirmed.Y}" : "等待角色位置同步…";
        if (syncing is null) navigationStatus.Text = player is null ? "導航：等待目前地圖。" : session.NavigationStatus.Message;
    }
    private async Task SynchronizeAsync()
    {
        if (syncing is not null) return;
        using var cancellation = new CancellationTokenSource(); syncing = cancellation;
        try
        {
            var s = session.Snapshot; var fix = s.Local.World.Location.Confirmed;
            if (s.Player is not {} player || fix is null) throw new InvalidOperationException("尚未確認本機位置。");
            navigationStatus.Text = "同步同版導航圖資…";
            await session.PreviewNavigationAsync(new(player.Scene, fix.X, fix.Y, true), cancellation.Token);
            if (subscribed) navigationStatus.Text = "導航圖資同步完成，可開啟導航選擇目的地。";
        }
        catch (OperationCanceledException) { if (subscribed) navigationStatus.Text = "已取消同步。"; }
        catch (Exception error) when (error is IOException or ArgumentException or InvalidOperationException or Lala.Core.Protocol.ProtocolException)
        { if (subscribed) navigationStatus.Text = error.Message; }
        finally { if (ReferenceEquals(syncing, cancellation)) syncing = null; }
    }
    public async ValueTask DisposeAsync(){Unsubscribe();syncing?.Cancel();if(syncOperation is {} pending)await pending;npcRoster.Dispose();await picture.DisposeAsync();}
}
